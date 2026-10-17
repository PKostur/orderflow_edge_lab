"""Single-run runner of leverage-bracket-study-v2 (descriptive; config/leverage_bracket_study_v2.json is the spec).

Writes research/leverage_bracket_v2/result_v2.json and RESULT.md with provenance (sha256 of the configs, all code, the
tests and the stored 1m arrays of both caches).  Refuses to run with uncommitted study files, if a result exists, or if
an array digest does not match its manifest.  Paper only; no orders.
Usage: PYTHONPATH=src .venv/Scripts/python scripts/leverage_bracket_v2_study.py [--workers 8]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time

from orderflow_edge_lab import leverage_bracket as lb
from orderflow_edge_lab import leverage_bracket_data as bdata
from orderflow_edge_lab import leverage_bracket_v2 as lb2
from orderflow_edge_lab import leverage_bracket_v2_data as bdata2
from orderflow_edge_lab import leverage_sim, review_methods

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "leverage_bracket_study_v2.json"
V1_CONFIG = ROOT / "config" / "leverage_bracket_study_v1.json"
AMENDMENT = ROOT / "config" / "leverage_bracket_study_v1_amendment_1.json"
AMENDMENT_V2 = ROOT / "config" / "leverage_bracket_study_v2_amendment_1.json"
EXPECTED_V1_TRIMS = {"WAVESUSDT": "2024-06-11", "SXPUSDT": "2025-12-05"}  # amendment 1 (consistency sample cache)
STUDY_PATHS = ("src/orderflow_edge_lab/leverage_bracket*.py", "scripts/leverage_bracket*.py",
               "config/leverage_bracket_study_v1.json", "config/leverage_bracket_study_v1_amendment_1.json",
               "config/leverage_bracket_study_v2.json", "config/leverage_bracket_study_v2_amendment_1.json",
               "tests/test_leverage_bracket*.py")
UNIVERSE = ROOT / "research" / "strategy_search_v3" / "round2_universe.json"
DATA_DIR_PRIMARY = ROOT / "artifacts" / "leverage_bracket_cache_2021"
DATA_DIR_CONSISTENCY = ROOT / "artifacts" / "leverage_bracket_cache"
OUT_DIR = ROOT / "research" / "leverage_bracket_v2"
CODE_FILES = ("src/orderflow_edge_lab/leverage_bracket.py", "src/orderflow_edge_lab/leverage_bracket_data.py",
              "src/orderflow_edge_lab/leverage_bracket_v2.py", "src/orderflow_edge_lab/leverage_bracket_v2_data.py",
              "scripts/leverage_bracket_v2_study.py", "scripts/leverage_bracket_v2_download.py",
              "tests/test_leverage_bracket.py", "tests/test_leverage_bracket_v2.py")


def _git(*args: str) -> str:
    """Run git; fail closed (SystemExit) if git cannot be run or returns a non-zero code."""
    try:
        proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise SystemExit(f"refusing to run: git failed ({exc})") from exc
    if proc.returncode != 0:
        raise SystemExit(f"refusing to run: git {' '.join(args)} returned {proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def git_head() -> str:
    head = _git("rev-parse", "HEAD")
    if not head:
        raise SystemExit("refusing to run: git rev-parse HEAD is empty")
    return head


def dirty_files() -> list[str]:
    """Study code / config / test files with uncommitted changes (untracked files count)."""
    out = _git("status", "--porcelain", "--", *STUDY_PATHS)
    return [line for line in out.splitlines() if line.strip()]


def check_primary_cache(manifest: dict, trims: dict) -> None:
    """The primary cache must match the grid constants and carry no stale-tail trim (reported, not decided here)."""
    expect = {"grid_len": bdata2.GRID_LEN, "sample_start_idx": bdata2.SAMPLE_START_IDX, "dtype": "float32",
              "grid_start": str(bdata2.GRID_START)}
    bad = {k: (manifest.get(k), v) for k, v in expect.items() if manifest.get(k) != v}
    if bad:
        raise SystemExit(f"primary manifest differs from the grid constants: {bad}")
    trimmed = {sym: t for sym, t in trims.items() if t is not None}
    if trimmed:
        raise SystemExit(f"primary cache has stale-tail trims / empty symbols (none expected): {trimmed}")


def check_consistency_trims(trims: dict) -> None:
    """The consistency cache must carry exactly amendment 1's stale-tail trims."""
    got = {s: d for s, d in trims.items() if d and d != "no bars in sample"}
    if got != EXPECTED_V1_TRIMS:
        raise SystemExit(f"stale-tail trims {got} differ from amendment 1 {EXPECTED_V1_TRIMS}")


def provenance(symbols: list[str], config: Path, workers: int, trims1: dict, trims2: dict,
               dir1: Path, dir2: Path) -> dict:
    out = {
        "config_sha256": bdata.digest_file(config),
        "v1_config_sha256": bdata.digest_file(V1_CONFIG),
        "amendment_sha256": bdata.digest_file(AMENDMENT),
        "amendment_v2_sha256": bdata.digest_file(AMENDMENT_V2),
        "code_sha256": {f: bdata.digest_file(ROOT / f) for f in CODE_FILES},
        "runner_sha256": bdata.digest_file(Path(__file__)),
        "leverage_sim_sha256": bdata.digest_file(Path(leverage_sim.__file__)),
        "review_methods_sha256": bdata.digest_file(Path(review_methods.__file__)),
        "universe_sha256": bdata.digest_file(UNIVERSE),
        "git_commit": git_head(),
        "git_dirty": bool(dirty_files()),
        "symbols": symbols, "seed": lb.SEED, "workers": workers,
    }
    for label, d, trims in (("primary", dir2, trims2), ("consistency", dir1, trims1)):
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        out[label] = {
            "manifest_sha256": bdata.digest_file(d / "manifest.json"),
            "array_sha256": manifest["array_digests"],
            "stale_tail_trim_start": {s: t for s, t in trims.items() if t and t != "no bars in sample"},
            "no_bars_in_sample": sorted(s for s, t in trims.items() if t == "no bars in sample"),
            "kline_zip_sha256": {e["symbol"]: [[f["file"], f["sha256"]] for f in e["files"]] for e in manifest["symbols"]},
            "daily_zip_sha256": {e["symbol"]: [[f["file"], f["sha256"]] for f in e.get("daily_files", [])]
                                 for e in manifest["symbols"]},
            "daily_fill": {e["symbol"]: {k: v for k, v in e.get("daily_fill", {}).items() if k != "days_requested"}
                           for e in manifest["symbols"]},
            "data_quality": {e["symbol"]: {k: e.get(k) for k in ("bars", "missing_inside_span", "gap_count",
                                                              "longest_gap_minutes", "ohlc_violations")}
                             for e in manifest["symbols"]},
        }
    return out


def _pct(x, nd=2):
    return "" if x is None else f"{100 * x:.{nd}f}"


def _table(cells: list[dict], v: dict, *, with_q: bool) -> list[str]:
    head = ("| cell | trades | win% (net>0) | TP% | BE% | fair% | liq% | stop% | time% | ambig | touch-only | fee% | fund% | "
            "EV | 95% CI | final eq | maxDD% | P(ruin) | ruin day |" + (" q |" if with_q else ""))
    lines = [head, "|" + "---|" * (head.count("|") - 1)]
    ncol = head.count("|") - 2
    for c in cells:
        if not c.get("trades"):
            lines.append(f"| {c['cell']} | 0 |" + " |" * (ncol - 1))
            continue
        eb, a = c["ev_bootstrap"]["full"], c.get("account", {})
        ru = a.get("ruin", {})
        row = (f"| {c['cell']} | {c['trades']} | {_pct(c['win_rate'], 1)} | {_pct(c['take_profit_rate'], 1)} | "
               f"{_pct(c['break_even_win_rate'], 1)} | {_pct(c['driftless_fair_win_rate'], 1)} | "
               f"{_pct(c['liquidation_rate'], 2)} | {_pct(c['stop_rate'], 1)} | {_pct(c['time_stop_rate'], 2)} | "
               f"{c['same_bar_ambiguous']} | {c.get('trades_with_touch_only_bar', 0)} | "
               f"{c['fees_pct_margin_per_trade']:.2f} | {c['funding_pct_margin_per_trade']:.3f} | "
               f"{c['net_ev_pct_margin_per_trade']:.3f} | [{100 * eb['lo']:.3f}, {100 * eb['hi']:.3f}] | "
               f"{a.get('final_equity', float('nan')):.4f} | {_pct(a.get('max_drawdown'), 1)} | "
               f"{_pct(ru.get('ruin_probability'), 1)} | {'' if ru.get('ruin_day') is None else ru['ruin_day']} |")
        if with_q:
            row += f" {v['cells'][c['cell']]['q_value']:.3f} |"
        lines.append(row)
    return lines


def markdown(result: dict) -> str:
    v = result["viability"]
    prov = result["provenance"]
    lines = ["# leverage-bracket-study-v2 result (descriptive; no promotion, no orders)", "",
             f"Viable cells (BH q=0.10 over {v['n_cells']} primary cells, both primary halves lower bound > 0, "
             f"primary P(ruin 365d) <= 5%, consistency EV > 0): {', '.join(v['viable_cells']) or 'none'}", "",
             "Cell name = entry_leverage_takeprofit%_stop_timestop-hours_fee model (F1 taker, F2 maker take-profit with "
             "0.01% through-fill). EV is net per trade in % of margin (95% day-block bootstrap interval); win% = share of "
             "trades with net > 0; TP% = take-profit fill rate; BE = break-even win rate after costs, fair = driftless "
             "P(TP first) before costs; touch-only = trades that had a bar touching the take-profit price without "
             "filling (F2). Account columns are realized-equity based. P(ruin) = 100 with a ruin day means the realized "
             "path itself reached <= 0. On a ruined path min equity and max drawdown can be below 0 and below -100% "
             "(equity is not floored in those two columns; daily equity after ruin is 0).", "",
             f"Primary stale-tail trims: {prov['primary']['stale_tail_trim_start']}; no bars: "
             f"{prov['primary']['no_bars_in_sample']}. Consistency trims: {prov['consistency']['stale_tail_trim_start']}; "
             f"no bars: {prov['consistency']['no_bars_in_sample']}.", "",
             "## Primary sample 2021-01-01..2023-12-31 (halves split 2022-06-30 / 07-01)", ""]
    lines += _table(result["primary"]["cells"], v, with_q=True)
    lines += ["", "## Consistency check 2024-01-01..2026-09-30 (reading uses only EV > 0)", ""]
    lines += _table(result["consistency"]["cells"], v, with_q=False)
    lines += ["", "Claims: strategy_promotion_authorized=false, paper_trading_authorized=false, "
              "live_trading_authorized=false, orders_sent=false.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--data-dir-primary", default=str(DATA_DIR_PRIMARY))
    parser.add_argument("--data-dir-consistency", default=str(DATA_DIR_CONSISTENCY))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--universe", default=str(UNIVERSE))
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    result_path, md_path = out_dir / "result_v2.json", out_dir / "RESULT.md"
    for guard in (OUT_DIR / "result_v2.json", OUT_DIR / "RESULT.md", result_path, md_path):  # single look
        if guard.exists():
            raise SystemExit(f"refusing to run: {guard} exists")
    git_head()  # fail closed before anything else if git is unusable
    dirty = dirty_files()
    if dirty:
        raise SystemExit("refusing to run with uncommitted study files:\n" + "\n".join(dirty))
    symbols = list(json.loads(Path(args.universe).read_text(encoding="utf-8"))["symbols"])
    dir2, dir1 = Path(args.data_dir_primary), Path(args.data_dir_consistency)
    manifest2 = json.loads((dir2 / "manifest.json").read_text(encoding="utf-8"))
    if not manifest2.get("complete"):
        raise SystemExit("primary cache manifest is not complete")
    bdata.verify_manifest_digests(dir2, symbols)
    bdata.verify_manifest_digests(dir1, symbols)
    trims2 = bdata2.stale_tail_dates(dir2, symbols)
    check_primary_cache(manifest2, trims2)
    trims1 = bdata.stale_tail_dates(dir1, symbols)
    check_consistency_trims(trims1)
    started = time.time()
    prov = provenance(symbols, Path(args.config), args.workers, trims1, trims2, dir1, dir2)
    study = lb2.run_study_v2({"primary": (dir2, bdata2.primary_sample()),
                              "consistency": (dir1, bdata2.consistency_sample())}, symbols, workers=args.workers)
    result = {"study_id": "leverage-bracket-study-v2", "status": "RESULT_DESCRIPTIVE", "provenance": prov,
              "seconds": round(time.time() - started, 1), **study,
              "claims": {"strategy_promotion_authorized": False, "paper_trading_authorized": False,
                         "live_trading_authorized": False, "orders_sent": False}}
    text = markdown(result)  # built before either file is written
    payload = json.dumps(result, indent=1)  # serialized before any output file is opened
    out_dir.mkdir(parents=True, exist_ok=True)
    with result_path.open("x", encoding="utf-8") as fh:
        fh.write(payload)
    with md_path.open("x", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {result_path} and {md_path} in {result['seconds']}s; viable cells: {study['viability']['viable_cells']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
