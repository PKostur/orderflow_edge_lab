"""Offline synthetic calibration; never imports provider adapters or live engines.

The canonical quote ledger is an explicitly new, fixed-contract successor model,
NOT a replacement for frozen canonical v3 weight/compounding semantics. The
Nautilus path reads actual native fills, account states and PositionAdjusted
funding events. It never uses the canonical calculator or expected_ledger.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import zipfile
from typing import Any, Mapping

from orderflow_edge_lab.contracts_v2 import canonical_json_sha256, non_authority_claims

ENGINE_VERSION = "2.0.0rc5"
WHEEL_NAME = "nautilus_trader-2.0.0rc5-cp312-cp312-manylinux_2_34_x86_64.whl"
WHEEL_SHA256 = "eab45fafd2312deda1236554c49a9798bfc76bc8465af864878e2f70189ebebe"
ENGINE_SPEC = {
    "engine_name": "NautilusTrader",
    "engine_version": ENGINE_VERSION,
    "distribution_sha256": WHEEL_SHA256,
    "runner_protocol_version": "orderflow-external-ledger-v1",
}
TOLERANCE = {"absolute": 1e-7, "relative": 0.0}
BASE_NS = 1_700_000_000_000_000_000
STEP_NS = 10_000_000_000


class IndependentCalibrationUnavailable(RuntimeError):
    """Optional runtime absent, incompatible, or not tied to authentic wheel bytes."""


def _money(value: Any) -> float:
    return float(str(value).split()[0])


def validate_quote_case(case: Mapping[str, Any]) -> dict[str, Any]:
    """Small bounded fixture protocol, rejecting unsupported economic mechanisms."""
    from orderflow_edge_lab.economics_v2 import EconomicsV2Error, _exact_keys, _mapping, _number

    case = _mapping(case, "quote_case")
    _exact_keys(case, {"case_id", "initial_cash", "taker_fee", "slippage_ticks", "steps"}, "quote_case")
    if not isinstance(case["case_id"], str) or not case["case_id"].strip():
        raise EconomicsV2Error("quote_case.case_id must be nonempty")
    initial = _number(case["initial_cash"], "initial_cash", positive=True)
    fee = _number(case["taker_fee"], "taker_fee", nonnegative=True)
    if fee > 0.01 or initial < 1000:
        raise EconomicsV2Error("synthetic protocol requires cash >=1000 and fee <=0.01")
    ticks = case["slippage_ticks"]
    if type(ticks) is not int or ticks not in (0, 2):
        raise EconomicsV2Error("rc5 supports only 0 or observed 2-tick displacement; NOT arbitrary bps/impact")
    steps = case["steps"]
    if not isinstance(steps, list) or not 2 <= len(steps) <= 20:
        raise EconomicsV2Error("quote_case.steps requires 2..20 entries")
    normalized = []
    for idx, step in enumerate(steps):
        step = _mapping(step, "step")
        _exact_keys(step, {"bid", "ask", "target", "funding_rate"}, "step")
        bid = _number(step["bid"], "bid", positive=True)
        ask = _number(step["ask"], "ask", positive=True)
        if ask <= bid or ask > 1000 or any(round(v, 2) != v for v in (bid, ask)):
            raise EconomicsV2Error("quotes require positive two-decimal BBO, bid < ask <=1000")
        if type(step["target"]) is not int or abs(step["target"]) > 10:
            raise EconomicsV2Error("target requires integer contracts within +/-10")
        rate = step["funding_rate"]
        if rate is not None:
            rate = _number(rate, "funding_rate")
            if idx == 0 or abs(rate) > 0.01:
                raise EconomicsV2Error("funding requires a previous quote and absolute rate <=0.01")
        normalized.append({"bid": bid, "ask": ask, "target": step["target"], "funding_rate": rate})
    if normalized[-1]["target"] != 0 or normalized[-2]["target"] == 0:
        raise EconomicsV2Error("final step must explicitly liquidate a nonzero held position")
    return {"case_id": case["case_id"], "initial_cash": initial, "taker_fee": fee,
            "slippage_ticks": ticks, "steps": normalized}


def _event_order(fills: list[dict], funding: list[dict]) -> list[str]:
    events = [(x["timestamp_ns"], f"fill:{idx}") for idx, x in enumerate(fills)]
    events += [(x["timestamp_ns"], f"funding:{idx}") for idx, x in enumerate(funding)]
    return [name for _, name in sorted(events)]


def canonical_quote_ledger_v2(case: Mapping[str, Any]) -> dict[str, Any]:
    """Transparent reference fixed-contract BBO/weighted-average-cost ledger.

    Native engine is never called here. Funding settles on the old position at
    the previous quote midpoint, one ns before the next quote/resize/reversal.
    Fees and funding use USDT's eight-decimal cash precision. Terminal equity
    is account cash, not an equity-weighted compounded return.
    """
    case = validate_quote_case(case)
    cash = case["initial_cash"]
    qty, avg = 0, 0.0
    episode_net, episode_start = 0.0, None
    fills, flows, trades, cash_series = [], [], [], []
    for idx, step in enumerate(case["steps"]):
        boundary = BASE_NS + idx * STEP_NS
        rate = step["funding_rate"]
        if rate is not None and qty:
            previous = case["steps"][idx - 1]
            amount = round(-qty * (previous["bid"] + previous["ask"]) / 2 * rate, 8)
            cash += amount
            episode_net += amount
            flows.append({"kind": "funding", "timestamp_ns": boundary, "amount": amount})
            cash_series.append({"timestamp_ns": boundary, "cash": round(cash, 8)})
        target = step["target"]
        delta = target - qty
        if not delta:
            continue
        side = 1 if delta > 0 else -1
        price = round((step["ask"] if side > 0 else step["bid"]) + side * case["slippage_ticks"] * 0.01, 2)
        fee = round(abs(delta) * price * case["taker_fee"], 8)
        ts = boundary + 1
        fills.append({"timestamp_ns": ts, "side": "BUY" if side > 0 else "SELL",
                      "quantity": abs(delta), "price": price, "commission": fee,
                      "terminal": idx == len(case["steps"]) - 1})
        old_qty = qty
        close_qty = min(abs(qty), abs(delta)) if qty * delta < 0 else 0
        gross = close_qty * (price - avg) * (1 if qty > 0 else -1)
        cash += gross - fee
        if close_qty:
            close_fee = round(fee * close_qty / abs(delta), 8)
            episode_net += gross - close_fee
            if close_qty == abs(qty):
                trades.append({"entry_timestamp_ns": episode_start, "exit_timestamp_ns": ts,
                               "net_pnl": round(episode_net, 8)})
                episode_start, episode_net = None, 0.0
            fee -= close_fee
        if target and (not old_qty or old_qty * target < 0):
            avg = price
            episode_start = ts
        elif old_qty * delta > 0:
            avg = (abs(old_qty) * avg + abs(delta) * price) / abs(target)
        if target and (not close_qty or old_qty * target < 0):
            episode_net -= fee
        qty = target
        cash_series.append({"timestamp_ns": ts, "cash": round(cash, 8)})
    return {"event_order": _event_order(fills, flows), "fills": fills, "cash_flows": flows,
            "trades": trades, "cash_series": cash_series,
            "turnover_units": sum(x["quantity"] for x in fills),
            "terminal_equity": round(cash, 8), "final_position": qty}


def verify_engine_wheel(wheel_path: str | Path) -> dict[str, Any]:
    """Verify published wheel SHA and installed native extension byte-for-byte.

    No network call: a caller must supply the authentic downloaded wheel.
    Local byte equality is not signature/attestation or external verification.
    """
    try:
        if platform.python_implementation() != "CPython" or sys.version_info[:2] != (3, 12):
            raise IndependentCalibrationUnavailable("pinned wheel requires CPython 3.12")
        if platform.system() != "Linux" or platform.machine() != "x86_64":
            raise IndependentCalibrationUnavailable("pinned wheel requires Linux x86_64")
        path = Path(wheel_path)
        if path.name != WHEEL_NAME or hashlib.sha256(path.read_bytes()).hexdigest() != WHEEL_SHA256:
            raise IndependentCalibrationUnavailable("wheel filename/hash does not match published rc5 pin")
        if importlib.metadata.version("nautilus_trader") != ENGINE_VERSION:
            raise IndependentCalibrationUnavailable("installed engine version does not match rc5 pin")
        import nautilus_trader
        dist = importlib.metadata.distribution("nautilus_trader")
        verified_files = 0
        with zipfile.ZipFile(path) as wheel:
            for member in wheel.namelist():
                if member.startswith("nautilus_trader/") and not member.endswith("/"):
                    installed = Path(dist.locate_file(member))
                    if hashlib.sha256(installed.read_bytes()).digest() != hashlib.sha256(wheel.read(member)).digest():
                        raise IndependentCalibrationUnavailable(f"installed bytes differ from authentic wheel: {member}")
                    verified_files += 1
        return {"python": sys.version, "implementation": platform.python_implementation(),
                "platform": platform.platform(), "machine": platform.machine(),
                "engine_version": nautilus_trader.__version__, "wheel_filename": WHEEL_NAME,
                "wheel_sha256": WHEEL_SHA256, "installed_files_verified": verified_files,
                "identity_method": "PyPI wheel SHA256 + installed package byte equality",
                "external_signature_or_attestation_verified": False}
    except IndependentCalibrationUnavailable:
        raise
    except (OSError, importlib.metadata.PackageNotFoundError, ImportError, zipfile.BadZipFile) as exc:
        raise IndependentCalibrationUnavailable(f"{type(exc).__name__}:{exc}") from exc


def run_nautilus_quote_case_v2(case: Mapping[str, Any]) -> tuple[dict, dict]:
    """Native BacktestEngine matching, fees, netting, funding, terminal fills.

    Inputs contain quotes/targets/rates only. No expected or canonical ledger is
    read. Native position PnL and account totals are used, not recalculated from
    our fills formula. The strategy only submits synthetic market-order deltas.
    """
    case = validate_quote_case(case)
    from nautilus_trader.backtest import BacktestEngine
    from nautilus_trader.common import LogLevel
    from nautilus_trader.config import BacktestEngineConfig, LoggerConfig, RiskEngineConfig, StrategyConfig
    from nautilus_trader.execution import MakerTakerFeeModel, OneTickSlippageFillModel, StaticLatencyModel
    from nautilus_trader.model import (
        AccountType, CryptoPerpetual, Currency, FundingRateUpdate, InstrumentId, Money,
        OmsType, OrderSide, Price, Quantity, QuoteTick, Symbol, Venue,
    )
    from nautilus_trader.trading import Strategy

    venue = Venue("OFFLINE")
    iid = InstrumentId.from_str("BTCUSDT-PERP.OFFLINE")
    usdt = Currency.from_str("USDT")
    instrument = CryptoPerpetual(
        instrument_id=iid, raw_symbol=Symbol("BTCUSDT"), base_currency=Currency.from_str("BTC"),
        quote_currency=usdt, settlement_currency=usdt, is_inverse=False,
        price_precision=2, size_precision=0, price_increment=Price.from_str("0.01"),
        size_increment=Quantity.from_int(1), multiplier=Quantity.from_int(1), lot_size=Quantity.from_int(1),
        margin_init=Decimal("0.1"), margin_maint=Decimal("0.05"),
        maker_fee=Decimal(str(case["taker_fee"])), taker_fee=Decimal(str(case["taker_fee"])),
        ts_event=0, ts_init=0,
    )

    class SyntheticTargets(Strategy):
        def __init__(self) -> None:
            super().__init__(StrategyConfig())
            self.current = 0
            self.raw_fills: list[dict] = []

        def on_start(self) -> None:
            self.subscribe_quotes(iid)

        def on_quote(self, quote: Any) -> None:
            idx = (quote.ts_event - BASE_NS - 1) // STEP_NS
            target = case["steps"][idx]["target"]
            delta = target - self.current
            if delta:
                self.submit_order(self.order_factory.market(
                    iid, OrderSide.BUY if delta > 0 else OrderSide.SELL, Quantity.from_int(abs(delta)),
                ))
                self.current = target

        def on_order_filled(self, event: Any) -> None:
            self.raw_fills.append(event.to_dict())

    engine = BacktestEngine(BacktestEngineConfig(
        logging=LoggerConfig(stdout_level=LogLevel.ERROR), risk_engine=RiskEngineConfig(bypass=True),
    ))
    try:
        fill_model = (OneTickSlippageFillModel(prob_fill_on_limit=1.0, prob_slippage=1.0, random_seed=42)
                      if case["slippage_ticks"] else None)
        engine.add_venue(
            venue=venue, oms_type=OmsType.NETTING, account_type=AccountType.MARGIN,
            starting_balances=[Money(case["initial_cash"], usdt)], base_currency=usdt,
            default_leverage=Decimal(1), fill_model=fill_model, fee_model=MakerTakerFeeModel(),
            latency_model=StaticLatencyModel(base_latency_nanos=0), bar_execution=False,
        )
        engine.add_instrument(instrument)
        quotes, rates = [], []
        for idx, step in enumerate(case["steps"]):
            ts = BASE_NS + idx * STEP_NS + 1
            quotes.append(QuoteTick(
                instrument_id=iid, bid_price=instrument.make_price(step["bid"]),
                ask_price=instrument.make_price(step["ask"]), bid_size=Quantity.from_int(1000),
                ask_size=Quantity.from_int(1000), ts_event=ts, ts_init=ts,
            ))
            if step["funding_rate"] is not None:
                rates.append(FundingRateUpdate(
                    instrument_id=iid, rate=Decimal(str(step["funding_rate"])),
                    ts_event=ts - 1_000_000_001, ts_init=ts - 1_000_000_001, next_funding_ns=ts - 1,
                ))
        engine.add_data(quotes)
        if rates:
            engine.add_data(rates)
        strategy = SyntheticTargets()
        engine.add_strategy(strategy)
        engine.run()
        raw_positions = [p.to_dict() for p in list(engine.cache.positions()) + list(engine.cache.position_snapshots())]
        raw_positions.sort(key=lambda p: p["ts_opened"])
        account = engine.cache.account_for_venue(venue)
        raw_account = [event.to_dict() for event in account.events]
        funding = [a for p in raw_positions for a in p.get("adjustments", []) if a["adjustment_type"] == "FUNDING"]
        funding.sort(key=lambda a: a["ts_event"])
        flows = [{"kind": "funding", "timestamp_ns": a["ts_event"], "amount": _money(a["pnl_change"])} for a in funding]
        fills = [{"timestamp_ns": f["ts_event"], "side": f["order_side"], "quantity": float(f["last_qty"]),
                  "price": float(f["last_px"]), "commission": _money(f["commission"]),
                  "terminal": f["ts_event"] == BASE_NS + (len(case["steps"]) - 1) * STEP_NS + 1}
                 for f in strategy.raw_fills]
        trades = [{"entry_timestamp_ns": p["ts_opened"], "exit_timestamp_ns": p["ts_closed"],
                   "net_pnl": _money(p["realized_pnl"])} for p in raw_positions]
        cash_by_ts = {a["ts_event"]: float(a["balances"][0]["total"]) for a in raw_account}
        economic_times = {f["timestamp_ns"] for f in fills} | {f["timestamp_ns"] for f in flows}
        ledger = {"event_order": _event_order(fills, flows), "fills": fills, "cash_flows": flows,
                  "trades": trades, "cash_series": [{"timestamp_ns": ts, "cash": cash_by_ts[ts]} for ts in sorted(economic_times)],
                  "turnover_units": sum(f["quantity"] for f in fills), "terminal_equity": account.balance_total(usdt).as_double(),
                  "final_position": sum(p.signed_qty for p in engine.cache.positions_open())}
        audit = {"native_order_filled_events": strategy.raw_fills, "native_positions": raw_positions,
                 "native_account_states": raw_account, "native_funding_adjustments": funding,
                 "native_pnl_cash_residual": ledger["terminal_equity"] - case["initial_cash"] - sum(t["net_pnl"] for t in trades),
                 "native_fee_total": sum(f["commission"] for f in fills),
                 "native_funding_total": sum(f["amount"] for f in flows),
                 "open_positions": engine.cache.positions_open_count()}
        return ledger, audit
    finally:
        engine.dispose()


def run_fixture(fixture: Mapping[str, Any], wheel_path: str | Path) -> dict[str, Any]:
    """Adapter protocol. expected_ledger is deliberately not consumed."""
    runtime = verify_engine_wheel(wheel_path)
    case = fixture["assumptions"]["quote_case"]
    ledger, audit = run_nautilus_quote_case_v2(case)
    return {"engine_identity": dict(ENGINE_SPEC), "ledger": ledger,
            "runtime_evidence": {"runtime": runtime, "audit": audit,
                                 "adapter_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                 "fixture_input_sha256": canonical_json_sha256(case),
                                 "non_authority_claims": non_authority_claims()}}


def run_frozen_v3_diagnostic(case: Mapping[str, Any]) -> dict[str, Any]:
    """Execute frozen v3 on the same synthetic economic inputs, honestly scoped.

    v3 only accepts bar opens/target equity weights and turnover-cost bps, not
    native quote fills/contract quantities. Mapping targets to INITIAL-equity
    nominal weights below is explicit. This is diagnostic, not equivalence.
    Neither v3 nor its frozen research evidence is modified.
    """
    import pandas as pd
    from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3
    from orderflow_edge_lab.universal_backtest import ExecutionModel

    case = validate_quote_case(case)
    steps = case["steps"]
    mids = [(s["bid"] + s["ask"]) / 2 for s in steps]
    index = pd.to_datetime([BASE_NS - STEP_NS] + [BASE_NS + i * STEP_NS for i in range(len(steps))], utc=True)
    prices = [mids[0]] + mids
    frame = pd.DataFrame({k: prices for k in ("open", "high", "low", "close")}, index=index)
    frame["volume"] = 1000.0
    target = pd.Series([s["target"] * mids[i] / case["initial_cash"] for i, s in enumerate(steps)] + [0.0], index=index)
    rates = {index[i + 1]: s["funding_rate"] for i, s in enumerate(steps) if s["funding_rate"] is not None}

    class DeclaredWeightTargets:
        strategy_id = "offline_native_calibration_v3_diagnostic"
        warmup_bars = 0

        def generate_target(self, frame: Any, params: Any, context: Any) -> Any:
            return target

    result = run_canonical_backtest_v3(
        frame, DeclaredWeightTargets(), {},
        ExecutionModel(round_trip_cost_bps=case["taker_fee"] * 20_000,
                       slippage_bps_per_turnover_unit=case["slippage_ticks"] * 0.01 / mids[0] * 10_000,
                       max_abs_position=1.0),
        funding=pd.Series(rates, dtype=float) if rates else None,
    )
    return {"status": "NOT_CALIBRATED_DIFFERENT_SEMANTICS", "result": result,
            "initial_equity_mapped_terminal_cash": case["initial_cash"] * (1 + result["total_return"]),
            "mapping": "quote midpoint bars; contracts*midpoint/INITIAL cash target weights; next-open shift",
            "gaps": ["no bid/ask inputs", "equity-compounded turnover costs vs native notional fees",
                     "target weights vs native fixed contracts", "funding at current bar weight vs old-position previous quote mark"],
            "non_authority_claims": non_authority_claims()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Genuine offline synthetic Nautilus rc5 adapter")
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--wheel", required=True)
    args = parser.parse_args()
    try:
        fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        output = run_fixture(fixture, args.wheel)
        Path(args.output).write_text(json.dumps(output, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return 0
    except (IndependentCalibrationUnavailable, ValueError, OSError, KeyError, RuntimeError) as exc:
        print(json.dumps({"status": "NOT_CALIBRATED_ENGINE_UNAVAILABLE", "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
