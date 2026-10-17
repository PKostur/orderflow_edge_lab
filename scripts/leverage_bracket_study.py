"""Single-run runner of leverage-bracket-study-v1 (descriptive; config/leverage_bracket_study_v1.json is the spec).

Writes research/leverage_bracket/result_v1.json, RESULT.md and provenance (digests of the config, the code and the
stored 1m arrays).  Refuses to overwrite an existing result.  Paper only; no orders.
Usage: PYTHONPATH=src .venv/Scripts/python scripts/leverage_bracket_study.py [--workers 8]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time

from orderflow_edge_lab import leverage_bracket as lb
from orderflow_edge_lab import leverage_bracket_data as bdata
from orderflow_edge_lab import leverage_sim, review_methods

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "leverage_bracket_study_v1.json"
AMENDMENT = ROOT / "config" / "leverage_bracket_study_v1_amendment_1.json"
EXPECTED_TRIMS = {"WAVESUSDT": "2024-06-11", "SXPUSDT": "2025-12-05"}  # amendment 1
STUDY_PATHS = ("src/orderflow_edge_lab/leverage_bracket*.py", "scripts/leverage_bracket*.py",
               "config/leverage_bracket_study_v1.json", "config/leverage_bracket_study_v1_amendment_1.json",
               "tests/test_leverage_bracket.py")
UNIVERSE = ROOT / "research" / "strategy_search_v3" / "round2_universe.json"
DATA_DIR = ROOT / "artifacts" / "leverage_bracket_cache"
OUT_DIR = ROOT / "research" / "leverage_bracket"


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()
    except OSError:
        return ""


def dirty_files() -> list[str]:
    """Study code / config / test files with uncommitted changes (untracked files count)."""
    out = _git("status", "--porcelain", "--", *STUDY_PATHS)
    return [line for line in out.splitlines() if line.strip()]


def check_trims(trims: dict, symbols: list[str]) -> None:
    """The stale-tail trim dates must be exactly those of amendment 1 (YFIIUSDT: no bars in sample)."""
    got = {s: d for s, d in trims.items() if d and d != "no bars in sample"}
    if got != EXPECTED_TRIMS:
        raise SystemExit(f"stale-tail trims {got} differ from amendment 1 {EXPECTED_TRIMS}")
    if "YFIIUSDT" in symbols and trims.get("YFIIUSDT") != "no bars in sample":
        raise SystemExit("YFIIUSDT expected to have no bars in the sample")


def provenance(data_dir: Path, symbols: list[str], config: Path, workers: int, trims: dict) -> dict:
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    sim = Path(leverage_sim.__file__)
    review = Path(review_methods.__file__)
    return {
        "config_sha256": bdata.digest_file(config),
        "amendment_sha256": bdata.digest_file(AMENDMENT),
        "engine_sha256": bdata.digest_file(Path(lb.__file__)),
        "data_loader_sha256": bdata.digest_file(Path(bdata.__file__)),
        "runner_sha256": bdata.digest_file(Path(__file__)),
        "leverage_sim_sha256": bdata.digest_file(sim),
        "review_methods_sha256": bdata.digest_file(review),
        "universe_sha256": bdata.digest_file(UNIVERSE),
        "manifest_sha256": bdata.digest_file(data_dir / "manifest.json"),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(dirty_files()),
        "symbols": symbols,
        "array_sha256": manifest["array_digests"],
        "stale_tail_trim_start": {s: d for s, d in trims.items() if d and d != "no bars in sample"},
        "no_bars_in_sample": sorted(s for s, d in trims.items() if d == "no bars in sample"),
        "kline_zip_sha256": {e["symbol"]: [[f["file"], f["sha256"]] for f in e["files"]] for e in manifest["symbols"]},
        "data_quality": {e["symbol"]: {k: e.get(k) for k in ("bars", "missing_inside_span", "gap_count",
                                                          "longest_gap_minutes", "ohlc_violations")}
                         for e in manifest["symbols"]},
        "seed": lb.SEED, "workers": workers,
    }


def _pct(x, nd=2):
    return "" if x is None else f"{100 * x:.{nd}f}"


def markdown(result: dict) -> str:
    v = result["viability"]
    trims = result["provenance"]["stale_tail_trim_start"]
    lines = ["# leverage-bracket-study-v1 result (descriptive; no promotion, no orders)", "",
             f"Viable cells (BH q=0.10, both halves lower bound > 0, P(ruin 365d) <= 5%): "
             f"{', '.join(v['viable_cells']) or 'none'}", "",
             "EV is net per trade in % of margin (95% day-block bootstrap interval); win% = share of trades with "
             "net > 0; TP% = take-profit hit rate; BE = break-even win rate after costs, fair = driftless P(TP first) "
             "before costs. A BE% above 100 means the cell cannot be won even at a 100% TP rate. Account columns "
             "(final eq, maxDD, P(ruin)) are realized-equity based: equity changes only when positions close.", "",
             f"Stale-tail trims (not traded): {trims}; no bars in sample: "
             f"{result['provenance']['no_bars_in_sample']}.", "",
             "| cell | trades | win% (net>0) | TP% | BE% | fair% | liq% | stop% | time% | ambig | fee% | fund% | EV | 95% CI | "
             "final eq | maxDD% | P(ruin) | q |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in result["cells"]:
        if not c.get("trades"):
            lines.append(f"| {c['cell']} | 0 |" + " |" * 16)
            continue
        eb, a = c["ev_bootstrap"]["full"], c.get("account", {})
        lines.append(
            f"| {c['cell']} | {c['trades']} | {_pct(c['win_rate'], 1)} | {_pct(c['take_profit_rate'], 1)} | {_pct(c['break_even_win_rate'], 1)} | "
            f"{_pct(c['driftless_fair_win_rate'], 1)} | {_pct(c['liquidation_rate'], 2)} | {_pct(c['stop_rate'], 1)} | "
            f"{_pct(c['time_stop_rate'], 2)} | {c['same_bar_ambiguous']} | {c['fees_pct_margin_per_trade']:.2f} | "
            f"{c['funding_pct_margin_per_trade']:.3f} | {c['net_ev_pct_margin_per_trade']:.3f} | "
            f"[{100 * eb['lo']:.3f}, {100 * eb['hi']:.3f}] | {a.get('final_equity', float('nan')):.4f} | "
            f"{_pct(a.get('max_drawdown'), 1)} | {_pct(a.get('ruin', {}).get('ruin_probability'), 1)} | "
            f"{v['cells'][c['cell']]['q_value']:.3f} |")
    lines += ["", "Claims: strategy_promotion_authorized=false, paper_trading_authorized=false, "
              "live_trading_authorized=false, orders_sent=false.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--data-dir", default=str(DATA_DIR))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--universe", default=str(UNIVERSE))
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    result_path, md_path = out_dir / "result_v1.json", out_dir / "RESULT.md"
    for guard in (OUT_DIR / "result_v1.json", OUT_DIR / "RESULT.md", result_path, md_path):  # single look
        if guard.exists():
            raise SystemExit(f"refusing to run: {guard} exists")
    dirty = dirty_files()
    if dirty:
        raise SystemExit("refusing to run with uncommitted study files:\n" + "\n".join(dirty))
    symbols = list(json.loads(Path(args.universe).read_text(encoding="utf-8"))["symbols"])
    data_dir = Path(args.data_dir)
    bdata.verify_manifest_digests(data_dir, symbols)
    trims = bdata.stale_tail_dates(data_dir, symbols)
    check_trims(trims, symbols)
    started = time.time()
    prov = provenance(data_dir, symbols, Path(args.config), args.workers, trims)
    study = lb.run_study(data_dir, symbols, workers=args.workers)
    result = {"study_id": "leverage-bracket-study-v1", "status": "RESULT_DESCRIPTIVE", "provenance": prov,
              "seconds": round(time.time() - started, 1), **study,
              "claims": {"strategy_promotion_authorized": False, "paper_trading_authorized": False,
                         "live_trading_authorized": False, "orders_sent": False}}
    text = markdown(result)  # built before either file is written
    lb.write_result_once(result_path, result)
    with md_path.open("x", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {result_path} and {md_path} in {result['seconds']}s; viable cells: {study['viability']['viable_cells']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
