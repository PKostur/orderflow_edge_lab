"""Public-data, cash-secured put spread feasibility. No authenticated endpoints."""

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://www.deribit.com/api/v2/public/"
DAY = 86400000


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def request(method, params, destination):
    """Only allow the four public read methods needed for the snapshot."""
    if method not in {"get_time", "get_instruments", "get_index_price", "get_order_book"}:
        raise ValueError("public read-only allowlist")
    url = API + method + ("?" + urlencode(params) if params else "")
    began = time.time_ns()
    with urlopen(Request(url, headers={"User-Agent": "orderflow-options-paper/1.0"}), timeout=25) as response:
        raw = response.read()
    Path(destination).write_bytes(raw)
    payload = json.loads(raw)
    if "error" in payload or "result" not in payload:
        raise ValueError("API error: " + str(payload.get("error")))
    return payload["result"], {"url": url, "request_start_unix_ns": began, "response_end_unix_ns": time.time_ns(),
                               "file": Path(destination).name, "sha256": hashlib.sha256(raw).hexdigest()}


def select_spread(instruments, asset, index, now_ms):
    if not math.isfinite(index) or index <= 0:
        raise ValueError("bad index")
    eligible = [x for x in instruments if x.get("base_currency") == asset and x.get("kind") == "option"
                and x.get("option_type") == "put" and x.get("instrument_type") == "linear"
                and x.get("quote_currency") == "USDC" and x.get("settlement_currency") == "USDC"
                and x.get("state") == "open" and x.get("is_active") is True
                and 7 * DAY <= x["expiration_timestamp"] - now_ms <= 14 * DAY]
    if not eligible:
        raise ValueError("no eligible expiry")
    expiry = min(x["expiration_timestamp"] for x in eligible)
    eligible = [x for x in eligible if x["expiration_timestamp"] == expiry]
    short = max((x for x in eligible if x["strike"] <= .9 * index), key=lambda x: x["strike"], default=None)
    long = max((x for x in eligible if x["strike"] <= .8 * index), key=lambda x: x["strike"], default=None)
    if not short or not long or long["strike"] >= short["strike"]:
        raise ValueError("missing ordered strikes")
    if any(x["contract_size"] != 1 for x in (short, long)):
        raise ValueError("BTC/ETH multiplier expected one; refuse ambiguous amount conversion")
    if any(x.get("taker_commission", .0003) > .0003 for x in (short, long)):
        raise ValueError("metadata fee exceeds frozen standard fee")
    if short["min_trade_amount"] != long["min_trade_amount"]:
        raise ValueError("different amount increments")
    return short, long


def size_amount(short, long, index):
    """Ignore premium credit for conservative stress sizing before reading quotes."""
    ks, kl = short["strike"], long["strike"]
    # Doubled trading fee upper bounds and doubled maximum put delivery fee.
    entry_bound = 2 * 2 * .0003 * index
    delivery_bound = 2 * .00015 * (ks + kl)
    risk_per_unit = ks - kl + entry_bound + delivery_bound
    # A put's price cannot exceed its strike in the supported nonnegative-price model.
    reserve_per_unit = ks + kl + entry_bound + delivery_bound
    raw = min(100 / risk_per_unit, 2500 / reserve_per_unit)
    step = Decimal(str(short["min_trade_amount"]))
    if not step.is_finite() or step <= 0:
        raise ValueError("invalid minimum amount")
    amount = float((Decimal(str(raw)) / step).to_integral_value(rounding=ROUND_FLOOR) * step)
    if amount <= 0:
        raise ValueError("minimum order exceeds fixed risk/cash budget")
    return amount, {"sizing_loss_bound_ignoring_credit": amount * risk_per_unit,
                    "sizing_cash_reserve_upper_bound": amount * reserve_per_unit,
                    "underlying_amount": amount, "increment": float(step)}


def depth_vwap(levels, amount, side):
    if side not in ("buy", "sell") or amount <= 0:
        raise ValueError("invalid depth request")
    levels = [(float(p), float(q)) for p, q in levels]
    if not levels or any(not math.isfinite(x) or x <= 0 for level in levels for x in level):
        raise ValueError("empty/nonpositive depth")
    prices = [p for p, _ in levels]
    if prices != sorted(prices, reverse=side == "sell") or len(set(prices)) != len(prices):
        raise ValueError("unsorted depth")
    remaining, notionals = amount, []
    for price, available in levels:
        taken = min(remaining, available)
        notionals.append(taken * price)
        remaining -= taken
        if remaining <= amount * 1e-12:
            return math.fsum(notionals) / amount
    raise ValueError("insufficient executable depth")


def trading_fee(index, premium, amount, multiplier=1):
    return amount * min(.0003 * index, .125 * premium) * multiplier


def expiry_pnl(settlement, ks, kl, amount, credit, entry_fee, fee_multiplier=1):
    if not math.isfinite(settlement) or settlement < 0 or not ks > kl >= 0 or amount <= 0:
        raise ValueError("invalid payoff inputs")
    short, long = max(ks - settlement, 0), max(kl - settlement, 0)
    delivery = amount * sum(min(.00015 * settlement, .125 * x) for x in (short, long)) * fee_multiplier
    return credit - entry_fee + amount * (long - short) - delivery


def return_scenarios(folder, asset, horizon):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text())
    meta = manifest["symbols"][asset + "USDT"]
    path = folder / meta["aligned_csv"]
    if sha(path) != meta["aligned_csv_sha256"]:
        raise ValueError("underlying history hash mismatch")
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    closes = [float(r["close"]) for r in rows]
    times = [datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) for r in rows]
    if any(not math.isfinite(c) or c <= 0 for c in closes) or any((b-a).total_seconds() != 28800 for a,b in zip(times,times[1:])):
        raise ValueError("invalid underlying history")
    returns = [closes[i + horizon] / closes[i] for i in range(0, len(closes) - horizon, horizon)]
    if len(returns) < 30:
        raise ValueError("insufficient nonoverlapping scenarios")
    return returns, {"sha256": sha(path), "first_open_utc": rows[0]["timestamp"], "last_open_utc": rows[-1]["timestamp"],
                     "bars": len(rows), "scenario_horizon_bars": horizon, "nonoverlapping_scenarios": len(returns),
                     "horizon_rounding": "ceil DTE/8h; no return interpolation or implied historical options"}


def describe(values):
    rng = random.Random(20261023)
    means = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(2000))
    ordered = sorted(values)
    return {"scenarios": len(values), "mean_pnl_usdc": statistics.mean(values), "median_pnl_usdc": statistics.median(values),
            "loss_fraction": sum(x < 0 for x in values) / len(values), "worst_pnl_usdc": min(values),
            "worst_5pct_mean_pnl_usdc": statistics.mean(ordered[:max(1, math.ceil(.05 * len(values)))]),
            "bootstrap_5pct_mean_pnl_usdc": means[99], "uncertainty": "development scenario bootstrap only; not prospective edge inference"}


def snapshot(folder, history):
    root = Path(__file__).resolve().parents[2]
    design_commit = subprocess.check_output(["git", "rev-parse", "75915a5"], cwd=root, text=True).strip()
    frozen_config = subprocess.check_output(["git", "show", design_commit + ":config/options_income_v1.json"], cwd=root)
    if (root / "config/options_income_v1.json").read_bytes() != frozen_config:
        raise ValueError("config differs from frozen design")
    implementation_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    committed_source = subprocess.check_output(["git", "show", "HEAD:src/orderflow_edge_lab/options_income.py"], cwd=root)
    if Path(__file__).read_bytes().replace(b"\r\n", b"\n") != committed_source.replace(b"\r\n", b"\n"):
        raise ValueError("evaluator source is not committed")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    receipts = []
    now, receipt = request("get_time", {}, folder / "exchange-time-start.json")
    receipts.append(receipt)
    instruments, receipt = request("get_instruments", {"currency": "USDC", "kind": "option", "expired": "false"}, folder / "instruments.json")
    receipts.append(receipt)
    selected, results = {}, {}
    for asset in ("BTC", "ETH"):
        try:
            index_reply, receipt = request("get_index_price", {"index_name": asset.lower() + "_usdc"}, folder / (asset + "-index.json"))
            receipts.append(receipt)
            index = index_reply["index_price"]
            short, long = select_spread(instruments, asset, index, now)
            amount, sizing = size_amount(short, long, index)
            selected[asset] = {"index": index, "short": short, "long": long, "amount": amount, "sizing": sizing}
        except (ValueError, KeyError) as exc:
            results[asset] = {"decision": "NO_FEASIBLE_POSITION", "reason": str(exc)}
    jobs = [(asset, side, x[side]["instrument_name"]) for asset, x in selected.items() for side in ("short", "long")]
    books = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(request, "get_order_book", {"instrument_name": name, "depth": 20}, folder / (asset + "-" + side + "-book.json")): (asset, side) for asset, side, name in jobs}
        for future, key in futures.items():
            book, receipt = future.result()
            books[key] = book
            receipts.append(receipt)
    finished, receipt = request("get_time", {}, folder / "exchange-time-end.json")
    receipts.append(receipt)
    for asset, x in selected.items():
        try:
            short, long, index, amount = x["short"], x["long"], x["index"], x["amount"]
            sb, lb = books[(asset, "short")], books[(asset, "long")]
            for metadata, book in ((short, sb), (long, lb)):
                if book["instrument_name"] != metadata["instrument_name"] or book["state"] != "open":
                    raise ValueError("wrong/closed book")
                if not 0 <= finished - book["timestamp"] <= 5000:
                    raise ValueError("stale/future-dated quote")
                if book.get("best_bid_price") and book.get("best_ask_price") and book["best_bid_price"] > book["best_ask_price"]:
                    raise ValueError("crossed book")
                if book.get("bids") and book.get("asks") and book["bids"][0][0] > book["asks"][0][0]:
                    raise ValueError("crossed depth arrays")
                for field, levels in (("best_bid_price", "bids"), ("best_ask_price", "asks")):
                    if book.get(levels) and book.get(field) is not None and book[field] != book[levels][0][0]:
                        raise ValueError("best price/depth disagreement")
            sell = depth_vwap(sb["bids"], amount, "sell")
            buy = depth_vwap(lb["asks"], amount, "buy")
            credit = (sell - buy) * amount
            entry = trading_fee(index, sell, amount) + trading_fee(index, buy, amount)
            horizon = math.ceil((short["expiration_timestamp"] - now) / 28800000)
            ratios, historical = return_scenarios(history, asset, horizon)
            cases = []
            for fee_multiplier, credit_factor in ((1, 1.0), (2, .9)):
                case_credit = credit * credit_factor
                pnl = [expiry_pnl(index * r, short["strike"], long["strike"], amount, case_credit, entry * fee_multiplier, fee_multiplier) for r in ratios]
                bound = amount * (short["strike"] - long["strike"] + fee_multiplier * .00015 * (short["strike"] + long["strike"])) + entry * fee_multiplier - case_credit
                reserve = short["strike"] * amount + buy * amount + entry * fee_multiplier + amount * fee_multiplier * .00015 * (short["strike"] + long["strike"])
                metrics = describe(pnl)
                cases.append({"fee_multiplier": fee_multiplier, "credit_factor": credit_factor, "net_entry_credit_usdc": case_credit - entry * fee_multiplier,
                              "conservative_net_loss_bound_usdc": bound, "cash_reserve_usdc": reserve, "metrics": metrics, "scenario_pnl_usdc": pnl})
            gates = {"positive_credit": credit > entry,
                     "positive_mean_and_bootstrap_both_costs": all(c["metrics"]["mean_pnl_usdc"] > 0 and c["metrics"]["bootstrap_5pct_mean_pnl_usdc"] > 0 for c in cases),
                     "loss_budget": all(0 <= c["conservative_net_loss_bound_usdc"] <= 100 for c in cases),
                     "cash_budget": all(c["cash_reserve_usdc"] <= 2500 for c in cases),
                     "observed_losses_within_bound": all(min(c["scenario_pnl_usdc"]) >= -c["conservative_net_loss_bound_usdc"] - 1e-8 for c in cases)}
            results[asset] = {**x, "sell_vwap": sell, "buy_vwap": buy, "entry_fees_usdc": entry, "gross_credit_usdc": credit,
                              "historical_scenarios": historical, "cases": cases, "gates": gates,
                              "decision": "SCENARIO_SCREEN_SURVIVOR_ONLY" if all(gates.values()) else "REJECTED_AS_DEFINED"}
        except (ValueError, KeyError) as exc:
            results[asset] = {**x, "decision": "NO_FEASIBLE_POSITION", "reason": str(exc)}
    portfolio = []
    if all(results[a].get("cases") for a in ("BTC", "ETH")):
        for number in range(2):
            a, b = (results[s]["cases"][number]["scenario_pnl_usdc"] for s in ("BTC", "ETH"))
            anchors_match = all(results["BTC"]["historical_scenarios"][k] == results["ETH"]["historical_scenarios"][k] for k in ("first_open_utc", "last_open_utc", "scenario_horizon_bars", "bars"))
            if len(a) == len(b) and anchors_match:
                joint = [x + y for x, y in zip(a, b)]
                portfolio.append({"case": number, "metrics": describe(joint), "scenario_pnl_usdc": joint,
                                  "joint_blocks": "synchronous BTC/ETH blocks, preserving observed cross-asset dependence"})
    survivor = all(results[a]["decision"] == "SCENARIO_SCREEN_SURVIVOR_ONLY" for a in ("BTC", "ETH"))
    report = {"candidate": "CASH_SECURED_OPTION_PUT_SPREAD_V1", "evidence": "LIVE_INDICATIVE_QUOTES_PLUS_SPENT_UNDERLYING_RETURN_SCENARIOS",
              "exchange_capture_start_ms": now, "exchange_capture_end_ms": finished,
              "decision": "SCENARIO_SCREEN_SURVIVOR_ONLY" if survivor else "NO_PORTFOLIO_ADMISSION",
              "results": results, "portfolio": portfolio, "raw_receipts": receipts,
              "actual_account_margin_verified": False, "atomic_execution_verified": False,
              "historical_options_backtest": False, "future_confirmation_started": False, "promotable": False, "orders": False,
              "design_commit": design_commit, "implementation_commit": implementation_commit,
              "config_sha256": hashlib.sha256(frozen_config).hexdigest(), "history_manifest_sha256": sha(Path(history) / "manifest.json"),
              "evaluator_sha256": sha(__file__)}
    save(folder / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    args = parser.parse_args()
    report = snapshot(args.output, args.history)
    print(report["decision"])
    for asset, result in report["results"].items():
        print(asset, result["decision"], result.get("reason", result.get("gates")))
        for case in result.get("cases", []):
            print(json.dumps({k:v for k,v in case.items() if k != "scenario_pnl_usdc"}, indent=2))


if __name__ == "__main__":
    main()
