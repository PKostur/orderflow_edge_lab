from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.common import LogLevel
from nautilus_trader.config import BacktestEngineConfig, LoggerConfig, RiskEngineConfig, StrategyConfig
from nautilus_trader.execution import StaticLatencyModel
from nautilus_trader.indicators import ExponentialMovingAverage, SimpleMovingAverage
from nautilus_trader.model import (
    AccountType,
    Bar,
    BarType,
    CryptoPerpetual,
    Currency,
    InstrumentId,
    Money,
    OmsType,
    OrderSide,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    Venue,
)
from nautilus_trader.trading import Strategy


class FrozenTrendExecutionConfig(StrategyConfig):
    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        bar_type: BarType,
        trade_size: Decimal,
        fast_ema: int,
        slow_ema: int,
        atr_period: int,
        threshold: float,
        **_kwargs: object,
    ) -> None:
        super().__init__()
        self.instrument_id = instrument_id
        self.bar_type = bar_type
        self.trade_size = trade_size
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.atr_period = atr_period
        self.threshold = threshold


class FrozenTrendExecutionStrategy(Strategy):
    def __init__(self, config: FrozenTrendExecutionConfig) -> None:
        super().__init__(config)
        self._fast = ExponentialMovingAverage(config.fast_ema)
        self._slow = ExponentialMovingAverage(config.slow_ema)
        self._atr = SimpleMovingAverage(config.atr_period)
        self._previous_close: float | None = None
        self._bars_seen = 0
        self._desired_target = 0

    def on_start(self) -> None:
        self.register_indicator_for_bars(self.config.bar_type, self._fast)
        self.register_indicator_for_bars(self.config.bar_type, self._slow)
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        high = bar.high.as_double()
        low = bar.low.as_double()
        close = bar.close.as_double()
        tr = abs(high - low)
        if self._previous_close is not None:
            tr = max(tr, abs(high - self._previous_close), abs(low - self._previous_close))
        self._atr.update_raw(tr)
        self._bars_seen += 1
        self._previous_close = close

        target = 0
        if self._bars_seen >= self.config.slow_ema and self._bars_seen >= self.config.atr_period:
            atr_value = float(self._atr.value)
            if atr_value != 0.0:
                score = (float(self._fast.value) - float(self._slow.value)) / atr_value
                if score > self.config.threshold:
                    target = 1
                elif score < -self.config.threshold:
                    target = -1

        delta = target - self._desired_target
        if delta != 0:
            instrument = self.cache.instrument(self.config.instrument_id)
            if instrument is None:
                raise RuntimeError(f"instrument missing from cache: {self.config.instrument_id}")
            side = OrderSide.BUY if delta > 0 else OrderSide.SELL
            qty = instrument.make_qty(abs(delta) * self.config.trade_size)
            order = self.order_factory.market(self.config.instrument_id, side, qty)
            self.submit_order(order)
            self._desired_target = target


def _price_precision(frame: pd.DataFrame) -> int:
    # A fixed 8-decimal calibration precision is sufficient for the selected USDT contracts
    # and is tighter than the parity tolerance. This is not an exchange tick-size claim.
    return 8


def _instrument(symbol: str, frame: pd.DataFrame, venue: Venue) -> CryptoPerpetual:
    base_code = symbol.split("_", 1)[0]
    base = Currency.from_str(base_code)
    quote = Currency.from_str("USDT")
    if base is None or quote is None:
        raise RuntimeError(f"unable to construct currencies for {symbol}")
    precision = _price_precision(frame)
    instrument_id = InstrumentId.from_str(f"{base_code}USDT-PERP.{venue.value}")
    return CryptoPerpetual(
        instrument_id=instrument_id,
        raw_symbol=Symbol(f"{base_code}USDT"),
        base_currency=base,
        quote_currency=quote,
        settlement_currency=quote,
        is_inverse=False,
        price_precision=precision,
        size_precision=0,
        price_increment=Price.from_str("0.00000001"),
        size_increment=Quantity.from_int(1),
        multiplier=Quantity.from_int(1),
        lot_size=Quantity.from_int(1),
        margin_init=Decimal("1.0"),
        margin_maint=Decimal("0.5"),
        maker_fee=Decimal("0"),
        taker_fee=Decimal("0"),
        ts_event=0,
        ts_init=0,
    )


def _build_market_data(frame: pd.DataFrame, instrument: CryptoPerpetual, interval_hours: int, quote_offset_ns: int) -> tuple[list[Bar], list[QuoteTick], BarType]:
    interval_ns = int(pd.Timedelta(hours=interval_hours).value)
    bar_type = BarType.from_str(f"{instrument.id.value}-{interval_hours}-HOUR-LAST-EXTERNAL")
    bars: list[Bar] = []
    quotes: list[QuoteTick] = []
    # The last source bar has no next open inside the frozen window, so it must not
    # create a calibratable execution order.
    for i in range(len(frame) - 1):
        row = frame.iloc[i]
        next_row = frame.iloc[i + 1]
        open_ns = int(frame.index[i].value)
        close_ns = open_ns + interval_ns
        bars.append(
            Bar(
                bar_type=bar_type,
                open=instrument.make_price(float(row["open"])),
                high=instrument.make_price(float(row["high"])),
                low=instrument.make_price(float(row["low"])),
                close=instrument.make_price(float(row["close"])),
                volume=Quantity.from_int(max(1, int(round(float(row["volume"]))))),
                ts_event=close_ns,
                ts_init=close_ns,
            )
        )
        next_open = instrument.make_price(float(next_row["open"]))
        quote_ts = close_ns + int(quote_offset_ns)
        quotes.append(
            QuoteTick(
                instrument_id=instrument.id,
                bid_price=next_open,
                ask_price=next_open,
                bid_size=Quantity.from_int(1_000_000),
                ask_size=Quantity.from_int(1_000_000),
                ts_event=quote_ts,
                ts_init=quote_ts,
            )
        )
    return bars, quotes, bar_type


def _expected_fills(frame: pd.DataFrame, targets: pd.DataFrame, quote_offset_ns: int) -> list[dict[str, Any]]:
    execution = targets["reference_execution_target"].astype(float)
    rows: list[dict[str, Any]] = []
    previous = float(execution.iloc[0])
    for i in range(1, len(execution)):
        current = float(execution.iloc[i])
        if current == previous:
            continue
        delta = current - previous
        rows.append(
            {
                "timestamp_ns": int(frame.index[i].value) + int(quote_offset_ns),
                "side": "BUY" if delta > 0 else "SELL",
                "quantity": abs(delta),
                "price": float(frame["open"].iloc[i]),
                "resulting_target": current,
            }
        )
        previous = current
    return rows


def _realized_from_fills(fills: list[dict[str, Any]]) -> float:
    target = 0.0
    entry_price: float | None = None
    realized = 0.0
    for row in fills:
        signed_delta = float(row["quantity"]) * (1.0 if row["side"] == "BUY" else -1.0)
        new_target = target + signed_delta
        px = float(row["price"])
        if target != 0.0 and np.sign(new_target) != np.sign(target):
            realized += target * (px - float(entry_price))
            entry_price = px if new_target != 0.0 else None
        elif target != 0.0 and new_target == 0.0:
            realized += target * (px - float(entry_price))
            entry_price = None
        elif target == 0.0 and new_target != 0.0:
            entry_price = px
        target = new_target
    return float(realized)


def _normalize_actual_fills(report: pd.DataFrame) -> list[dict[str, Any]]:
    if report.empty:
        return []
    rows: list[dict[str, Any]] = []
    for _, row in report.reset_index().iterrows():
        ts = pd.Timestamp(row["ts_event"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        rows.append(
            {
                "timestamp_ns": int(ts.value),
                "side": str(row["order_side"]),
                "quantity": float(row["last_qty"]),
                "price": float(row["last_px"]),
            }
        )
    rows.sort(key=lambda x: x["timestamp_ns"])
    return rows


def _compare(expected: list[dict[str, Any]], actual: list[dict[str, Any]], price_tolerance: float, ts_tolerance_ns: int) -> dict[str, Any]:
    details: list[dict[str, Any]] = []
    count_match = len(expected) == len(actual)
    passed = count_match
    for i in range(max(len(expected), len(actual))):
        e = expected[i] if i < len(expected) else None
        a = actual[i] if i < len(actual) else None
        if e is None or a is None:
            details.append({"index": i, "expected": e, "actual": a, "pass": False})
            passed = False
            continue
        side_match = e["side"] == a["side"]
        qty_match = abs(float(e["quantity"]) - float(a["quantity"])) <= 1e-12
        price_match = abs(float(e["price"]) - float(a["price"])) <= price_tolerance
        ts_match = abs(int(e["timestamp_ns"]) - int(a["timestamp_ns"])) <= ts_tolerance_ns
        row_pass = side_match and qty_match and price_match and ts_match
        passed = passed and row_pass
        details.append(
            {
                "index": i,
                "expected": e,
                "actual": a,
                "side_match": side_match,
                "quantity_match": qty_match,
                "price_match": price_match,
                "timestamp_match": ts_match,
                "pass": row_pass,
            }
        )
    return {"pass": passed, "fill_count_match": count_match, "details": details}


def _run_symbol(symbol: str, frame: pd.DataFrame, targets: pd.DataFrame, protocol: dict[str, Any]) -> dict[str, Any]:
    venue = Venue("MEXC")
    fixture = protocol["nautilus_execution_fixture"]
    strat = protocol["strategy"]
    gate = protocol["parity_gate"]
    instrument = _instrument(symbol, frame, venue)
    bars, quotes, bar_type = _build_market_data(
        frame,
        instrument,
        int(protocol["data"]["interval_hours"]),
        int(fixture["next_open_quote_offset_nanos"]),
    )

    engine = BacktestEngine(
        config=BacktestEngineConfig(
            logging=LoggerConfig(stdout_level=LogLevel.ERROR),
            risk_engine=RiskEngineConfig(bypass=True),
        )
    )
    quote = instrument.quote_currency
    engine.add_venue(
        venue=venue,
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        starting_balances=[Money(10_000_000, quote)],
        base_currency=quote,
        default_leverage=Decimal(1),
        latency_model=StaticLatencyModel(base_latency_nanos=int(fixture["signal_to_exchange_latency_nanos"])),
        bar_execution=bool(fixture["bar_execution"]),
    )
    engine.add_instrument(instrument)
    engine.add_data(bars)
    engine.add_data(quotes)
    strategy = FrozenTrendExecutionStrategy(
        FrozenTrendExecutionConfig(
            instrument_id=instrument.id,
            bar_type=bar_type,
            trade_size=Decimal(int(strat["target_units"])),
            fast_ema=int(strat["fast_ema"]),
            slow_ema=int(strat["slow_ema"]),
            atr_period=int(strat["atr_period"]),
            threshold=float(strat["min_atr_spread"]),
        )
    )
    engine.add_strategy(strategy)
    engine.run()
    fills_report = engine.generate_fills_report()
    actual = _normalize_actual_fills(fills_report)
    expected = _expected_fills(frame, targets, int(fixture["next_open_quote_offset_nanos"]))
    comparison = _compare(
        expected,
        actual,
        float(gate["fill_price_absolute_tolerance"]),
        int(gate["fill_timestamp_tolerance_nanos"]),
    )
    expected_realized = _realized_from_fills(expected)
    actual_realized = _realized_from_fills(actual)
    realized_match = abs(expected_realized - actual_realized) <= float(gate["gross_realized_pnl_absolute_tolerance_quote"])
    expected_final = float(targets["reference_execution_target"].iloc[-1])
    actual_final = 0.0
    if actual:
        for fill in actual:
            actual_final += float(fill["quantity"]) * (1.0 if fill["side"] == "BUY" else -1.0)
    final_match = abs(expected_final - actual_final) <= 1e-12
    passed = bool(comparison["pass"] and realized_match and final_match)
    result = {
        "symbol": symbol,
        "instrument_id": instrument.id.value,
        "expected_fill_count": len(expected),
        "actual_fill_count": len(actual),
        "expected_final_target": expected_final,
        "actual_final_target": actual_final,
        "final_net_target_match": final_match,
        "expected_gross_realized_pnl_quote": expected_realized,
        "actual_gross_realized_pnl_quote": actual_realized,
        "gross_realized_pnl_match": realized_match,
        "fill_comparison": comparison,
        "pass": passed,
    }
    engine.dispose()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    protocol = json.loads(Path(args.config).read_text(encoding="utf-8"))
    data_dir = Path(args.data_dir)
    results: dict[str, Any] = {}
    for symbol in protocol["data"]["symbols"]:
        frame = pd.read_csv(data_dir / f"{symbol}_{protocol['data']['interval']}.csv", index_col=0, parse_dates=True)
        frame.index = pd.to_datetime(frame.index, utc=True)
        targets = pd.read_csv(data_dir / f"{symbol}_{protocol['data']['interval']}_targets.csv", index_col=0, parse_dates=True)
        targets.index = pd.to_datetime(targets.index, utc=True)
        results[symbol] = _run_symbol(symbol, frame, targets, protocol)

    passed = all(bool(row["pass"]) for row in results.values())
    import nautilus_trader
    report = {
        "schema_version": 1,
        "protocol_name": protocol["protocol_name"],
        "candidate_id": protocol["candidate_id"],
        "nautilus_version": getattr(nautilus_trader, "__version__", "unknown"),
        "status": "event_driven_execution_parity_pass" if passed else "event_driven_execution_parity_fail",
        "event_driven_execution_parity_pass": passed,
        "symbols": results,
        "claims": {
            "execution_fixture_is_market_realism": False,
            "execution_calibration_is_strategy_edge_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "nautilus_version": report["nautilus_version"],
        "symbols": {symbol: {
            "pass": row["pass"],
            "expected_fills": row["expected_fill_count"],
            "actual_fills": row["actual_fill_count"],
            "pnl_match": row["gross_realized_pnl_match"],
            "final_target_match": row["final_net_target_match"],
        } for symbol, row in results.items()},
    }, indent=2))
    if not passed:
        raise SystemExit(4)


if __name__ == "__main__":
    main()
