from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class RiskLadderError(ValueError):
    pass


DEFAULT_EXPOSURE_MULTIPLES = (1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 50.0, 75.0, 100.0)
DEFAULT_FEES_BPS = (4.0, 8.0)


def _load_pair(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("experiment") != "paired_original_vs_reversed_execution":
        raise RiskLadderError("input is not a paired original/reversed direction report")
    streams = payload.get("streams")
    if not isinstance(streams, dict) or set(streams) != {"original", "reversed"}:
        raise RiskLadderError("paired report must contain original and reversed streams")
    return payload


def _non_overlapping(observations: list[dict[str, Any]], *, family: str, horizon_ms: int, fee_bps: float) -> list[dict[str, Any]]:
    rows = [
        row for row in observations
        if str(row["family"]) == family
        and int(row["horizon_ms"]) == horizon_ms
        and float(row["fee_bps_round_trip"]) == fee_bps
    ]
    rows.sort(key=lambda row: (int(row["signal_observed_at_ns"]), int(row["exit_observed_at_ns"])))
    selected: list[dict[str, Any]] = []
    last_exit = -1
    for row in rows:
        signal_ns = int(row["signal_observed_at_ns"])
        if signal_ns < last_exit:
            continue
        selected.append(row)
        last_exit = int(row["exit_observed_at_ns"])
    return selected


def _equity_path(rows: list[dict[str, Any]], *, exposure_multiple: float, starting_equity: float) -> dict[str, Any]:
    equity = starting_equity
    peak = starting_equity
    max_drawdown = 0.0
    ruined = False
    trade_returns_pct: list[float] = []
    for row in rows:
        trade_return = exposure_multiple * float(row["net_bps"]) / 10_000.0
        trade_returns_pct.append(trade_return * 100.0)
        if 1.0 + trade_return <= 0.0:
            equity = 0.0
            max_drawdown = 1.0
            ruined = True
            break
        equity *= 1.0 + trade_return
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return {
        "trades": len(rows),
        "ending_equity": equity,
        "return_pct": (equity / starting_equity - 1.0) * 100.0,
        "max_realized_drawdown_pct": max_drawdown * 100.0,
        "ruined_on_close_to_close_path": ruined,
        "min_trade_return_on_equity_pct": min(trade_returns_pct) if trade_returns_pct else None,
        "max_trade_return_on_equity_pct": max(trade_returns_pct) if trade_returns_pct else None,
    }


def evaluate_risk_ladder(
    paired_report: str | Path,
    *,
    exposure_multiples: tuple[float, ...] = DEFAULT_EXPOSURE_MULTIPLES,
    fee_bps_cases: tuple[float, ...] = DEFAULT_FEES_BPS,
    starting_equity: float = 100.0,
) -> dict[str, Any]:
    if starting_equity <= 0:
        raise RiskLadderError("starting_equity must be positive")
    if not exposure_multiples or any(value <= 0 for value in exposure_multiples):
        raise RiskLadderError("exposure multiples must all be positive")
    if not fee_bps_cases or any(value < 0 for value in fee_bps_cases):
        raise RiskLadderError("fee cases must all be non-negative")

    payload = _load_pair(paired_report)
    results: list[dict[str, Any]] = []
    for stream_name in ("original", "reversed"):
        observations = payload["streams"][stream_name]["observations"]
        families = sorted({str(row["family"]) for row in observations})
        horizons = sorted({int(row["horizon_ms"]) for row in observations})
        available_fees = {float(row["fee_bps_round_trip"]) for row in observations}
        for fee_bps in fee_bps_cases:
            if fee_bps not in available_fees:
                raise RiskLadderError(f"fee case {fee_bps} bps is absent from paired report")
            for family in families:
                for horizon_ms in horizons:
                    rows = _non_overlapping(observations, family=family, horizon_ms=horizon_ms, fee_bps=fee_bps)
                    if not rows:
                        continue
                    raw_count = sum(
                        1 for row in observations
                        if str(row["family"]) == family
                        and int(row["horizon_ms"]) == horizon_ms
                        and float(row["fee_bps_round_trip"]) == fee_bps
                    )
                    for exposure_multiple in exposure_multiples:
                        path = _equity_path(rows, exposure_multiple=float(exposure_multiple), starting_equity=starting_equity)
                        results.append({
                            "stream": stream_name,
                            "family": family,
                            "horizon_ms": horizon_ms,
                            "fee_bps_round_trip": fee_bps,
                            "exposure_multiple": float(exposure_multiple),
                            "raw_observations": raw_count,
                            "overlap_filtered_observations": len(rows),
                            **path,
                        })

    return {
        "schema_version": 1,
        "experiment": "incremental_exposure_stress_test",
        "source_direction_pair_sha256": hashlib.sha256(Path(paired_report).read_bytes()).hexdigest(),
        "source_market_sha256": payload.get("source_sha256"),
        "starting_equity": starting_equity,
        "exposure_multiples": [float(value) for value in exposure_multiples],
        "fee_bps_cases": [float(value) for value in fee_bps_cases],
        "position_policy": "one_position_at_a_time_within_each_stream_family_horizon; overlapping later signals are skipped",
        "risk_semantics": "effective notional exposure multiple applied to close-to-close net bps; not exact percent-at-risk",
        "limitations": {
            "intratrade_mae_modeled": False,
            "liquidation_price_modeled": False,
            "maintenance_margin_modeled": False,
            "funding_modeled": False,
            "portfolio_cross_family_overlap_modeled": False,
        },
        "results": results,
        "claims": {
            "exploratory_only": True,
            "risk_stress_only": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }
