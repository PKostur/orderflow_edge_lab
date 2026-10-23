"""Fixed long/cash portfolio research. No credentials, exchange orders or tuning."""

import argparse
import csv
import gzip
import hashlib
import json
import math
import statistics
from datetime import datetime, timedelta
from pathlib import Path

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT")
LOOKBACKS = (90, 270, 1095)
INITIAL = 10000.0
STEP = timedelta(hours=8)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_panel(folder):
    """Refuse edits, gaps, bad OHLC and different calendars; no repairs."""
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    panel = {}
    calendar = None
    for symbol in SYMBOLS:
        meta = manifest["symbols"][symbol]
        path = folder / meta["aligned_csv"]
        if digest(path) != meta["aligned_csv_sha256"]:
            raise ValueError("aligned CSV hash mismatch: " + symbol)
        with path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        times = [datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) for r in rows]
        if not times or any(b - a != STEP for a, b in zip(times, times[1:])):
            raise ValueError("noncontinuous calendar")
        if calendar is not None and times != calendar:
            raise ValueError("unsynchronized symbols")
        calendar = times
        panel[symbol] = {k: [float(r[k]) for r in rows] for k in ("open", "high", "low", "close")}
        for o, h, low, c in zip(*(panel[symbol][k] for k in ("open", "high", "low", "close"))):
            if not all(math.isfinite(x) and x > 0 for x in (o, h, low, c)) or not low <= min(o, c) <= max(o, c) <= h:
                raise ValueError("invalid OHLC")
    if len(calendar) != manifest["common_bars"]:
        raise ValueError("manifest bar count mismatch")
    return calendar, panel, manifest


def weights(closes, end, mode="trend"):
    if mode not in ("trend", "always_long", "btc"):
        raise ValueError("unknown control")
    if end < max(LOOKBACKS):
        return {s: 0.0 for s in SYMBOLS}
    result = {}
    for s in SYMBOLS:
        c = closes[s]
        if mode == "btc":
            result[s] = float(s == "BTCUSDT")
            continue
        returns = [math.log(c[k] / c[k - 1]) for k in range(end - 179, end + 1)]
        vol = statistics.stdev(returns) * math.sqrt(1095)
        risk = min(1.0, 0.10 / vol) if vol > 0 else 1.0
        score = 1.0 if mode == "always_long" else max(0.0, sum((c[end] > c[end - n]) - (c[end] < c[end - n]) for n in LOOKBACKS) / 3)
        result[s] = 0.25 * score * risk
    return result


def rebalance(cash, holdings, desired, prices, rate):
    """Fractional float64 units; fsum and shared scaling avoid symbol-order bias."""
    if not 0 <= rate < 1 or cash < 0:
        raise ValueError("invalid wallet/cost")
    if any(not math.isfinite(x) or x < 0 for x in [cash, *holdings.values(), *desired.values()]):
        raise ValueError("invalid wallet")
    if any(not math.isfinite(p) or p <= 0 for p in prices.values()):
        raise ValueError("invalid price")
    held = dict(holdings)
    sales = {s: max(0.0, held[s] - desired[s]) for s in SYMBOLS}
    cash += math.fsum(sales[s] * prices[s] * (1 - rate) for s in SYMBOLS)
    fills = []
    for s in SYMBOLS:
        if sales[s] > 0:
            held[s] -= sales[s]
            fills.append({"symbol": s, "side": "sell", "quantity": sales[s], "price": prices[s], "cost": sales[s] * prices[s] * rate})
    needs = {s: max(0.0, desired[s] - held[s]) for s in SYMBOLS}
    total = math.fsum(needs[s] * prices[s] * (1 + rate) for s in SYMBOLS)
    # A tiny safety factor on cash-limited buys leaves a positive rounding reserve.
    scale = min(1.0, cash / total * (1 - 1e-14)) if total > cash else 1.0
    debits = []
    for s in SYMBOLS:
        q = needs[s] * scale
        if q > 0:
            held[s] += q
            debits.append(q * prices[s] * (1 + rate))
            fills.append({"symbol": s, "side": "buy", "quantity": q, "price": prices[s], "cost": q * prices[s] * rate})
    cash -= math.fsum(debits)
    if cash < 0:
        raise ArithmeticError("negative cash: no clipping or borrowing permitted")
    return cash, held, fills


def simulate(times, panel, rate, mode="trend"):
    closes = {s: panel[s]["close"] for s in SYMBOLS}
    eligible = [i for i, t in enumerate(times) if i >= 1097 and t.weekday() == 0 and t.hour == 8]
    if not eligible:
        raise ValueError("insufficient eligible history")
    start = eligible[0]
    cash, holdings = INITIAL, dict.fromkeys(SYMBOLS, 0.0)
    fills, marks = [], []
    peak, worst, low_bound = INITIAL, 0.0, 0.0
    year_start, year_end = {}, {}
    previous = INITIAL
    exposure = []
    for i in range(start, len(times)):
        t = times[i]
        if t.weekday() == 0 and t.hour == 8 and (mode != "btc" or i == start):
            j = i - 2
            w = weights(closes, j, mode)
            decision_nav = cash + math.fsum(holdings[s] * closes[s][j] for s in SYMBOLS)
            desired = {s: decision_nav * w[s] / closes[s][j] for s in SYMBOLS}
            if mode == "btc":
                # Descriptive full-cash buy/hold benchmark, not a tradable signal target.
                desired["BTCUSDT"] = cash / panel["BTCUSDT"]["open"][i]
            cash, holdings, trades = rebalance(cash, holdings, desired, {s: panel[s]["open"][i] for s in SYMBOLS}, rate)
            for trade in trades:
                fills.append({**trade, "fill_open_utc": t.isoformat(), "signal_close_utc": (times[j] + STEP).isoformat()})
        inventory = math.fsum(holdings[s] * closes[s][i] for s in SYMBOLS)
        nav = cash + inventory * (1 - rate)
        bar_low = cash + math.fsum(holdings[s] * panel[s]["low"][i] * (1 - rate) for s in SYMBOLS)
        low_bound = min(low_bound, bar_low / peak - 1)
        peak = max(peak, nav)
        worst = min(worst, nav / peak - 1)
        year = str(t.year)
        year_start.setdefault(year, previous)
        year_end[year] = nav
        previous = nav
        exposure.append(inventory / (cash + inventory))
        marks.append({"close_utc": (t + STEP).isoformat(), "net_liquidation_usdt": nav, "cash_usdt": cash, "holdings": dict(holdings)})
    years = {y: year_end[y] / year_start[y] - 1 for y in year_start}
    omitted = {y: math.prod(1 + r for other, r in years.items() if other != y) - 1 for y in years}
    duration = (times[-1] + STEP - times[start]).total_seconds() / (365.25 * 86400)
    final = marks[-1]["net_liquidation_usdt"]
    return {"mode": mode, "side_cost_bps": rate * 10000, "first_fill_open_utc": times[start].isoformat(),
            "end_exclusive_utc": (times[-1] + STEP).isoformat(), "initial_usdt": INITIAL,
            "final_net_liquidation_usdt": final, "net_profit_usdt": final - INITIAL,
            "net_return": final / INITIAL - 1, "cagr": (final / INITIAL) ** (1 / duration) - 1,
            "max_close_drawdown": worst, "same_bar_low_stress_bound": low_bound,
            "calendar_returns": years, "leave_one_year_out_compounded": omitted,
            "mean_gross_exposure": statistics.mean(exposure), "fill_count": len(fills),
            "rebalance_costs_usdt": math.fsum(f["cost"] for f in fills),
            "hypothetical_terminal_cost_usdt": inventory * rate, "fills": fills, "equity": marks}


def evaluate(folder):
    times, panel, manifest = load_panel(folder)
    cases = [simulate(times, panel, rate, mode) for rate in (0.002, 0.004) for mode in ("trend", "always_long", "btc")]
    trend = [r for r in cases if r["mode"] == "trend"]
    control = [r for r in cases if r["mode"] == "always_long"]
    gates = {"net_positive_both_costs": all(r["net_profit_usdt"] > 0 for r in trend),
             "close_drawdown_at_most_15pct": all(r["max_close_drawdown"] >= -0.15 for r in trend),
             "increment_over_matched_control_both_costs": all(a["net_return"] > b["net_return"] for a, b in zip(trend, control)),
             "all_leave_year_out_positive": all(all(v > 0 for v in r["leave_one_year_out_compounded"].values()) for r in trend)}
    return {"candidate": "CASH_TREND_PORTFOLIO_V1", "evidence": "SPENT_DEVELOPMENT_ONLY", "orders": False,
            "future_confirmation_started": False, "promotable": False,
            "decision": "HISTORICAL_SCREEN_SURVIVOR_ONLY" if all(gates.values()) else "REJECTED_AS_DEFINED",
            "gates": gates, "source_manifest_sha256": digest(Path(folder) / "manifest.json"),
            "source_manifest": manifest, "cases": cases, "cash_control_return": 0.0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("refusing to overwrite evidence")
    report = evaluate(args.data)
    report["evaluator_sha256"] = digest(__file__)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output, "wt", encoding="utf-8") as stream:
        json.dump(report, stream, allow_nan=False, separators=(",", ":"))
    print(json.dumps({k: v for k, v in report.items() if k not in ("cases", "source_manifest")}, indent=2))
    for case in report["cases"]:
        print(json.dumps({k: v for k, v in case.items() if k not in ("fills", "equity")}, indent=2))


if __name__ == "__main__":
    main()
