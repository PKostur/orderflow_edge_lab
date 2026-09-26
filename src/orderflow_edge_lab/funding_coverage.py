from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.cross_sectional_forward_shadow import verify_candidate_spec
from orderflow_edge_lab.cross_sectional_momentum import build_signal_weights


class FundingCoverageError(ValueError):
    pass


def _utc_index(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise FundingCoverageError(f"{symbol}: index must be DatetimeIndex")
    out = frame.copy().sort_index()
    out.index = pd.to_datetime(out.index, utc=True)
    if out.index.has_duplicates:
        raise FundingCoverageError(f"{symbol}: duplicate timestamps")
    return out


def _shared_calendar(
    frames: Mapping[str, pd.DataFrame],
    symbols: list[str],
    *,
    start: str,
    end: str,
) -> pd.DatetimeIndex:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    start_ts = start_ts.tz_localize("UTC") if start_ts.tzinfo is None else start_ts.tz_convert("UTC")
    end_ts = end_ts.tz_localize("UTC") if end_ts.tzinfo is None else end_ts.tz_convert("UTC")
    common: pd.DatetimeIndex | None = None
    for symbol in symbols:
        if symbol not in frames:
            raise FundingCoverageError(f"missing price frame for {symbol}")
        frame = _utc_index(frames[symbol], symbol)
        if "close" not in frame.columns:
            raise FundingCoverageError(f"{symbol}: close column required")
        idx = frame.index[(frame.index >= start_ts) & (frame.index < end_ts)]
        common = idx if common is None else common.intersection(idx)
    if common is None or len(common) < 200:
        raise FundingCoverageError(
            f"insufficient shared price calendar: {0 if common is None else len(common)}"
        )
    return common.sort_values()


def build_funding_coverage_report(
    candidate: Mapping[str, Any],
    price_frames: Mapping[str, pd.DataFrame],
    funding_frames: Mapping[str, pd.DataFrame],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    if not verify_candidate_spec(candidate):
        raise FundingCoverageError("candidate specification hash invalid")

    spec = candidate["specification"]
    symbols = [str(value) for value in spec["symbols"]]
    if symbols != [str(value) for value in config["symbols"]]:
        raise FundingCoverageError("audit symbol universe mismatch")

    common = _shared_calendar(
        price_frames,
        symbols,
        start=str(config["window"]["start"]),
        end=str(config["window"]["end_exclusive"]),
    )
    close_frame = pd.DataFrame(
        {
            symbol: pd.to_numeric(
                _utc_index(price_frames[symbol], symbol).loc[common, "close"],
                errors="coerce",
            )
            for symbol in symbols
        },
        index=common,
    )
    if close_frame.isna().any().any() or (close_frame <= 0.0).any().any():
        raise FundingCoverageError("shared close frame contains invalid values")

    signal = build_signal_weights(
        close_frame,
        lookback_days=int(spec["lookback_days"]),
        holding_days=int(spec["holding_days"]),
        quantile_fraction=float(spec["quantile_fraction"]),
        variant=str(spec["variant"]),
    )
    executed = signal.shift(1).fillna(0.0)

    normalized_funding: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        frame = funding_frames.get(symbol)
        if frame is None:
            normalized_funding[symbol] = pd.DataFrame(
                columns=["funding_rate"],
                index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
            )
            continue
        clean = _utc_index(frame, symbol)
        if "funding_rate" not in clean.columns:
            raise FundingCoverageError(f"{symbol}: funding_rate column required")
        clean["funding_rate"] = pd.to_numeric(clean["funding_rate"], errors="coerce")
        normalized_funding[symbol] = clean.loc[
            np.isfinite(clean["funding_rate"].to_numpy(dtype=float))
        ].copy()

    total_required = 0
    total_covered = 0
    missing: list[dict[str, Any]] = []
    per_symbol: dict[str, dict[str, Any]] = {}

    for symbol in symbols:
        frame = normalized_funding[symbol]
        per_symbol[symbol] = {
            "required_held_intervals": 0,
            "covered_held_intervals": 0,
            "coverage_fraction": None,
            "first_realized_funding": (
                frame.index.min().isoformat() if not frame.empty else None
            ),
            "last_realized_funding": (
                frame.index.max().isoformat() if not frame.empty else None
            ),
        }

    for i in range(len(executed.index) - 1):
        start = executed.index[i]
        end = executed.index[i + 1]
        row = executed.iloc[i]
        for symbol in symbols:
            weight = float(row[symbol])
            if abs(weight) <= 1e-15:
                continue
            total_required += 1
            per_symbol[symbol]["required_held_intervals"] += 1
            funding = normalized_funding[symbol]
            mask = (funding.index > start) & (funding.index < end)
            observation_count = int(mask.sum())
            if observation_count > 0:
                total_covered += 1
                per_symbol[symbol]["covered_held_intervals"] += 1
            else:
                missing.append(
                    {
                        "symbol": symbol,
                        "interval_start": start.isoformat(),
                        "interval_end": end.isoformat(),
                        "executed_weight": weight,
                    }
                )

    for symbol in symbols:
        required = int(per_symbol[symbol]["required_held_intervals"])
        covered = int(per_symbol[symbol]["covered_held_intervals"])
        per_symbol[symbol]["coverage_fraction"] = (
            float(covered / required) if required else None
        )

    coverage_fraction = (
        float(total_covered / total_required) if total_required else None
    )
    complete = bool(total_required > 0 and total_covered == total_required)

    return {
        "schema_version": 1,
        "analysis": "cross_sectional_funding_coverage_audit_v1",
        "audit_id": str(config["audit_id"]),
        "candidate_id": candidate["candidate_id"],
        "candidate_spec_sha256": candidate["spec_sha256"],
        "source": str(config["source"]),
        "window": dict(config["window"]),
        "shared_price_start": common.min().isoformat(),
        "shared_price_end": common.max().isoformat(),
        "shared_price_observations": len(common),
        "coverage_policy": {
            "scope": "nonzero_executed_weight_symbol_day_intervals",
            "interval_rule": "at_least_one_finite_realized_funding_observation_strictly_inside_each_held_interval",
            "missing_funding_is_zero_fill_admissible": False,
            "required_coverage_fraction_for_complete_economics": 1.0,
        },
        "required_held_intervals": total_required,
        "covered_held_intervals": total_covered,
        "missing_held_intervals": total_required - total_covered,
        "coverage_fraction": coverage_fraction,
        "per_symbol": per_symbol,
        "missing_interval_examples": missing[:100],
        "funding_economics_admissible": complete,
        "status": (
            "FUNDING_COVERAGE_COMPLETE"
            if complete
            else "FUNDING_COVERAGE_INCOMPLETE"
        ),
        "evidence_use": "data_quality_only",
        "claims": {
            "strategy_definition_changed": False,
            "candidate_retested": False,
            "historical_economic_result_repaired": False,
            "candidate_promoted": False,
            "profitable_edge_established": False,
            "live_trading_authorized": False,
            "leverage_authorized": False,
        },
    }
