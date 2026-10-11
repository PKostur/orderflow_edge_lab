"""Offline PSR8 adapted bot screen; no network, orders, retuning or promotion."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import random
from statistics import mean, median

from .public_strategy_shadow import Bar, iso, read_bars, sha256_file, utc
from .public_strategy_development import btc_regime, path_metrics, beta_sensitivity
from .public_strategy_completion import clock_counts

DESIGN_COMMIT = "063e170590f117e1e771b8ecb9581aef3e69737e"
DESIGN_SHA256 = "b00df9754dc72baf41023f752621accbb3c318774497033cdba5460c4e37cee6"
CANDIDATES = ("ASDTSRockwellTrading", "AwesomeMacd", "CofiBitStrategy")
EXTENSION_CANDIDATES = ("RSI2", "CCICorrectionStrategy")
EXTENSION_DESIGN_COMMIT = "177dfca25d47bac5e07b958f632496336d01433a"
EXTENSION_DESIGN_SHA256 = "a9bf180aaf8cbd7d053bdf49b9cd9b9a805bb23237cef239926091c8dfdfcf4a"
RISK_DESIGN_COMMIT = "3e96f735717c3ea847ee4051f228342555a0c518"
RISK_DESIGN_SHA256 = "de9cbbd32b1f142cf2f988cd9e2d1ea6ae6c269b37963a5b85aca204f68c76a2"


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sma(values: list[float | None], period: int) -> list[float | None]:
    result: list[float | None] = []
    for i in range(len(values)):
        window = values[max(0, i - period + 1):i + 1]
        result.append(mean(window) if len(window) == period and all(x is not None for x in window) else None)
    return result


def smooth(values: list[float | None], period: int, *, wilder: bool = False) -> list[float | None]:
    result: list[float | None] = []
    state = None
    alpha = 1 / period if wilder else 2 / (period + 1)
    for i, value in enumerate(values):
        if value is None:
            state = None
        elif state is None:
            window = values[max(0, i - period + 1):i + 1]
            if len(window) == period and all(x is not None for x in window):
                state = mean(window)
        else:
            state += alpha * (value - state)
        result.append(state)
    return result


def indicators(bars: list[Bar]) -> dict[str, list]:
    closes = [b.close for b in bars]
    fast, slow = smooth(closes, 12), smooth(closes, 26)
    macd = [a - b if a is not None and b is not None else None for a, b in zip(fast, slow)]
    mids = [(b.high + b.low) / 2 for b in bars]
    ao = [a - b if a is not None and b is not None else None for a, b in zip(sma(mids, 5), sma(mids, 34))]
    k = []
    tr, plus, minus = [None], [None], [None]
    for i, bar in enumerate(bars):
        if i < 4:
            k.append(None)
        else:
            low = min(b.low for b in bars[i - 4:i + 1])
            high = max(b.high for b in bars[i - 4:i + 1])
            k.append(100 * (bar.close - low) / (high - low) if high > low else 0.0)
        if i:
            prior = bars[i - 1]
            up, down = bar.high - prior.high, prior.low - bar.low
            tr.append(max(bar.high - bar.low, abs(bar.high - prior.close), abs(bar.low - prior.close)))
            plus.append(up if up > down and up > 0 else 0.0)
            minus.append(down if down > up and down > 0 else 0.0)
    tr_s, p_s, m_s = (smooth(x, 14, wilder=True) for x in (tr, plus, minus))
    dx = []
    for t, p, m in zip(tr_s, p_s, m_s):
        if t is None:
            dx.append(None)
        else:
            dx.append(100 * abs(p - m) / (p + m) if p + m else 0.0)
    return {"macd": macd, "signal": smooth(macd, 9), "ao": ao, "k": k, "d": sma(k, 3),
            "adx": smooth(dx, 14, wilder=True), "ema_low": smooth([b.low for b in bars], 5),
            "ema_high": smooth([b.high for b in bars], 5)}


def extension_indicators(bars: list[Bar]) -> dict[str, list]:
    closes = [b.close for b in bars]
    gains = [None] + [max(0, b - a) for a, b in zip(closes, closes[1:])]
    losses = [None] + [max(0, a - b) for a, b in zip(closes, closes[1:])]
    g, l = smooth(gains, 2, wilder=True), smooth(losses, 2, wilder=True)
    rsi = [None if a is None else (100 * a / (a + b) if a + b else 0.0) for a, b in zip(g, l)]
    typical = [(b.high + b.low + b.close) / 3 for b in bars]
    output = {"sma200": sma(closes, 200), "sma5": sma(closes, 5), "rsi2": rsi}
    for period in (5, 200):
        values = []
        for i, value in enumerate(typical):
            window = typical[max(0, i - period + 1):i + 1]
            if len(window) < period:
                values.append(None)
            else:
                avg = mean(window)
                deviation = mean(abs(x - avg) for x in window)
                values.append((value - avg) / (.015 * deviation) if deviation else 0.0)
        output[f"cci{period}"] = values
    return output


def chandelier_indicators(bars: list[Bar]) -> dict[str, list]:
    tr = [b.high - b.low if i == 0 else max(b.high - b.low, abs(b.high - bars[i - 1].close),
                                         abs(b.low - bars[i - 1].close)) for i, b in enumerate(bars)]
    atr = smooth(tr, 22, wilder=True)
    longs, shorts, direction = [], [], []
    state = 1
    for i, bar in enumerate(bars):
        if atr[i] is None:
            longs.append(None)
            shorts.append(None)
            direction.append(state)
            continue
        window = bars[i - 21:i + 1]
        long = max(b.close for b in window) - 3 * atr[i]
        short = min(b.close for b in window) + 3 * atr[i]
        prior_long = longs[i - 1] if i and longs[i - 1] is not None else long
        prior_short = shorts[i - 1] if i and shorts[i - 1] is not None else short
        if i and bars[i - 1].close > prior_long:
            long = max(long, prior_long)
        if i and bars[i - 1].close < prior_short:
            short = min(short, prior_short)
        state = 1 if bar.close > prior_short else -1 if bar.close < prior_long else state
        longs.append(long)
        shorts.append(short)
        direction.append(state)
    return {"atr": atr, "long_band": longs, "short_band": shorts, "direction": direction}


def chandelier_risk(bar: Bar, entry_open: float, prior_peak_pct: float) -> tuple[bool, float]:
    high_gain = (bar.high / entry_open - 1) * 100
    close_gain = (bar.close / entry_open - 1) * 100
    trigger = (close_gain < -5 or high_gain > 20 or
               (prior_peak_pct > 10 and prior_peak_pct - high_gain > 5))
    return trigger, max(prior_peak_pct, high_gain)


def rules(name: str, bars: list[Bar], features: dict[str, list], i: int) -> tuple[bool, bool]:
    if name not in (*CANDIDATES, *EXTENSION_CANDIDATES, "ChandelierExit"):
        raise ValueError("unregistered candidate")
    if i < 1 or any(v[i] is None or v[i - 1] is None for v in features.values()):
        return False, False
    f = {k: v[i] for k, v in features.items()}
    p = {k: v[i - 1] for k, v in features.items()}
    if name == "ChandelierExit":
        return f["direction"] == 1 and p["direction"] == -1, f["direction"] == -1 and p["direction"] == 1
    if name == "RSI2":
        return bars[i].close > f["sma200"] and f["rsi2"] <= 10, bars[i].close > f["sma5"]
    if name == "CCICorrectionStrategy":
        return f["cci200"] > 100 and f["cci5"] < -100, f["cci200"] < -100 and f["cci5"] > 100
    if name == "ASDTSRockwellTrading":
        return f["macd"] > 0 and f["macd"] > f["signal"], f["macd"] < f["signal"]
    if name == "AwesomeMacd":
        return f["macd"] > 0 and f["ao"] > 0 and p["ao"] < 0, f["macd"] < 0 and f["ao"] < 0 and p["ao"] > 0
    cross = f["k"] > f["d"] and p["k"] <= p["d"]
    entry = bars[i].open < f["ema_low"] and cross and f["k"] < 25 and f["d"] < 25 and f["adx"] > 25
    exit_signal = (bars[i].open >= f["ema_high"] or (f["k"] > 75 and p["k"] <= 75)
                   or (f["d"] > 75 and p["d"] <= 75))
    return entry, exit_signal


def execute(name: str, symbol: str, bars: list[Bar], btc: list[Bar], features: dict[str, list],
            spec: dict) -> dict:
    rows, signals, skipped = [], [], 0
    position = None
    prior_peak = 0.0
    for i in range(spec["warmup_bars"], len(bars)):
        enter, leave = rules(name, bars, features, i)
        if enter:
            signals.append(iso(bars[i].timestamp))
        if position is not None:
            risk = False
            if name == "ChandelierExit":
                risk, prior_peak = chandelier_risk(bars[i], bars[position].open, prior_peak)
                leave = leave or risk
            if enter:
                skipped += 1
            if (leave or i + 1 - position >= spec["max_hold_bars"]) and i + 1 < len(bars):
                j = i + 1
                gross = (bars[j].open / bars[position].open - 1) * 10000
                benchmark = (btc[j].open / btc[position].open - 1) * 10000
                stamp = bars[position].timestamp
                regime, volatility = btc_regime(btc, position)
                rows.append({"symbol": symbol, "entry_index": position, "exit_index": j,
                             "entry_time": iso(stamp), "exit_time": iso(bars[j].timestamp),
                             "origin_open_time": iso(bars[position - 1].timestamp),
                             "gross_bps": gross, "btc_gross_bps": benchmark, "excess_bps": gross - benchmark,
                             "hold_bars": j - position, "week": week(stamp), "year": stamp.year,
                             "month": stamp.strftime("%Y-%m"), "hour": stamp.hour,
                             "btc_regime": regime, "btc_volatility": volatility,
                             "exit_reason": "published_completed_bar_risk" if risk else "indicator" if leave else "administrative_timeout",
                             **path_metrics(bars, position, j, bars[position].open, spec["baseline_round_trip_bps"])})
                position = None
                prior_peak = 0.0
        elif enter:
            # Entry on final closed candle is pending next-open, not an invented fill.
            position = i + 1
            prior_peak = 0.0
    pending = None if position is None else {"symbol": symbol, "entry_index": position,
        "status": "open_position" if position < len(bars) else "awaiting_next_open"}
    return {"rows": rows, "signal_origin_times": signals, "overlap_skipped": skipped, "pending": pending}


def week(stamp) -> str:
    year, number, _ = stamp.isocalendar()
    return f"{year}-W{number:02d}"


def metrics(rows: list[dict], cost: float) -> dict:
    if not rows:
        return {"n": 0, "mean_net_bps": None}
    net = [r["gross_bps"] - cost for r in rows]
    loss = -sum(x for x in net if x < 0)
    return {"n": len(rows), "weeks": len({r["week"] for r in rows}), "gross_bps": mean(r["gross_bps"] for r in rows),
            "mean_net_bps": mean(net), "median_net_bps": median(net), "win_rate": mean(x > 0 for x in net),
            "profit_factor": sum(x for x in net if x > 0) / loss if loss else None,
            "btc_net_bps": mean(r["btc_gross_bps"] - cost for r in rows),
            "excess_bps": mean(r["excess_bps"] for r in rows),
            "mean_mfe_bps": mean(r["mfe_bps"] for r in rows), "mean_mae_bps": mean(r["mae_bps"] for r in rows),
            "median_mfe_bps": median(r["mfe_bps"] for r in rows), "median_mae_bps": median(r["mae_bps"] for r in rows),
            "worst_net_bps": min(net), "best_net_bps": max(net)}


def grouped(rows: list[dict], field: str, cost: float) -> dict:
    return {str(k): metrics([r for r in rows if r[field] == k], cost) for k in sorted({r[field] for r in rows})}


def intervals(rows: list[dict], frames: dict, spec: dict) -> dict:
    if not rows:
        return {"net_bps": [None, None], "excess_bps": [None, None]}
    first = frames[spec["symbols"][0]][spec["warmup_bars"]].timestamp
    first -= timedelta(days=first.weekday(), hours=first.hour)
    last = frames[spec["symbols"][0]][-1].timestamp
    weeks = []
    while first <= last:
        weeks.append(week(first))
        first += timedelta(days=7)
    groups = defaultdict(list)
    for r in rows:
        groups[r["week"]].append(r)
    blocks = [weeks[i:i + 4] for i in range(len(weeks) - 3)]
    rng, draws_net, draws_excess = random.Random(spec["seed"]), [], []
    for _ in range(spec["bootstrap_replicates"]):
        chosen = []
        while len(chosen) < len(weeks):
            chosen.extend(rng.choice(blocks))
        sample = [r for w in chosen[:len(weeks)] for r in groups[w]]
        if sample:
            draws_net.append(mean(r["gross_bps"] for r in sample) - spec["baseline_round_trip_bps"])
            draws_excess.append(mean(r["excess_bps"] for r in sample))
    alpha = spec["familywise_alpha"] / len(spec["candidates"])
    def bounds(values):
        values.sort()
        return [values[int(len(values) * alpha / 2)], values[min(len(values) - 1, int(len(values) * (1 - alpha / 2)))]]
    return {"net_bps": bounds(draws_net), "excess_bps": bounds(draws_excess), "replicates": len(draws_net),
            "calendar_weeks_including_empty": len(weeks), "block_weeks": 4,
            "descriptive_interval_pct": 100 * (1 - alpha),
            "note": "Descriptive batch-width interval; not full-search corrected or untouched confirmation"}


def controls(rows: list[dict], frames: dict, spec: dict) -> dict:
    if not rows:
        return {"shifted": {"n": 0}, "placebo_fraction_at_least_observed": None}
    cost = spec["baseline_round_trip_bps"]
    def returns(row, i):
        j, alt, btc = i + row["hold_bars"], frames[row["symbol"]], frames[spec["benchmark"]]
        a = (alt[j].open / alt[i].open - 1) * 10000
        b = (btc[j].open / btc[i].open - 1) * 10000
        return a - cost, a - b
    shifted = [returns(r, r["entry_index"] + 7) for r in rows
               if r["exit_index"] + 7 < len(frames[r["symbol"]])]
    # Pre-index available starts by symbol, week and observed duration, including only full windows.
    options = {}
    for r in rows:
        key = (r["symbol"], r["week"], r["hold_bars"])
        if key not in options:
            options[key] = [i for i, b in enumerate(frames[r["symbol"]][:-r["hold_bars"]]) if week(b.timestamp) == r["week"]]
    rng, placebo = random.Random(spec["seed"]), []
    for _ in range(spec["placebo_replicates"]):
        placebo.append(mean(returns(r, rng.choice(options[(r["symbol"], r["week"], r["hold_bars"])]))[1] for r in rows))
    observed = mean(r["excess_bps"] for r in rows)
    return {"shifted": {"n": len(shifted), "net_bps": mean(x[0] for x in shifted) if shifted else None,
                        "excess_bps": mean(x[1] for x in shifted) if shifted else None, "offset_bars": 7},
            "placebo_fraction_at_least_observed": mean(x >= observed for x in placebo),
            "placebo_mean_excess_bps": mean(placebo), "placebo_replicates": len(placebo),
            "note": "Same-entry-week/symbol and observed-duration timing control permits overlap; no state counterfactual"}


def portfolio(rows: list[dict], pending: list[dict], frames: dict, spec: dict, cost: float) -> dict:
    balances = {s: 1.0 for s in spec["symbols"]}
    starts, ends = defaultdict(set), defaultdict(set)
    for r in rows:
        starts[r["entry_index"]].add(r["symbol"])
        ends[r["exit_index"]].add(r["symbol"])
    for p in pending:
        if p["status"] == "open_position":
            starts[p["entry_index"]].add(p["symbol"])
    active, curve = set(), [1.0]
    n = len(frames[spec["symbols"][0]])
    half_cost = cost / 20000
    for i in range(n):
        for s in ends[i]:
            active.remove(s)
            balances[s] *= 1 - half_cost
        for s in starts[i]:
            if s in active:
                raise ValueError("overlapping position")
            active.add(s)
            balances[s] *= 1 - half_cost
        curve.append(mean(balances.values()))
        for s in active:
            bars = frames[s]
            balances[s] *= bars[i + 1].open / bars[i].open if i + 1 < n else bars[i].close / bars[i].open
    curve.append(mean(balances.values()))
    peak, dd = 1.0, 0.0
    for equity in curve:
        peak = max(peak, equity)
        dd = min(dd, equity / peak - 1)
    return {"return_pct": (curve[-1] - 1) * 100, "max_drawdown_pct": dd * 100,
            "pending_marked_symbols": sorted(active), "cost_round_trip_bps": cost,
            "note": "Equal initial cash sleeves, internally reinvested; pending positions marked final close without fictitious exit. Costs applied multiplicatively; event means subtract bps."}


def build(spec: dict, root: Path) -> dict:
    # Compare with the pre-outcome design, refusing silently changed trials.
    expected = {"PSR8-PUBLIC-BOT-BATCH2": (DESIGN_SHA256, DESIGN_COMMIT),
                "PSR9-PUBLIC-BOT-BATCH3": (EXTENSION_DESIGN_SHA256, EXTENSION_DESIGN_COMMIT),
                "PSR10-PUBLIC-BOT-BATCH4": (RISK_DESIGN_SHA256, RISK_DESIGN_COMMIT)}
    if spec.get("study_id") not in expected or digest(spec) != expected[spec["study_id"]][0]:
        raise ValueError("config differs from immutable pre-outcome design")
    source = json.loads((root / spec["data_manifest"]).read_text(encoding="utf-8"))
    names = [spec["benchmark"], *spec["symbols"]]
    files = {s: root / spec["development_data"] / f"{s}.csv" for s in names}
    hashes = {s: sha256_file(p) for s, p in files.items()}
    if any(hashes[s] != source["symbols"][s.replace("_", "")]["aligned_csv_sha256"] for s in names):
        raise ValueError("source manifest hash mismatch")
    frames = {s: read_bars(p, spec["bar_minutes"], utc(spec["as_of"])) for s, p in files.items()}
    clocks = [b.timestamp for b in frames[names[0]]]
    if any([b.timestamp for b in frames[s]] != clocks for s in names):
        raise ValueError("unaligned source clocks")
    indicator_function = {"PSR8-PUBLIC-BOT-BATCH2": indicators, "PSR9-PUBLIC-BOT-BATCH3": extension_indicators,
                          "PSR10-PUBLIC-BOT-BATCH4": chandelier_indicators}[spec["study_id"]]
    features = {s: indicator_function(frames[s]) for s in spec["symbols"]}
    results, all_keys = [], {}
    for name in spec["candidates"]:
        executions = [execute(name, s, frames[s], frames[spec["benchmark"]], features[s], spec) for s in spec["symbols"]]
        rows = sorted([r for e in executions for r in e["rows"]], key=lambda r: (r["entry_time"], r["symbol"]))
        pending = [e["pending"] for e in executions if e["pending"] is not None]
        all_keys[name] = {(s, t) for s, e in zip(spec["symbols"], executions) for t in e["signal_origin_times"]}
        cost = spec["baseline_round_trip_bps"]
        summary = metrics(rows, cost)
        ci, control = intervals(rows, frames, spec), controls(rows, frames, spec)
        symbols, years = grouped(rows, "symbol", cost), grouped(rows, "year", cost)
        week_means = grouped(rows, "week", cost)
        leave_week = [mean(r["gross_bps"] - cost for r in rows if r["week"] != w) for w in week_means
                      if any(r["week"] != w for r in rows)]
        curve = portfolio(rows, pending, frames, spec, cost)
        gate = {
            "completed_count": len(rows) >= spec["min_trades"],
            "entry_weeks": len(week_means) >= spec["min_weeks"],
            "net40_hurdle": bool(rows) and summary["mean_net_bps"] > spec["min_net_expectancy_bps"],
            "net80_positive": bool(rows) and metrics(rows, 80)["mean_net_bps"] > 0,
            "all_symbols_positive": len(symbols) == len(spec["symbols"]) and all(m["mean_net_bps"] > 0 for m in symbols.values()),
            "positive_year_fraction": bool(years) and mean(m["mean_net_bps"] > 0 for m in years.values()) >= spec["min_positive_year_fraction"],
            "leave_week_positive": bool(leave_week) and min(leave_week) > 0,
            "portfolio_drawdown": abs(curve["max_drawdown_pct"]) < spec["max_portfolio_drawdown_pct"],
            "net_interval_positive": ci["net_bps"][0] is not None and ci["net_bps"][0] > 0,
            "excess_interval_positive": ci["excess_bps"][0] is not None and ci["excess_bps"][0] > 0,
            "placebo_tail": control["placebo_fraction_at_least_observed"] is not None and control["placebo_fraction_at_least_observed"] <= spec["max_placebo_at_least_observed_fraction"],
        }
        origins = [utc(t) for e in executions for t in e["signal_origin_times"]]
        result = {"candidate": name, "metrics40": summary, "costs": {str(c): metrics(rows, c) for c in spec["cost_cases_bps"]},
                  "signals": sum(len(e["signal_origin_times"]) for e in executions),
                  "skipped": sum(e["overlap_skipped"] for e in executions), "pending": pending,
                  "portfolio": curve, "intervals": ci, "controls": control, "by_symbol": symbols, "by_year": years,
                  "by_month": grouped(rows, "month", cost), "by_hour": grouped(rows, "hour", cost),
                  "by_btc_regime": grouped(rows, "btc_regime", cost), "by_btc_volatility": grouped(rows, "btc_volatility", cost),
                  "positive_week_fraction": mean(v["mean_net_bps"] > 0 for v in week_means.values()) if week_means else None,
                  "leave_one_week_net_range": [min(leave_week), max(leave_week)] if leave_week else None,
                  "leave_one_symbol_net": {s: metrics([r for r in rows if r["symbol"] != s], cost) for s in spec["symbols"]},
                  "clock_origin": clock_counts(origins), "clock_completion": clock_counts([t + timedelta(hours=8) for t in origins]),
                  "clock_entry": clock_counts([utc(r["entry_time"]) for r in rows]), "gates": gate,
                  "decision": "HISTORICAL_SCREEN_SURVIVOR_NOT_VIABLE" if all(gate.values()) else "REJECTED_AS_ADAPTED",
                  "events": rows}
        if rows:
            beta = beta_sensitivity(rows)
            if beta["beta_adjusted_net_intercept_bps"] is not None:
                beta["beta_adjusted_net_intercept_bps"] -= cost - 20
            result["beta_sensitivity40"] = beta
            result["exit_reasons"] = dict(Counter(r["exit_reason"] for r in rows))
        if result["signals"] != len(rows) + result["skipped"] + len(pending):
            raise ValueError("signal/event accounting mismatch")
        results.append(result)
    overlaps = {}
    for a in spec["candidates"]:
        for b in spec["candidates"]:
            if a < b:
                union = all_keys[a] | all_keys[b]
                overlaps[f"{a}|{b}"] = {"intersection": len(all_keys[a] & all_keys[b]),
                                          "jaccard": len(all_keys[a] & all_keys[b]) / len(union) if union else None}
    return {"study": spec["study_id"], "design_commit": expected[spec["study_id"]][1], "config_sha256": digest(spec),
            "source_sha256": hashes, "first_open": iso(clocks[0]), "last_open": iso(clocks[-1]), "bars_per_symbol": len(clocks),
            "signal_overlap": overlaps, "results": results, "new_trading_cells": len(spec["candidates"]), "parameter_search_cells": 0,
            "upstream_exact_bot_replication": False, "untouched_oos": False, "viable_candidates": [], "authorizes_orders": False,
            "note": "Source-derived8h adaptations on spent historical data. No profitable/deployment claim. All candidate outcomes retained."}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/public_bot_batch2_v1.json"))
    args = parser.parse_args()
    spec = json.loads((args.root / args.config).read_text(encoding="utf-8"))
    result = build(spec, args.root)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps([{k: r[k] for k in ("candidate", "metrics40", "gates", "decision")} for r in result["results"]]))


if __name__ == "__main__":
    main()
