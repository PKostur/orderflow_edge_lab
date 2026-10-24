"""Build ``research/near_miss_forward/reference_daily_v1.json``: the already-seen daily return series of the five books of
``near-miss-forward-v1`` (the inputs of the forward bands), computed ONCE from the full local history with the same
functions the forward module uses, plus the reproduction check against the published numbers and the checks that the
forward module's truncated replays equal the full-history rule.

Uses the local archive caches (and the REST funding verification the original trend-core study used).  Descriptive
only: no orders, no keys.  A mismatch against a published number is reported, never tuned away.

Usage: PYTHONPATH=src .venv/Scripts/python scripts/near_miss_forward_reference.py [--output PATH] [--force]
       [--sleeves cascade,ctrend,trend_core] [--skip-equivalence]
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import numpy as np
import pandas as pd

from orderflow_edge_lab import binance_spot_archive as bsa
from orderflow_edge_lab import ctrend
from orderflow_edge_lab import leverage_sim as lev
from orderflow_edge_lab import liquidation_cascade as lc
from orderflow_edge_lab import near_miss_forward as nmf
from orderflow_edge_lab import strategy_search as ss
from orderflow_edge_lab import strategy_search_round2 as r2
from orderflow_edge_lab import trend_core_leverage as tcl

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / nmf.DEFAULT_REFERENCE
DATA_END = "2026-09-30"
CASCADE_MAX_EXIT = "2026-09-30 23:59:59"
WINDOWS = {"cascade": ("2023-07-01", "2026-09-30"), "ctrend": ("2022-06-01", "2026-09-30"),
           "trend_core": ("2023-01-01", "2026-09-30")}
PSEUDO_STARTS = ("2026-08-17", "2026-09-07", "2026-09-21")  # inside the cached history, to compare truncated replays


def log(msg: str) -> None:
    print(f"[reference {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def stats(series: pd.Series) -> dict[str, Any]:
    s = ss.perf_stats(series, 365)
    return {k: s[k] for k in ("days", "sharpe", "newey_west_t", "cumulative_return", "max_drawdown")}


def series_entry(series: pd.Series, window: tuple[str, str], note: str) -> dict[str, Any]:
    return {"window": list(window), "note": note, "stamps": [t.isoformat() for t in series.index],
            "values": [float(v) for v in series.to_numpy()], "stats_365": stats(series),
            "series_sha256": ss.series_sha256(series)}


def compare(label: str, published: float | None, reproduced: float | None, tol: float) -> dict[str, Any]:
    ok = published is not None and reproduced is not None and abs(published - reproduced) <= tol
    return {"quantity": label, "published": published, "reproduced": reproduced,
            "abs_diff": None if published is None or reproduced is None else abs(published - reproduced),
            "tolerance": tol, "match": bool(ok)}


# ------------------------------------------------------------------------------------------------------- cascade


def cascade_reference(equivalence: bool) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    round_cfg = json.loads((ROOT / nmf.DEFAULT_ROUND2_CONFIG).read_text(encoding="utf-8"))
    uni = json.loads((ROOT / nmf.DEFAULT_UNIVERSE).read_text(encoding="utf-8"))
    spec = lc.candidate_spec(round_cfg)
    log("cascade: loading full history from the local cache")
    data = lc.load_data(list(uni["symbols"]), end=DATA_END, workers=24)
    inputs = lc.make_inputs(data, max_exit=CASCADE_MAX_EXIT)
    weights = lc.cascade_weights(inputs.data, spec["params"])
    trades = lc.build_trades(weights, inputs, None, lc.COST_BPS_ROUND_TRIP)
    lo, hi = ss._utc_ts(WINDOWS["cascade"][0]), ss._utc_ts(WINDOWS["cascade"][1])
    exit_day = pd.DatetimeIndex(trades["exit_time"]).normalize()
    val = trades.loc[np.asarray((exit_day >= lo) & (exit_day <= hi))].reset_index(drop=True)
    frames = lc.mark_with_perp_fallback(inputs.mark, inputs.perp_hl)
    gate = lc.daily_detail(trades, [(ss._utc_ts(spec["development"][0]), ss._utc_ts(spec["development"][1])), (lo, hi)])
    gate_val = gate.loc[(gate.index >= lo) & (gate.index <= hi), "net"]
    published = json.loads((ROOT / "research/strategy_search_v3/round2_results.json").read_text(encoding="utf-8"))
    pv = published["candidates"][0]["validation"]
    pl = json.loads((ROOT / "research/strategy_search_v3/round2_leverage.json").read_text(encoding="utf-8"))
    pl = pl["leverage_assessment"]["levels"]
    series: dict[str, Any] = {}
    comparisons = [compare("cascade validation Sharpe (gate accounting, 1x)", pv["sharpe"], stats(gate_val)["sharpe"], 1e-6),
                   compare("cascade validation cumulative return (gate accounting)", pv["cumulative_return"],
                           stats(gate_val)["cumulative_return"], 1e-6),
                   compare("cascade validation max drawdown (gate accounting)", pv["max_drawdown"],
                           stats(gate_val)["max_drawdown"], 1e-6)]
    for level in nmf.CASCADE_LEVELS:
        daily, n_liq, _ = nmf.cascade_book(val, frames, level, lo, hi)
        series[f"cascade_{level}x"] = series_entry(
            daily, WINDOWS["cascade"], "validation window, daily account return by exit day (leverage_sim), zero-filled")
        eq = float((1.0 + daily).prod())
        comparisons.append(compare(f"cascade {level}x final equity (leverage_sim, round2_leverage.json)",
                                   pl[str(level)]["historical_final_equity"], eq, 1e-6))
        comparisons.append(compare(f"cascade {level}x liquidations", float(pl[str(level)]["n_liquidations"]),
                                   float(n_liq), 0.0))
    prov = {"frame_sha256": {k: ss.frame_sha256(f) for k, f in inputs.data.items()},
            "oi_provenance_sha256": sha256(json.dumps(data["provenance"]["oi"], sort_keys=True, default=str).encode()).hexdigest(),
            "symbols": list(uni["symbols"]), "max_exit": CASCADE_MAX_EXIT, "round2_params": spec["params"]}
    equiv: list[dict[str, Any]] = []
    if equivalence:
        end_ts = pd.Timestamp(DATA_END, tz="UTC") + pd.Timedelta(days=1)
        for s in PSEUDO_STARTS:
            start = ss._utc_ts(s)
            log(f"cascade: truncated replay for pseudo start {s}")
            books, info = nmf.cascade_sleeve_auto(
                lambda rs: nmf.load_cascade_data(list(uni["symbols"]), replay_start=rs, end=DATA_END), round_cfg, start,
                end_ts)
            full = trades.loc[(trades["entry_time"] > start) & (trades["exit_time"] < end_ts)]
            a = {(t["symbol"], t["entry_time"], t["side"]): t["unit_return"] for t in info["trades"]}
            b = {(r.symbol, r.entry_time.isoformat(), int(r.side)): float(r.unit_return) for r in full.itertuples()}
            same_keys = set(a) == set(b)
            max_diff = max((abs(a[k] - b[k]) for k in set(a) & set(b)), default=0.0)
            equiv.append({"sleeve": "cascade", "pseudo_start": s, "warmup_days": info["warmup_days"], "trades_truncated": len(a), "trades_full": len(b),
                          "same_trade_set": same_keys, "only_in_truncated": len(set(a) - set(b)),
                          "only_in_full": len(set(b) - set(a)), "max_abs_unit_return_diff": max_diff,
                          "match": bool(same_keys and max_diff < 1e-12)})
    return series, {"cascade": prov}, comparisons + [{"equivalence": e} for e in equiv]


# -------------------------------------------------------------------------------------------------------- CTREND


def ctrend_reference(equivalence: bool) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    log("ctrend: loading the full spot universe from the local cache")
    panel = bsa.load_universe(end=DATA_END, workers=24)
    data = {"close": panel["close"], "high": panel["high"], "low": panel["low"], "dollar_volume": panel["quote_volume"]}
    weights = ctrend.ctrend_weights(data, r2.DEFAULT_PARAMS[r2.CTREND_ID])
    detail = r2.buy_and_hold_detail(weights, panel["close"], nmf.CTREND_COST_BPS_ROUND_TRIP)
    lo, hi = ss._utc_ts(WINDOWS["ctrend"][0]), ss._utc_ts(WINDOWS["ctrend"][1])
    val = detail["net"].loc[(detail.index >= lo) & (detail.index <= hi)]
    published = json.loads((ROOT / "research/strategy_search_v1/round2_results.json").read_text(encoding="utf-8"))
    pv = published["candidates"][0]["validation"]
    got = stats(val)
    comparisons = [compare("CTREND validation Sharpe", pv["sharpe"], got["sharpe"], 1e-6),
                   compare("CTREND validation cumulative return", pv["cumulative_return"], got["cumulative_return"], 1e-6),
                   compare("CTREND validation Newey-West t", pv["newey_west_t"], got["newey_west_t"], 1e-6)]
    series = {"ctrend_1x": series_entry(val, WINDOWS["ctrend"],
                                        "validation window, weekly buy-and-hold net of 20 bps round trip, stamp = day")}
    prov = {"close_frame_sha256": ss.frame_sha256(panel["close"]),
            "dollar_volume_frame_sha256": ss.frame_sha256(panel["quote_volume"]),
            "rows": int(len(panel["close"])), "symbols_used": int(panel["close"].shape[1])}
    equiv: list[dict[str, Any]] = []
    if equivalence:
        log("ctrend: loading the truncated panel the forward module uses")
        tp = nmf.load_spot_panel(start=nmf.CTREND_HISTORY_START, end=DATA_END)
        tp = nmf.trim_incomplete_tail(tp)
        replay = nmf.ctrend_replay(tp, ss._utc_ts(PSEUDO_STARTS[0]))
        last_sundays = [d for d in weights.index[weights.index.dayofweek == 6] if d >= ss._utc_ts("2026-06-01")]
        wt = replay.weights.reindex(index=last_sundays)
        wf = weights.reindex(index=last_sundays)
        # a relisted ticker is split into SYM / SYM#2 where the gap falls inside the loaded history: same coin, so
        # weights are compared per base symbol
        base = lambda frame: frame.T.groupby(lambda c: str(c).split("#", 1)[0]).sum().T  # noqa: E731
        wt, wf = base(wt), base(wf)
        cols = sorted(set(wt.columns) | set(wf.columns))
        diff = (wt.reindex(columns=cols).fillna(0.0) - wf.reindex(columns=cols).fillna(0.0)).abs().max().max()
        dn = replay.detail["net"]
        common = dn.index.intersection(detail["net"].index)
        common = common[common >= ss._utc_ts("2026-06-08")]
        net_diff = float((dn.loc[common] - detail["net"].loc[common]).abs().max())
        equiv.append({"sleeve": "ctrend", "weights_compared_sundays": len(last_sundays),
                      "max_abs_weight_diff": float(diff), "daily_net_days_compared": int(len(common)),
                      "max_abs_daily_net_diff": net_diff, "match": bool(diff < 1e-9 and net_diff < 1e-9),
                      "truncated_history_start": nmf.CTREND_HISTORY_START})
    return series, {"ctrend": prov}, comparisons + [{"equivalence": e} for e in equiv]


# ----------------------------------------------------------------------------------------------------- trend core


def trend_reference(equivalence: bool, use_rest: bool) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    core = json.loads((ROOT / nmf.DEFAULT_CORE_CONFIG).read_text(encoding="utf-8"))
    mexc = [str(s) for s in core["groups"]["crypto"]]
    available, missing = tcl.split_symbols(mexc)
    frames, funding, marks = {}, {}, {}
    for name, sym in available.items():
        perp = tcl.load_hourly(sym, "perp", end=DATA_END)
        frames[sym], _ = tcl.build_8h_bars(perp)
        funding[sym] = tcl.load_funding(sym, end=DATA_END)
        marks[sym], _, _ = tcl.mark_with_fallback(tcl.load_hourly(sym, "mark", end=DATA_END), perp)
    run_core = {**core, "source": {**core["source"], "symbols": list(available.values())}}
    log("trend core: full-history sleeves (REST funding verification as in the original study)")
    run = tcl.run_sleeves_detailed(run_core, frames, funding, rest_fetch=bsa.http_fetch if use_rest else None)
    episodes = run.episodes
    paths = [tcl.episode_adverse_path(e, marks.get(e["symbol"])) for e in episodes]
    account = run.daily.mean(axis=1).dropna()
    keep = tcl.trim_leading_zero(account).index
    assessment = json.loads((ROOT / tcl.RESULT_RELPATH).read_text(encoding="utf-8"))["result"]["levels"]["from_2023"]
    series: dict[str, Any] = {}
    comparisons: list[dict[str, Any]] = []
    cfg = lev.LeverageConfig()
    full_daily: dict[int, pd.Series] = {}
    for level in nmf.TREND_LEVELS:
        sim = tcl.simulate_level(run.intervals, episodes, paths, level, config=cfg)
        daily = sim["daily"].loc[sim["daily"].index.isin(keep)]
        full_daily[level] = daily
        w = tcl.window(daily, *WINDOWS["trend_core"])
        series[f"trend_core_{level}x"] = series_entry(
            w, WINDOWS["trend_core"], "assessment window, daily account return, stamp d covers day d-1")
        n_liq = int(sum(pd.Timestamp(x["time"]) >= w.index[0] - pd.Timedelta(days=1) for x in sim["liquidations"]
                        if pd.Timestamp(x["time"]) <= w.index[-1]))
        pub = assessment[str(level)]
        eq = float((1.0 + w).prod())
        comparisons += [compare(f"trend core {level}x final equity 2023-26 (assessment_v1.json)", pub["final_equity"], eq, 1e-9),
                        compare(f"trend core {level}x annual return 2023-26", pub["annual_return"],
                                float(eq ** (365.0 / len(w)) - 1.0), 1e-9),
                        compare(f"trend core {level}x liquidations 2023-26", float(pub["n_liquidations"]), float(n_liq), 0.0)]
    prov = {"input_sha256": tcl.input_digest(available), "symbols_used": available, "symbols_missing_from_cache": missing,
            "funding_rest_repairs": {k: len(v["repaired_from_rest"]) for k, v in run.funding_rest.items()}}
    equiv: list[dict[str, Any]] = []
    if equivalence:
        end_ts = pd.Timestamp(DATA_END, tz="UTC") + pd.Timedelta(days=1)
        tdata = nmf.load_trend_data(core, history_start=nmf.TREND_HISTORY_START, end=DATA_END)
        for s in PSEUDO_STARTS:
            start = ss._utc_ts(s)
            log(f"trend core: truncated replay for pseudo start {s}")
            books, info = nmf.trend_core_sleeve(core, tdata, start, end_ts)
            full_eps = {(e["sleeve"], pd.Timestamp(e["entry_time"]).isoformat()): e for e in episodes
                        if pd.Timestamp(e["entry_time"]) > start}
            t_eps = {(e["sleeve"], e["entry_time"]): e for e in info["episodes"]}
            same = set(full_eps) == set(t_eps)
            net_diff = max((abs(full_eps[k]["net_return"] - t_eps[k]["net_return"]) for k in set(full_eps) & set(t_eps)),
                           default=0.0)
            order = [i for i, e in enumerate(episodes) if pd.Timestamp(e["entry_time"]) > start]
            neutral = nmf.neutralized_intervals(run.intervals, episodes, set(order))
            row: dict[str, Any] = {"sleeve": "trend_core", "pseudo_start": s, "episodes_truncated": len(t_eps),
                                   "episodes_full": len(full_eps), "same_episode_set": same,
                                   "max_abs_episode_net_return_diff": float(net_diff)}
            for level in nmf.TREND_LEVELS:
                sim = tcl.simulate_level(neutral, [episodes[i] for i in order], [paths[i] for i in order], level, config=cfg)
                ref = sim["daily"].dropna()
                ref = ref.loc[ref.index >= start.normalize() + pd.Timedelta(days=1)]
                got = books[f"trend_core_{level}x"].daily
                common = ref.index.intersection(got.index)
                row[f"max_abs_daily_diff_{level}x"] = float((ref.loc[common] - got.loc[common]).abs().max()) \
                    if len(common) else 0.0
                row[f"days_compared_{level}x"] = int(len(common))
            row["match"] = bool(same and net_diff < 1e-9 and all(
                row[f"max_abs_daily_diff_{lv}x"] < 1e-9 for lv in nmf.TREND_LEVELS))
            equiv.append(row)
    return series, {"trend_core": prov}, comparisons + [{"equivalence": e} for e in equiv]


# ------------------------------------------------------------------------------------------------------------ main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(OUTPUT))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--sleeves", default="cascade,ctrend,trend_core")
    parser.add_argument("--skip-equivalence", action="store_true")
    parser.add_argument("--no-rest", action="store_true", help="trend core: no REST funding verification")
    args = parser.parse_args(argv)
    out = Path(args.output)
    if out.exists() and not args.force:
        print(f"refusing to overwrite {out} (use --force)", file=sys.stderr)
        return 2
    wanted = args.sleeves.split(",")
    series: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    comparisons: list[dict[str, Any]] = []
    jobs = {"cascade": lambda: cascade_reference(not args.skip_equivalence),
            "ctrend": lambda: ctrend_reference(not args.skip_equivalence),
            "trend_core": lambda: trend_reference(not args.skip_equivalence, not args.no_rest)}
    for name in wanted:
        s, p, c = jobs[name]()
        series.update(s)
        provenance.update(p)
        comparisons += c
    mismatches = [c for c in comparisons if ("match" in c and not c["match"]) or ("equivalence" in c and not c["equivalence"]["match"])]
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except OSError:
        commit = None
    payload = {
        "schema_version": 1, "watch_id": nmf.WATCH_ID, "kind": "reference daily series (already seen) for the forward bands",
        "generated_utc": datetime.now(timezone.utc).isoformat(), "git_head_at_generation": commit,
        "data_end": DATA_END, "windows": {k: list(v) for k, v in WINDOWS.items()},
        "config_sha256": {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in
                          (nmf.DEFAULT_CONFIG, nmf.DEFAULT_ROUND2_CONFIG, nmf.DEFAULT_CORE_CONFIG, nmf.DEFAULT_UNIVERSE)},
        "code_sha256": {"src/orderflow_edge_lab/near_miss_forward.py":
                        sha256((ROOT / "src/orderflow_edge_lab/near_miss_forward.py").read_bytes()).hexdigest(),
                        "scripts/near_miss_forward_reference.py": sha256(Path(__file__).read_bytes()).hexdigest()},
        "provenance": provenance, "reproduction_checks": comparisons, "all_checks_match": not mismatches,
        "series": series,
        "claims": {"strategy_promotion_authorized": False, "paper_trading_authorized": False,
                   "live_trading_authorized": False, "orders_sent": False}}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    for c in comparisons:
        print(json.dumps(c, default=str))
    print(f"wrote {out}; mismatches: {len(mismatches)}")
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
