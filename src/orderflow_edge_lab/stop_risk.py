from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

from orderflow_edge_lab.orderflow_backtest import BacktestConfig, _load, _quote_rows, candidate_signals


class StopRiskError(ValueError):
    pass


@dataclass(frozen=True)
class StopRiskConfig:
    lookback_ms: int = 15_000
    time_stop_ms: int = 30_000
    minimum_spread_multiple: float = 2.0
    rr_targets: tuple[float, ...] = (1.0, 2.0, 3.0)
    risk_fractions: tuple[float, ...] = (0.0025, 0.005, 0.01, 0.015, 0.02, 0.03, 0.05)
    fee_bps_round_trip: tuple[float, ...] = (4.0, 8.0)
    max_exposure_multiple: float = 100.0
    starting_equity: float = 100.0


def _quote_slice(quotes, quote_times, start_ns: int, end_ns: int):
    left = bisect_left(quote_times, start_ns)
    right = bisect_right(quote_times, end_ns)
    return quotes[left:right]


def _first_quote_at_or_after(quotes, quote_times, target_ns: int):
    index = bisect_left(quote_times, target_ns)
    return quotes[index] if index < len(quotes) else None


def _stop_distance(signal, trade_side: int, quotes, quote_times, cfg: StopRiskConfig):
    signal_ns = int(signal["signal_observed_at_ns"])
    prior = _quote_slice(quotes, quote_times, signal_ns - cfg.lookback_ms * 1_000_000, signal_ns)
    if not prior:
        return None
    bid = float(signal["signal_bid"])
    ask = float(signal["signal_ask"])
    spread = ask - bid
    if spread <= 0:
        return None
    entry = ask if trade_side > 0 else bid
    if trade_side > 0:
        structure_distance = entry - min(row[1] for row in prior)
    else:
        structure_distance = max(row[2] for row in prior) - entry
    distance = max(structure_distance, cfg.minimum_spread_multiple * spread)
    return None if distance <= 0 else (entry, distance, spread)


def _trade_path(signal, trade_side: int, rr: float, quotes, quote_times, cfg: StopRiskConfig):
    stop_info = _stop_distance(signal, trade_side, quotes, quote_times, cfg)
    if stop_info is None:
        return None
    entry, distance, spread = stop_info
    signal_ns = int(signal["signal_observed_at_ns"])
    end_ns = signal_ns + cfg.time_stop_ms * 1_000_000
    future = _quote_slice(quotes, quote_times, signal_ns + 1, end_ns)
    if not future:
        return None
    stop = entry - trade_side * distance
    target = entry + trade_side * rr * distance
    mfe_bps = 0.0
    mae_bps = 0.0
    status = "time"
    exit_ns = None
    exit_exchange_ts_ms = None
    exit_price = None
    for observed_ns, bid, ask, exchange_ts_ms in future:
        executable = bid if trade_side > 0 else ask
        move_bps = trade_side * (executable / entry - 1.0) * 10_000.0
        mfe_bps = max(mfe_bps, move_bps)
        mae_bps = max(mae_bps, -move_bps)
        stop_hit = executable <= stop if trade_side > 0 else executable >= stop
        target_hit = executable >= target if trade_side > 0 else executable <= target
        if stop_hit:
            status = "stop"
            exit_ns, exit_exchange_ts_ms, exit_price = observed_ns, exchange_ts_ms, executable
            break
        if target_hit:
            status = "target"
            exit_ns, exit_exchange_ts_ms, exit_price = observed_ns, exchange_ts_ms, executable
            break
    if exit_price is None:
        quote = _first_quote_at_or_after(quotes, quote_times, end_ns)
        if quote is None:
            return None
        exit_ns, bid, ask, exit_exchange_ts_ms = quote
        exit_price = bid if trade_side > 0 else ask
        move_bps = trade_side * (exit_price / entry - 1.0) * 10_000.0
        mfe_bps = max(mfe_bps, move_bps)
        mae_bps = max(mae_bps, -move_bps)
    gross_bps = trade_side * (exit_price / entry - 1.0) * 10_000.0
    return {
        "entry_price": entry,
        "stop_price": stop,
        "target_price": target,
        "stop_distance_bps": distance / entry * 10_000.0,
        "signal_spread_bps": spread / entry * 10_000.0,
        "exit_price": exit_price,
        "exit_observed_at_ns": exit_ns,
        "exit_exchange_ts_ms": exit_exchange_ts_ms,
        "status": status,
        "gross_bps": gross_bps,
        "mfe_bps": mfe_bps,
        "mae_bps": mae_bps,
    }


def _simulate_sequence(signals, quotes, quote_times, *, stream: str, family: str, rr: float, risk_fraction: float, fee_bps: float, cfg: StopRiskConfig):
    equity = cfg.starting_equity
    peak = equity
    max_drawdown = 0.0
    busy_until = -1
    ledger = []
    requested = [row for row in signals if row["family"] == family]
    for signal in requested:
        signal_ns = int(signal["signal_observed_at_ns"])
        if signal_ns < busy_until:
            continue
        signal_side = int(signal["side"])
        trade_side = signal_side if stream == "original" else -signal_side
        path = _trade_path(signal, trade_side, rr, quotes, quote_times, cfg)
        if path is None:
            continue
        stop_and_cost_bps = float(path["stop_distance_bps"]) + fee_bps
        if stop_and_cost_bps <= 0:
            continue
        required_exposure = risk_fraction / (stop_and_cost_bps / 10_000.0)
        exposure = min(required_exposure, cfg.max_exposure_multiple)
        capped = exposure + 1e-12 < required_exposure
        actual_stop_risk_fraction = exposure * stop_and_cost_bps / 10_000.0
        net_asset_return = (float(path["gross_bps"]) - fee_bps) / 10_000.0
        equity_return = exposure * net_asset_return
        equity_before = equity
        equity = max(0.0, equity * (1.0 + equity_return))
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak if peak else 1.0)
        busy_until = int(path["exit_observed_at_ns"])
        ledger.append({
            "stream": stream,
            "family": family,
            "rr_target": rr,
            "requested_risk_fraction": risk_fraction,
            "fee_bps_round_trip": fee_bps,
            "signal_observed_at_ns": signal_ns,
            "signal_side": signal_side,
            "trade_side": trade_side,
            "required_exposure_multiple": required_exposure,
            "exposure_multiple": exposure,
            "exposure_capped": capped,
            "actual_stop_risk_fraction": actual_stop_risk_fraction,
            "equity_before": equity_before,
            "equity_after": equity,
            "equity_return_pct": equity_return * 100.0,
            **path,
        })
        if equity <= 0:
            break
    profits = [row["equity_after"] - row["equity_before"] for row in ledger]
    gains = sum(value for value in profits if value > 0)
    losses = -sum(value for value in profits if value < 0)
    pf = gains / losses if losses else ("INF" if gains else None)
    summary = {
        "stream": stream,
        "family": family,
        "rr_target": rr,
        "requested_risk_fraction": risk_fraction,
        "requested_risk_pct": risk_fraction * 100.0,
        "fee_bps_round_trip": fee_bps,
        "trades": len(ledger),
        "starting_equity": cfg.starting_equity,
        "ending_equity": equity,
        "return_pct": (equity / cfg.starting_equity - 1.0) * 100.0,
        "max_realized_drawdown_pct": max_drawdown * 100.0,
        "profit_factor_on_equity_pnl": pf,
        "target_hits": sum(row["status"] == "target" for row in ledger),
        "stop_hits": sum(row["status"] == "stop" for row in ledger),
        "time_exits": sum(row["status"] == "time" for row in ledger),
        "mean_mae_bps": sum(float(row["mae_bps"]) for row in ledger) / len(ledger) if ledger else None,
        "mean_mfe_bps": sum(float(row["mfe_bps"]) for row in ledger) / len(ledger) if ledger else None,
        "mean_stop_distance_bps": sum(float(row["stop_distance_bps"]) for row in ledger) / len(ledger) if ledger else None,
        "mean_exposure_multiple": sum(float(row["exposure_multiple"]) for row in ledger) / len(ledger) if ledger else None,
        "capped_trades": sum(bool(row["exposure_capped"]) for row in ledger),
        "ruined_on_realized_path": equity <= 0,
    }
    return summary, ledger


def evaluate_stop_risk(feature_path: str | Path, backtest_cfg: BacktestConfig = BacktestConfig(), risk_cfg: StopRiskConfig = StopRiskConfig()) -> dict[str, Any]:
    if risk_cfg.lookback_ms <= 0 or risk_cfg.time_stop_ms <= 0:
        raise StopRiskError("lookback and time stop must be positive")
    if risk_cfg.minimum_spread_multiple <= 0 or risk_cfg.max_exposure_multiple <= 0 or risk_cfg.starting_equity <= 0:
        raise StopRiskError("spread multiple, exposure cap and starting equity must be positive")
    if any(value <= 0 for value in risk_cfg.rr_targets):
        raise StopRiskError("RR targets must be positive")
    if any(not 0 < value < 1 for value in risk_cfg.risk_fractions):
        raise StopRiskError("risk fractions must be between zero and one")
    if any(value < 0 for value in risk_cfg.fee_bps_round_trip):
        raise StopRiskError("fee cases must be non-negative")
    rows = _load(feature_path)
    signals = candidate_signals(rows, backtest_cfg)
    quotes = _quote_rows(rows, backtest_cfg.symbol)
    quote_times = [int(row[0]) for row in quotes]
    families = sorted({str(signal["family"]) for signal in signals})
    summaries = []
    ledger = []
    for stream in ("original", "reversed"):
        for family in families:
            for rr in risk_cfg.rr_targets:
                for risk_fraction in risk_cfg.risk_fractions:
                    for fee_bps in risk_cfg.fee_bps_round_trip:
                        summary, trades = _simulate_sequence(signals, quotes, quote_times, stream=stream, family=family, rr=float(rr), risk_fraction=float(risk_fraction), fee_bps=float(fee_bps), cfg=risk_cfg)
                        summaries.append(summary)
                        ledger.extend(trades)
    return {
        "schema_version": 1,
        "experiment": "stop_based_risk_mae_mfe",
        "source_sha256": hashlib.sha256(Path(feature_path).read_bytes()).hexdigest(),
        "risk_config": {
            "lookback_ms": risk_cfg.lookback_ms,
            "time_stop_ms": risk_cfg.time_stop_ms,
            "minimum_spread_multiple": risk_cfg.minimum_spread_multiple,
            "rr_targets": list(risk_cfg.rr_targets),
            "risk_fractions": list(risk_cfg.risk_fractions),
            "fee_bps_round_trip": list(risk_cfg.fee_bps_round_trip),
            "max_exposure_multiple": risk_cfg.max_exposure_multiple,
            "starting_equity": risk_cfg.starting_equity,
            "sizing_rule": "position exposure = requested equity risk / (technical stop bps + stated round-trip fee bps), capped at max exposure",
            "technical_stop_rule": "causal recent-structure stop over the prior lookback, with a minimum distance of N current spreads",
            "execution_rule": "long exits use bid; short exits use ask; stop/target checked on observed BBO path; unresolved trades use time-stop executable quote",
        },
        "signals": len(signals),
        "families": families,
        "summary": summaries,
        "trades": ledger,
        "limitations": {
            "liquidation_price_modeled": False,
            "maintenance_margin_modeled": False,
            "funding_modeled": False,
            "market_impact_modeled": False,
            "cross_family_portfolio_overlap_modeled": False,
        },
        "claims": {
            "exploratory_only": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }
