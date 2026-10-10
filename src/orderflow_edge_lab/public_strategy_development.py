"""Descriptive diagnostics for the unchanged public-strategy v1 development run.

This code consumes the exact v1 report. It cannot alter v1 signals, trading state,
or any prospective protocol. Controls and perturbations are explicitly separate.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, stdev

from .public_strategy_shadow import Bar, iso, is_signal, read_bars, sha256_file, utc

COSTS = (10, 20, 30, 40, 60)
SEED = 20261010
BOOTSTRAPS = 2000


def week_key(value: str) -> str:
    year, week, _ = utc(value).isocalendar()
    return f"{year}-W{week:02d}"


def summarize(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "median": None}
    return {"n": len(values), "mean": mean(values), "median": median(values)}


def drawdown(returns_bps: list[float]) -> tuple[float, float]:
    equity = peak = 1.0
    max_dd = 0.0
    for value in returns_bps:
        equity *= 1 + value / 10_000
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1)
    return (equity - 1) * 100, max_dd * 100


def portfolio_equity(events: list[dict], frames: dict[str, list[Bar]], symbols: list[str]) -> dict:
    """Three equal starting cash sleeves, one per symbol, using next-open marks.

    Each sleeve reinvests its own equity, holds cash between events and pays
    10 bps on entry plus 10 bps on exit. Sleeves are not rebalanced.
    """
    starts = defaultdict(list)
    ends = defaultdict(list)
    index = {s: {iso(bar.timestamp): i for i, bar in enumerate(frames[s])} for s in symbols}
    for event in events:
        if event["status"] != "completed":
            continue
        symbol = event["symbol"]
        starts[index[symbol][event["entry_time"]]].append(symbol)
        ends[index[symbol][event["exit_time"]]].append(symbol)
    balances = {symbol: 1.0 for symbol in symbols}
    active = {symbol: False for symbol in symbols}
    curve = [1.0]
    for i in range(len(frames[symbols[0]])):
        for symbol in ends[i]:
            if not active[symbol]:
                raise ValueError("portfolio exit without entry")
            balances[symbol] *= 1 - 10 / 10_000
            active[symbol] = False
        for symbol in starts[i]:
            if active[symbol]:
                raise ValueError("portfolio overlapping entries")
            balances[symbol] *= 1 - 10 / 10_000
            active[symbol] = True
        curve.append(mean(balances.values()))
        if i + 1 < len(frames[symbols[0]]):
            for symbol in symbols:
                if active[symbol]:
                    bars = frames[symbol]
                    balances[symbol] *= bars[i + 1].open / bars[i].open
    if any(active.values()):
        raise ValueError("completed event set leaves portfolio position open")
    peak = curve[0]
    maximum_drawdown = 0.0
    for value in curve:
        peak = max(peak, value)
        maximum_drawdown = min(maximum_drawdown, value / peak - 1)
    return {"terminal_return_pct": (curve[-1] - 1) * 100,
            "max_drawdown_pct": maximum_drawdown * 100,
            "sleeve_terminal_return_pct": {s: (v - 1) * 100 for s, v in balances.items()},
            "initial_symbol_weights": {s: 1 / len(symbols) for s in symbols},
            "cost_split_bps_per_entry_and_exit": 10,
            "note": "Equal starting capital per symbol; each sleeve reinvests internally and holds cash between trades. No cross-symbol rebalancing."}


def path_metrics(bars: list[Bar], start: int, stop: int, entry: float, cost_bps: float) -> dict:
    """OHLC excursions; order of high and low within a candle is unknown."""
    held = bars[start:stop]
    mfe_at = max(range(len(held)), key=lambda j: held[j].high)
    mfe = (held[mfe_at].high / entry - 1) * 10_000
    mae = (min(bar.low for bar in held) / entry - 1) * 10_000
    prior_lows = [bar.low for bar in held[:mfe_at]]
    return {
        "mfe_bps": mfe,
        "mae_bps": mae,
        "pre_mfe_completed_bar_adverse_bps": (min(prior_lows) / entry - 1) * 10_000 if prior_lows else None,
        "pre_exit_adverse_bps": mae,
        "mfe_after_cost_bps": mfe - cost_bps,
        "mfe_bar_offset": mfe_at,
    }


def row_metrics(rows: list[dict], cost: float = 20) -> dict:
    if not rows:
        return {"n": 0}
    gross = [r["gross_bps"] for r in rows]
    net = [x - cost for x in gross]
    btc = [r["btc_gross_bps"] - cost for r in rows]
    excess = [r["excess_bps"] for r in rows]
    winners = sum(x for x in net if x > 0)
    losers = -sum(x for x in net if x < 0)
    compound, dd = drawdown(net)
    weeks = {r["week"] for r in rows}
    return {
        "n": len(rows), "weeks": len(weeks), "symbols": len({r["symbol"] for r in rows}),
        "gross_expectancy_bps": mean(gross), "net_expectancy_bps": mean(net),
        "matched_btc_net_bps": mean(btc), "excess_vs_btc_bps": mean(excess),
        "win_rate": sum(x > 0 for x in net) / len(net), "median_net_bps": median(net),
        "profit_factor": winners / losers if losers else None,
        "compounded_sequential_trade_return_pct": compound,
        "max_sequential_trade_drawdown_pct": dd,
        "worst_net_bps": min(net), "best_net_bps": max(net),
        "mean_mfe_bps": mean(r["mfe_bps"] for r in rows),
        "mean_mae_bps": mean(r["mae_bps"] for r in rows),
        "median_mfe_bps": median(r["mfe_bps"] for r in rows),
        "median_mae_bps": median(r["mae_bps"] for r in rows),
        "correct_direction_frequency": sum(x > 0 for x in gross) / len(gross),
        "pre_mfe_completed_bar_adverse_bps": summarize([r["pre_mfe_completed_bar_adverse_bps"] for r in rows
                                                          if r["pre_mfe_completed_bar_adverse_bps"] is not None]),
        "pre_exit_adverse_bps": summarize([r["pre_exit_adverse_bps"] for r in rows]),
        "mean_mfe_after_20bps_cost_bps": mean(r["mfe_bps"] - 20 for r in rows),
        "cost_stress_mean_net_bps": {str(c): mean(x - c for x in gross) for c in COSTS},
    }


def clustered(rows: list[dict]) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[row["week"]].append(row)
    weeks = sorted(groups)
    weekly = {w: mean(r["excess_bps"] for r in groups[w]) for w in weeks}
    rng = random.Random(SEED)
    draws = []
    for _ in range(BOOTSTRAPS):
        sample = [groups[weeks[rng.randrange(len(weeks))]] for _ in weeks]
        values = [r["excess_bps"] for block in sample for r in block]
        draws.append(mean(values))
    draws.sort()
    leave_week = [mean(r["excess_bps"] for r in rows if r["week"] != w) for w in weeks]
    symbols = sorted({r["symbol"] for r in rows})
    return {
        "weekly_cluster_means_bps": weekly,
        "positive_week_fraction": sum(v > 0 for v in weekly.values()) / len(weekly),
        "cluster_bootstrap_98pct_bps": [draws[20], draws[1979]],
        "bonferroni_three_candidate_98_33pct_descriptive_bps": [draws[16], draws[1983]],
        "bootstrap_seed": SEED, "bootstrap_replicates": BOOTSTRAPS,
        "leave_one_week_out_excess_range_bps": [min(leave_week), max(leave_week)],
        "leave_one_symbol_out_excess_bps": {s: mean(r["excess_bps"] for r in rows if r["symbol"] != s)
                                                 for s in symbols},
    }


def beta_sensitivity(rows: list[dict]) -> dict:
    x = [r["btc_gross_bps"] for r in rows]
    y = [r["gross_bps"] for r in rows]
    mx, my = mean(x), mean(y)
    variance = sum((v - mx) ** 2 for v in x)
    beta = sum((a - mx) * (b - my) for a, b in zip(x, y)) / variance if variance else None
    return {"full_sample_beta": beta,
            "beta_adjusted_net_intercept_bps": my - beta * mx - 20 if beta is not None else None,
            "note": "Full-sample descriptive linear adjustment; beta is estimated on inspected development outcomes."}


def by_field(rows: list[dict], key: str) -> dict:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(row)
    return {str(k): row_metrics(v) for k, v in sorted(grouped.items())}


def concentration(rows: list[dict], key: str) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    positive = [max(0, sum(r["gross_bps"] - 20 for r in group)) for group in groups.values()]
    return {
        "largest_group_trade_fraction": max(map(len, groups.values())) / len(rows),
        "largest_group_share_of_positive_group_net_pnl": max(positive) / sum(positive) if sum(positive) else None,
    }


def btc_regime(bars: list[Bar], entry: int) -> tuple[str, str]:
    if entry < 31:
        return "insufficient_prior_bars", "insufficient_prior_bars"
    trailing_return = bars[entry - 1].close / bars[entry - 31].close - 1
    direction = "bull" if trailing_return > 0.10 else "bear" if trailing_return < -0.10 else "sideways"
    returns = [math.log(bars[j].close / bars[j - 1].close) for j in range(entry - 29, entry)]
    volatility = "high_vol" if stdev(returns) >= 0.025 else "low_vol"
    return direction, volatility


def shifted_control(rows: list[dict], frames: dict[str, list[Bar]], offset: int, hold: int) -> dict:
    values = []
    excess = []
    indices = {s: {iso(b.timestamp): i for i, b in enumerate(bars)} for s, bars in frames.items()}
    for row in rows:
        i = indices[row["symbol"]][row["entry_time"]] + offset
        j = i + hold
        if j >= len(frames[row["symbol"]]):
            continue
        alt = frames[row["symbol"]]
        btc = frames["BTC_USDT"]
        a = (alt[j].open / alt[i].open - 1) * 10_000
        b = (btc[j].open / btc[i].open - 1) * 10_000
        values.append(a - 20)
        excess.append(a - b)
    return {"n": len(values), "mean_net_bps": mean(values), "mean_excess_vs_btc_bps": mean(excess),
            "offset_bars": offset}


def week_block_placebo(rows: list[dict], frames: dict[str, list[Bar]], hold: int) -> dict:
    """Reassign entries to a uniform valid 8h opening within each signal's ISO week."""
    rng = random.Random(SEED)
    week_indices = defaultdict(list)
    for symbol in ("ETH_USDT", "SOL_USDT", "LINK_USDT"):
        bars = frames[symbol]
        for i in range(len(bars) - hold):
            week_indices[(symbol, week_key(iso(bars[i].timestamp)))].append(i)
    draws = []
    for _ in range(500):
        values = []
        for row in rows:
            options = week_indices[(row["symbol"], week_key(row["entry_time"]))]
            if not options:
                continue
            i = options[rng.randrange(len(options))]
            j = i + hold
            alt = frames[row["symbol"]]
            btc = frames["BTC_USDT"]
            values.append((alt[j].open / alt[i].open - btc[j].open / btc[i].open) * 10_000)
        draws.append(mean(values))
    draws.sort()
    observed = mean(r["excess_bps"] for r in rows)
    return {"replicates": 500, "seed": SEED, "mean_placebo_excess_bps": mean(draws),
            "placebo_95pct_range_bps": [draws[12], draws[487]],
            "fraction_placebo_at_least_observed": sum(d >= observed for d in draws) / len(draws),
            "note": "Descriptive same-week timing control; no overlap or matched-state preservation."}


def variant(spec: dict, experiment: dict, frames: dict[str, list[Bar]]) -> dict:
    rows = []
    count = skipped = 0
    for symbol in spec["symbols"]:
        bars = frames[symbol]
        btc = frames["BTC_USDT"]
        next_allowed = 0
        for i in range(experiment["lookback_bars"], len(bars)):
            if not is_signal(bars, i, experiment):
                continue
            count += 1
            entry = i + 1
            if entry < next_allowed:
                skipped += 1
                continue
            exit_i = entry + experiment["hold_bars"]
            next_allowed = exit_i
            if exit_i >= len(bars):
                continue
            gross = (bars[exit_i].open / bars[entry].open - 1) * 10_000
            btc_gross = (btc[exit_i].open / btc[entry].open - 1) * 10_000
            rows.append({"symbol": symbol, "week": week_key(iso(bars[exit_i].timestamp)),
                         "gross_bps": gross, "excess_bps": gross - btc_gross})
    return {"signals": count, "overlap_skipped": skipped, "completed": len(rows),
            "weeks": len({r["week"] for r in rows}), "mean_net_20bps": mean(r["gross_bps"] - 20 for r in rows),
            "mean_net_40bps": mean(r["gross_bps"] - 40 for r in rows),
            "mean_excess_vs_btc_bps": mean(r["excess_bps"] for r in rows)}


def analyze(spec: dict, exact: dict, data_dir: Path) -> dict:
    if exact["specification_sha256"] != hashlib.sha256(
            json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest():
        raise ValueError("exact v1 report does not match unchanged draft config")
    frames = {s: read_bars(data_dir / f"{s}.csv", 480, utc(exact["as_of_utc"]))
              for s in [spec["benchmark_symbol"], *spec["symbols"]]}
    for symbol in frames:
        if sha256_file(data_dir / f"{symbol}.csv") != exact["source_sha256"][symbol]:
            raise ValueError(f"{symbol}: exact v1 source SHA256 mismatch")
    index = {s: {iso(b.timestamp): i for i, b in enumerate(bars)} for s, bars in frames.items()}
    results = []
    neighborhoods = {
        "volume_impulse": ("volume_multiple", [1.5, 2.0, 2.5]),
        "failed_downside_break": ("min_close_location", [0.6, 0.7, 0.8]),
        "rolling_vwap_reversion": ("min_displacement_bps", [50, 70, 90]),
    }
    for experiment, exact_result in zip(spec["experiments"], exact["experiments"]):
        if experiment["id"] != exact_result["experiment_id"]:
            raise ValueError("experiment order/ID mismatch")
        rows = []
        for event in exact_result["events"]:
            if event["status"] != "completed":
                continue
            symbol = event["symbol"]
            start = index[symbol][event["entry_time"]]
            stop = index[symbol][event["exit_time"]]
            path = path_metrics(frames[symbol], start, stop, event["entry_open"], 20)
            dt = utc(event["entry_time"])
            hour = dt.hour
            regime, volatility = btc_regime(frames["BTC_USDT"], start)
            row = {"symbol": symbol, "entry_time": event["entry_time"], "week": week_key(event["exit_time"]),
                   "year": dt.year, "month": dt.strftime("%Y-%m"), "entry_utc_hour": hour,
                   "btc_trailing_regime": regime, "btc_trailing_volatility": volatility,
                   "utc_session_proxy": {0: "Asia", 8: "London", 16: "New_York"}[hour],
                   "gross_bps": event["gross_bps"],
                   "btc_gross_bps": event["btc_matched_net_bps"] + 20,
                   "excess_bps": event["excess_vs_btc_bps"], **path}
            rows.append(row)
        rows.sort(key=lambda r: (r["entry_time"], r["symbol"]))
        key, values = neighborhoods[experiment["family"]]
        cells = []
        for value in values:
            e = copy.deepcopy(experiment)
            e["parameters"][key] = value
            cells.append({"parameter": key, "value": value, "baseline": value == experiment["parameters"][key],
                          **variant(spec, e, frames)})
        baseline = next(cell for cell in cells if cell["baseline"])
        if (baseline["signals"] != exact_result["signals_count"]
                or baseline["completed"] != exact_result["summary"]["completed"]
                or not math.isclose(baseline["mean_net_20bps"], exact_result["summary"]["mean_net_bps"], abs_tol=1e-9)):
            raise ValueError(f"{experiment['id']}: independent baseline re-evaluation differs from exact v1")
        signal_hours = defaultdict(int)
        for symbol in spec["symbols"]:
            bars = frames[symbol]
            for i in range(experiment["lookback_bars"], len(bars)):
                if is_signal(bars, i, experiment):
                    signal_hours[bars[i + 1].timestamp.hour if i + 1 < len(bars) else (bars[i].timestamp.hour + 8) % 24] += 1
        if sum(signal_hours.values()) != exact_result["signals_count"]:
            raise ValueError("signal hour distribution differs from exact v1 signal count")
        results.append({"experiment_id": experiment["id"], "exact_v1": True,
                        "signals": exact_result["signals_count"], "overlap_skipped": exact_result["overlap_skipped"],
                        "pending": exact_result["summary"]["pending"], "metrics": row_metrics(rows),
                        "equal_symbol_sleeve_portfolio": portfolio_equity(exact_result["events"], frames, spec["symbols"]),
                        "cluster": clustered(rows), "beta_sensitivity": beta_sensitivity(rows),
                        "by_symbol": by_field(rows, "symbol"), "by_year": by_field(rows, "year"),
                        "by_month": by_field(rows, "month"), "by_entry_hour": by_field(rows, "entry_utc_hour"),
                        "by_btc_trailing_regime": by_field(rows, "btc_trailing_regime"),
                        "by_btc_trailing_volatility": by_field(rows, "btc_trailing_volatility"),
                        "regime_note": "BTC prior 30-bar close change: bull >10%, bear <-10%, otherwise sideways; prior 30 8h log-return sample stdev high >=2.5%. Fixed descriptive bins, no signal filtering.",
                        "by_session_proxy": by_field(rows, "utc_session_proxy"),
                        "all_signal_utc_hour_counts_including_skipped": dict(sorted(signal_hours.items())),
                        "session_note": "8h UTC entries occur at 00/08/16 only; region names are coarse proxies; overlaps unidentifiable.",
                        "month_concentration": concentration(rows, "month"),
                        "week_concentration": concentration(rows, "week"),
                        "negative_controls": {
                            "shift_plus_7_bars": shifted_control(rows, frames, 7, experiment["hold_bars"]),
                            "same_week_random_entry": week_block_placebo(rows, frames, experiment["hold_bars"]),
                            "matched_btc_net_bps": row_metrics(rows)["matched_btc_net_bps"],
                        },
                        "neighborhood_one_parameter_at_a_time": cells})
    return {"status": "DEVELOPMENT_SPENT_DATA", "source_sha256": exact["source_sha256"],
            "specification_sha256": exact["specification_sha256"], "bootstrap_seed": SEED,
            "trial_accounting": {"original_inspected_public_hypotheses": 7, "exact_v1_trading_candidates": 3,
                                 "development_neighborhood_cells_including_baselines": 9,
                                 "distinct_additional_cells": 6, "selection_permitted": False},
            "multiplicity_note": "Bonferroni three-candidate 98.33% week-cluster bootstrap intervals are descriptive only; nine inspected development cells and original 25-source survey are disclosed, so no calibrated discovery p-value or formal pass is claimed.",
            "path_limitation": "OHLC highs/lows give excursion bounds, not intrabar order or executable fills; pre-MFE adverse uses strictly earlier completed bars only.",
            "compounding_limitation": "Sequential per-trade compounding is an event-series diagnostic; simultaneous coin positions are serialized, so it is not a portfolio equity curve.",
            "results": results, "verified_out_of_sample_evidence": False, "deployment_eligible": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--exact-report", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.config.read_text(encoding="utf-8"))
    exact = json.loads(args.exact_report.read_text(encoding="utf-8"))
    result = analyze(spec, exact, args.data_dir)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({r["experiment_id"]: r["metrics"] for r in result["results"]}, sort_keys=True))


if __name__ == "__main__":
    main()
