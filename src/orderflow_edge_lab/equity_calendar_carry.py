"""Funded equity calendar/Treasury feasibility; reads archived public data only."""
import argparse
import csv
import hashlib
import json
import math
import random
import subprocess
from bisect import bisect_left
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ASSETS = ("SPY", "SHV")


def cost(shares, price, multiplier=1):
    return (max(1.0, .005 * shares) + .00015 * shares * price) * multiplier if shares else 0.0


def quantity(cash, limit, multiplier=1):
    q = max(0, math.floor(cash / (limit * (1 + .00015 * multiplier) + .005 * multiplier)))
    while q and q * limit + cost(q, limit, multiplier) > cash:
        q -= 1
    return q


def load_data(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    for item in manifest["files"]:
        if hashlib.sha256((folder / item["name"]).read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("source hash mismatch " + item["name"])
    with (folder / "calendar.csv").open(newline="", encoding="utf-8") as stream:
        calendar = [r["session"][:10] for r in csv.DictReader(stream)]
    expected = [d for d in calendar if "2008-12-01" <= d < "2026-10-01"]
    frames, dividends = {}, {}
    for asset in ASSETS:
        with (folder / (asset + ".csv")).open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        if [r["date"] for r in rows] != expected:
            raise ValueError("vendor/exchange calendar disagreement")
        frame = {}
        for row in rows:
            values = {k: float(row[k]) for k in ("open", "high", "low", "close", "volume")}
            if not all(math.isfinite(v) and v > 0 for v in values.values()):
                raise ValueError("missing/invalid quote or volume")
            if not values["low"] <= min(values["open"], values["close"]) <= max(values["open"], values["close"]) <= values["high"]:
                raise ValueError("inconsistent OHLC")
            frame[row["date"]] = values
        frames[asset] = frame
        divs = json.loads((folder / (asset + "-dividends.json")).read_text())
        if len(set(x["ex_date"] for x in divs)) != len(divs):
            raise ValueError("duplicate dividend date")
        if any(x["ex_date"] not in frame or not math.isfinite(x["amount"]) or x["amount"] < 0 for x in divs):
            raise ValueError("invalid dividend")
        dividends[asset] = {x["ex_date"]: x["amount"] for x in divs}
    with (folder / "planned_calendar.csv").open(newline="", encoding="utf-8") as stream:
        planned = [r["session"][:10] for r in csv.DictReader(stream)]
    if planned != sorted(set(planned)) or not set(calendar).issubset(planned):
        raise ValueError("invalid planned/actual calendar relation")
    return calendar, frames, dividends, manifest, planned


def make_schedule(calendar, mode="calendar", seed=20261024):
    if mode not in ("calendar", "midmonth", "random", "SPY", "SHV", "cash"):
        raise ValueError("unknown mode")
    months = defaultdict(list)
    for i, day in enumerate(calendar):
        months[day[:7]].append(i)
    buys, sells, windows = {}, {}, []
    if mode in ASSETS:
        for indices in months.values():
            buys[calendar[indices[0]]] = mode
        return buys, sells, windows
    if mode == "cash":
        return buys, sells, windows
    rng = random.Random(seed)
    ordered = list(months.values())
    for n, indices in enumerate(ordered):
        if mode == "calendar":
            if n + 1 == len(ordered) or len(ordered[n + 1]) < 3:
                continue
            entry, exit_at = indices[-1], ordered[n + 1][2]
        elif mode == "midmonth":
            if len(indices) < 14:
                continue
            entry, exit_at = indices[9], indices[12]
        else:
            if len(indices) < 12:
                continue
            offset = rng.randrange(3, len(indices) - 4)
            entry, exit_at = indices[offset], indices[offset + 3]
        if entry == 0 or exit_at + 1 >= len(calendar):
            continue
        sells[calendar[entry - 1]] = "SHV"
        buys[calendar[entry]] = "SPY"
        sells[calendar[exit_at]] = "SPY"
        buys[calendar[exit_at + 1]] = "SHV"
        windows.append({"entry_open": calendar[entry], "exit_close": calendar[exit_at]})
    return buys, sells, windows


def operational_schedule(planned, actual, mode, seed):
    buys, sells, windows = make_schedule(planned, mode, seed)
    closed = [{"date": d, "asset": s, "side": side, "status": "CANCELLED_MARKET_CLOSED"}
              for side, mapping in (("buy", buys), ("sell", sells)) for d, s in mapping.items() if d not in actual]
    if mode not in ASSETS and mode != "cash":
        buys = {d:s for d,s in buys.items() if s == "SPY"}
        sells = {d:s for d,s in sells.items() if s == "SHV"}
        for window in windows:
            i = bisect_left(actual, window["exit_close"])
            if i >= len(actual):
                continue
            sells[actual[i]] = "SPY"
            if i + 1 < len(actual):
                buys[actual[i+1]] = "SHV"
    return buys, sells, windows, closed


def simulate(calendar, frames, dividends, mode="calendar", multiplier=1, seed=20261024, retain=True, planning_calendar=None):
    buys, sells, windows, closures = operational_schedule(planning_calendar or calendar, calendar, mode, seed)
    days = [d for d in calendar if "2009-01-01" <= d <= "2026-09-30"]
    positions = {s: 0 for s in ASSETS}
    cash, peak = 10000.0, 10000.0
    receivables, ledger, equity, distributions = [], [], [], []
    total_cost, turnover, worst, low_bound, prior_nav = 0., 0., 0., 0., 10000.
    year_start, year_end = {}, {}
    exposure = []
    max_participation = 0.
    for day in days:
        current = date.fromisoformat(day)
        # Entitlement uses inventory carried across the ex-date boundary, before any open order.
        for s in ASSETS:
            amount = positions[s] * dividends[s].get(day, 0)
            if amount:
                due = (current + timedelta(days=90)).isoformat()
                receivables.append((due, amount))
                distributions.append({"ex_date": day, "asset": s, "shares": positions[s], "receivable_usd": amount, "modeled_cash_date": due})
        cash += math.fsum(v for due, v in receivables if due <= day)
        receivables = [(due, v) for due, v in receivables if due > day]
        asset = buys.get(day)
        if day == days[0] and mode in ASSETS:
            asset = mode
        blocked = asset and any(q and s != asset for s,q in positions.items())
        if blocked:
            ledger.append({"date":day,"side":"buy","asset":asset,"shares":0,"fee_usd":0.,"status":"BLOCKED_PREVIOUS_ASSET_NOT_SOLD","cash_after":cash})
        if asset and not blocked:
            previous = calendar[calendar.index(day) - 1]
            limit = 1.02 * frames[asset][previous]["close"]
            q = quantity(cash, limit, multiplier)
            price = frames[asset][day]["open"]
            filled = q > 0 and price < limit
            fee = cost(q, price, multiplier) if filled else 0.
            if filled:
                cash -= q * price + fee
                positions[asset] += q
                total_cost += fee
                turnover += q * price
                max_participation = max(max_participation, q / frames[asset][day]["volume"])
            ledger.append({"date": day, "side": "buy", "asset": asset, "submitted_shares": q, "shares": q if filled else 0,
                           "limit": limit, "price": price if filled else None, "fee_usd": fee,
                           "status": "FILLED_MODEL" if filled else "UNFILLED_LIMIT_OR_CASH", "cash_after": cash})
        receivable_value = math.fsum(v for _, v in receivables)
        low_nav = cash + receivable_value + math.fsum(positions[s] * frames[s][day]["low"] - cost(positions[s], frames[s][day]["low"], multiplier) for s in ASSETS)
        low_bound = min(low_bound, low_nav / peak - 1)
        asset = sells.get(day)
        if asset and positions[asset]:
            q, price = positions[asset], frames[asset][day]["close"]
            fee = cost(q, price, multiplier)
            cash += q * price - fee
            positions[asset] = 0
            total_cost += fee
            turnover += q * price
            max_participation = max(max_participation, q / frames[asset][day]["volume"])
            ledger.append({"date": day, "side": "sell", "asset": asset, "shares": q, "price": price, "fee_usd": fee, "status": "FILLED_MODEL", "cash_after": cash})
        if cash < -1e-8 or any(q < 0 for q in positions.values()):
            raise ArithmeticError("unfunded wallet")
        inventory = math.fsum(positions[s] * frames[s][day]["close"] for s in ASSETS)
        liquidation_cost = math.fsum(cost(positions[s], frames[s][day]["close"], multiplier) for s in ASSETS)
        nav = cash + receivable_value + inventory - liquidation_cost
        peak = max(peak, nav)
        worst = min(worst, nav / peak - 1)
        year = day[:4]
        year_start.setdefault(year, prior_nav)
        year_end[year] = nav
        prior_nav = nav
        exposure.append(positions["SPY"] * frames["SPY"][day]["close"] / (cash + receivable_value + inventory))
        equity.append({"date": day, "net_liquidation_usd": nav, "cash_usd": cash, "shares": dict(positions), "receivables_usd": receivable_value})
    years = {y: year_end[y] / year_start[y] - 1 for y in year_start}
    blocks = {label: math.prod(1+r for y,r in years.items() if start <= int(y) <= end)-1 for label,start,end in (("2009-13",2009,2013),("2014-18",2014,2018),("2019-23",2019,2023),("2024-26",2024,2026))}
    duration = ((date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days + 1)/365.25
    result = {"mode": mode, "cost_multiplier": multiplier, "seed": seed if mode == "random" else None,
              "first_session": days[0], "last_session": days[-1], "sessions": len(days), "initial_usd": 10000.,
              "final_net_liquidation_usd": nav, "net_profit_usd": nav-10000, "net_return": nav/10000-1,
              "cagr": (nav/10000)**(1/duration)-1, "max_close_drawdown": worst,
              "low_vs_prior_close_high_water": low_bound, "calendar_returns": years, "fixed_block_returns": blocks,
              "paid_costs_usd": total_cost, "terminal_hypothetical_liquidation_cost_usd": liquidation_cost,
              "dividends_entitled_usd": math.fsum(x["receivable_usd"] for x in distributions),
              "terminal_unpaid_receivables_usd": receivable_value, "mean_equity_exposure": sum(exposure)/len(exposure),
              "turnover_notional_usd": turnover, "maximum_trade_daily_volume_fraction": max_participation,
              "filled_orders": sum(x["status"] == "FILLED_MODEL" for x in ledger),
              "unfilled_orders": sum(x["status"] != "FILLED_MODEL" for x in ledger),
              "planned_equity_windows": sum("2009-01-01" <= x["entry_open"] <= "2026-09-30" for x in windows),
              "ending_inventory": positions}
    if retain:
        result.update(equity=equity, ledger=ledger, distributions=distributions, planned_windows=windows,
                      canceled_market_closed_orders=[x for x in closures if days[0] <= x["date"] <= days[-1]])
    return result


def evaluate(folder):
    calendar, frames, dividends, manifest, planned = load_data(folder)
    cases = [simulate(calendar, frames, dividends, mode, m, planning_calendar=planned) for m in (1,2) for mode in ("calendar","midmonth","SHV","SPY","cash")]
    controls = [simulate(calendar, frames, dividends, "random", 1, 20261024+i, False, planned) for i in range(100)]
    candidates = [c for c in cases if c["mode"] == "calendar"]
    bills = [c for c in cases if c["mode"] == "SHV"]
    tail = (1 + sum(c["net_return"] >= candidates[0]["net_return"] for c in controls)) / 101
    gates = {"positive_profit_both_costs": all(c["net_profit_usd"] > 0 for c in candidates),
             "exceeds_Treasury_CAGR_both_costs": all(c["cagr"] > b["cagr"] for c,b in zip(candidates,bills)),
             "drawdown_at_most_25pct": all(c["max_close_drawdown"] >= -.25 for c in candidates),
             "all_fixed_blocks_positive": all(all(x>0 for x in c["fixed_block_returns"].values()) for c in candidates),
             "random_window_tail_at_most_10pct": tail <= .10}
    return {"candidate": "EQUITY_CALENDAR_CARRY_V1_2", "evidence": "RETROSPECTIVE_DEVELOPMENT_ONLY", "gates": gates,
            "decision": "HISTORICAL_SCREEN_SURVIVOR_ONLY" if all(gates.values()) else "REJECTED_AS_DEFINED",
            "random_window_corrected_right_tail": tail, "cases": cases, "random_controls": controls, "source_manifest": manifest,
            "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "orders": False,
            "auction_execution_verified": False, "future_confirmation_started": False, "promotable": False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError("refuse evidence overwrite")
    root=Path(__file__).resolve().parents[2]
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    committed=subprocess.check_output(['git','show','HEAD:src/orderflow_edge_lab/equity_calendar_carry.py'],cwd=root)
    if Path(__file__).read_bytes().replace(b'\r\n',b'\n') != committed.replace(b'\r\n',b'\n'):
        raise ValueError('evaluator not committed before evaluation')
    config_hashes={}
    for name in ('equity_calendar_carry_v1.json','equity_calendar_carry_v1_1.json','equity_calendar_carry_v1_2.json'):
        raw=(root/'config'/name).read_bytes()
        frozen=subprocess.check_output(['git','show','9abf017:config/'+name],cwd=root)
        if raw != frozen:
            raise ValueError('protocol changed since pre-outcome freeze')
        config_hashes[name]=hashlib.sha256(raw).hexdigest()
    report=evaluate(args.source)
    report.update(executed_commit=commit,protocol_sha256=config_hashes,
                  source_manifest_sha256=hashlib.sha256((args.source/'manifest.json').read_bytes()).hexdigest())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,allow_nan=False,separators=(",",":")),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("cases","random_controls","source_manifest")},indent=2))
    for c in report["cases"]:
        print(json.dumps({k:v for k,v in c.items() if k not in ("equity","ledger","distributions","planned_windows","canceled_market_closed_orders")},indent=2))


if __name__ == "__main__":
    main()
