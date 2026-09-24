from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.cross_sectional_forward_shadow import verify_candidate_spec
from orderflow_edge_lab.cross_sectional_momentum import (
    backtest_cross_sectional_momentum,
    build_signal_weights,
)


class CrossSectionalVenueReplicationError(ValueError):
    pass


def _common_calendar(
    mexc_frames: Mapping[str, pd.DataFrame],
    replication_frames: Mapping[str, pd.DataFrame],
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
    for venue_frames in (mexc_frames, replication_frames):
        for symbol in symbols:
            if symbol not in venue_frames:
                raise CrossSectionalVenueReplicationError(
                    f"missing {symbol} from one venue"
                )
            frame = venue_frames[symbol]
            if not isinstance(frame.index, pd.DatetimeIndex):
                raise CrossSectionalVenueReplicationError(
                    f"{symbol}: index must be DatetimeIndex"
                )
            idx = pd.to_datetime(frame.index, utc=True)
            idx = idx[(idx >= start_ts) & (idx < end_ts)]
            common = idx if common is None else common.intersection(idx)
    if common is None or len(common) < 200:
        raise CrossSectionalVenueReplicationError(
            f"insufficient shared venue calendar: {0 if common is None else len(common)}"
        )
    return common.sort_values()


def _restrict(
    frames: Mapping[str, pd.DataFrame],
    symbols: list[str],
    common: pd.DatetimeIndex,
) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        frame = frames[symbol].copy().sort_index()
        frame.index = pd.to_datetime(frame.index, utc=True)
        out[symbol] = frame.loc[common].copy()
    return out


def _executed_weights(
    frames: Mapping[str, pd.DataFrame],
    symbols: list[str],
    *,
    lookback_days: int,
    holding_days: int,
    quantile_fraction: float,
    variant: str,
) -> pd.DataFrame:
    close_frame = pd.DataFrame(
        {symbol: frames[symbol]["close"].astype(float) for symbol in symbols}
    )
    signal = build_signal_weights(
        close_frame,
        lookback_days=lookback_days,
        holding_days=holding_days,
        quantile_fraction=quantile_fraction,
        variant=variant,
    )
    return signal.shift(1).fillna(0.0)


def _signal_agreement(
    left: pd.DataFrame,
    right: pd.DataFrame,
) -> dict[str, Any]:
    idx = left.index.intersection(right.index)
    columns = list(left.columns)
    left = left.loc[idx, columns]
    right = right.loc[idx, columns]
    active = (left.abs().sum(axis=1) > 1e-12) | (right.abs().sum(axis=1) > 1e-12)
    left = left.loc[active]
    right = right.loc[active]
    if left.empty:
        return {
            "active_daily_observations": 0,
            "exact_weight_agreement_fraction": None,
            "mean_l1_weight_distance": None,
            "nonzero_side_agreement_fraction": None,
            "rebalance_event_agreement_fraction": None,
        }
    exact = np.isclose(left.to_numpy(), right.to_numpy(), atol=1e-12).all(axis=1)
    l1 = (left - right).abs().sum(axis=1).to_numpy(dtype=float)
    union_nonzero = (left.abs() > 1e-12) | (right.abs() > 1e-12)
    side_equal = np.sign(left.to_numpy()) == np.sign(right.to_numpy())
    union_values = union_nonzero.to_numpy()
    side_fraction = (
        float(side_equal[union_values].mean()) if union_values.any() else None
    )

    left_change = left.ne(left.shift(1).fillna(0.0)).any(axis=1)
    right_change = right.ne(right.shift(1).fillna(0.0)).any(axis=1)
    rebalance_union = left_change | right_change
    rebalance_agree = left_change == right_change
    return {
        "active_daily_observations": len(left),
        "exact_weight_agreement_fraction": float(exact.mean()),
        "mean_l1_weight_distance": float(l1.mean()),
        "nonzero_side_agreement_fraction": side_fraction,
        "rebalance_event_agreement_fraction": (
            float(rebalance_agree[rebalance_union].mean())
            if bool(rebalance_union.any())
            else None
        ),
    }


def build_venue_replication_report(
    candidate: Mapping[str, Any],
    mexc_frames: Mapping[str, pd.DataFrame],
    mexc_funding: Mapping[str, pd.DataFrame],
    replication_frames: Mapping[str, pd.DataFrame],
    replication_funding: Mapping[str, pd.DataFrame],
    config: Mapping[str, Any],
    *,
    source_sha256: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if not verify_candidate_spec(candidate):
        raise CrossSectionalVenueReplicationError("candidate specification hash invalid")
    spec = candidate["specification"]
    symbols = [str(v) for v in spec["symbols"]]
    if symbols != [str(v) for v in config["symbols"]]:
        raise CrossSectionalVenueReplicationError("replication symbol universe mismatch")
    common = _common_calendar(
        mexc_frames,
        replication_frames,
        symbols,
        start=str(config["window"]["start"]),
        end=str(config["window"]["end_exclusive"]),
    )
    mexc = _restrict(mexc_frames, symbols, common)
    independent = _restrict(replication_frames, symbols, common)

    kwargs = {
        "lookback_days": int(spec["lookback_days"]),
        "holding_days": int(spec["holding_days"]),
        "quantile_fraction": float(spec["quantile_fraction"]),
        "variant": str(spec["variant"]),
        "round_trip_cost_bps": float(spec["round_trip_cost_bps"]),
        "fold_days": int(config["fold_days"]),
    }
    mexc_result = backtest_cross_sectional_momentum(
        mexc,
        funding_frames=mexc_funding,
        **kwargs,
    )
    independent_result = backtest_cross_sectional_momentum(
        independent,
        funding_frames=replication_funding,
        **kwargs,
    )
    mexc_weights = _executed_weights(mexc, symbols, **{
        key: kwargs[key]
        for key in ("lookback_days", "holding_days", "quantile_fraction", "variant")
    })
    independent_weights = _executed_weights(independent, symbols, **{
        key: kwargs[key]
        for key in ("lookback_days", "holding_days", "quantile_fraction", "variant")
    })
    agreement = _signal_agreement(mexc_weights, independent_weights)

    return {
        "schema_version": 1,
        "analysis": "cross_sectional_independent_venue_replication_v1",
        "candidate_id": candidate["candidate_id"],
        "candidate_spec_sha256": candidate["spec_sha256"],
        "evidence_independence": "D2_independent_venue_same_historical_period",
        "window": dict(config["window"]),
        "shared_daily_observations": len(common),
        "shared_start": common.min().isoformat(),
        "shared_end": common.max().isoformat(),
        "symbols": symbols,
        "economics": {
            "round_trip_cost_bps": float(spec["round_trip_cost_bps"]),
            "mexc_funding": "realized public MEXC funding",
            "independent_venue": str(config["replication_venue"]),
            "independent_venue_funding": str(config["replication_funding_description"]),
        },
        "mexc": mexc_result,
        "independent_venue": independent_result,
        "signal_agreement": agreement,
        "source_sha256": dict(source_sha256 or {}),
        "descriptive_differences": {
            "independent_minus_mexc_net_return": float(
                independent_result["net_return"] - mexc_result["net_return"]
            ),
            "independent_minus_mexc_max_drawdown": float(
                independent_result["max_drawdown"] - mexc_result["max_drawdown"]
            ),
            "independent_minus_mexc_funding_return_sum": float(
                independent_result["funding_return_sum"] - mexc_result["funding_return_sum"]
            ),
        },
        "formal_verdict": "DESCRIPTIVE_TRANSFER_ONLY",
        "claims": {
            "strategy_definition_changed": False,
            "same_calendar_enforced": True,
            "same_historical_period_is_future_oos": False,
            "independent_venue_is_independent_engine": False,
            "candidate_promoted": False,
            "profitable_edge_established": False,
            "live_trading_authorized": False,
            "leverage_authorized": False,
        },
    }


def config_sha256(config: Mapping[str, Any]) -> str:
    raw = json.dumps(config, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(raw.encode("utf-8")).hexdigest()
