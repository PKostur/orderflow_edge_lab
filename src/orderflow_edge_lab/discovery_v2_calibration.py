from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.strategy_tournament import generate_target_position


class DiscoveryV2CalibrationError(ValueError):
    pass


def _validate(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise DiscoveryV2CalibrationError(f"missing columns: {sorted(required - set(frame.columns))}")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise DiscoveryV2CalibrationError("index must be DatetimeIndex")
    out = frame.copy().sort_index()
    out.index = out.index.tz_localize("UTC") if out.index.tz is None else out.index.tz_convert("UTC")
    if out.index.has_duplicates:
        raise DiscoveryV2CalibrationError("duplicate timestamps")
    for column in required:
        out[column] = pd.to_numeric(out[column], errors="raise").astype(float)
        if not np.isfinite(out[column].to_numpy()).all():
            raise DiscoveryV2CalibrationError(f"non-finite {column}")
    if (out[["open", "high", "low", "close"]] <= 0).any().any():
        raise DiscoveryV2CalibrationError("non-positive OHLC")
    return out


def canonical_frame_sha256(frame: pd.DataFrame) -> str:
    clean = _validate(frame)
    payload = clean.reset_index().rename(columns={clean.index.name or "index": "timestamp"})
    payload["timestamp"] = payload["timestamp"].map(lambda x: pd.Timestamp(x).isoformat())
    raw = payload[["timestamp", "open", "high", "low", "close", "volume"]].to_csv(index=False, float_format="%.12g").encode("utf-8")
    return sha256(raw).hexdigest()


def _recursive_ema(values: np.ndarray, span: int) -> np.ndarray:
    if span <= 0:
        raise DiscoveryV2CalibrationError("EMA span must be positive")
    out = np.full(values.size, np.nan, dtype=float)
    if values.size == 0:
        return out
    alpha = 2.0 / (float(span) + 1.0)
    state = float(values[0])
    for i, value in enumerate(values):
        if i > 0:
            state = alpha * float(value) + (1.0 - alpha) * state
        if i + 1 >= span:
            out[i] = state
    return out


def _rolling_sma(values: np.ndarray, period: int) -> np.ndarray:
    if period <= 0:
        raise DiscoveryV2CalibrationError("period must be positive")
    out = np.full(values.size, np.nan, dtype=float)
    if values.size < period:
        return out
    csum = np.cumsum(np.insert(values.astype(float), 0, 0.0))
    out[period - 1 :] = (csum[period:] - csum[:-period]) / float(period)
    return out


def independent_indicator_frame(frame: pd.DataFrame, *, fast: int, slow: int, atr_period: int) -> pd.DataFrame:
    clean = _validate(frame)
    close = clean["close"].to_numpy(dtype=float)
    high = clean["high"].to_numpy(dtype=float)
    low = clean["low"].to_numpy(dtype=float)
    prev_close = np.concatenate(([np.nan], close[:-1]))
    tr = np.empty(close.size, dtype=float)
    for i in range(close.size):
        candidates = [abs(high[i] - low[i])]
        if np.isfinite(prev_close[i]):
            candidates.extend([abs(high[i] - prev_close[i]), abs(low[i] - prev_close[i])])
        tr[i] = max(candidates)
    fast_values = _recursive_ema(close, int(fast))
    slow_values = _recursive_ema(close, int(slow))
    atr_values = _rolling_sma(tr, int(atr_period))
    normalized = np.divide(
        fast_values - slow_values,
        atr_values,
        out=np.full(close.size, np.nan, dtype=float),
        where=np.isfinite(atr_values) & (atr_values != 0.0),
    )
    return pd.DataFrame(
        {
            "fast_ema": fast_values,
            "slow_ema": slow_values,
            "atr": atr_values,
            "normalized_spread": normalized,
        },
        index=clean.index,
    )


def independent_target(frame: pd.DataFrame, *, fast: int, slow: int, atr_period: int, threshold: float) -> pd.Series:
    indicators = independent_indicator_frame(frame, fast=fast, slow=slow, atr_period=atr_period)
    score = indicators["normalized_spread"].to_numpy(dtype=float)
    target = np.where(score > float(threshold), 1.0, np.where(score < -float(threshold), -1.0, 0.0))
    return pd.Series(target, index=indicators.index, name="target", dtype=float)


def reference_target(frame: pd.DataFrame, *, fast: int, slow: int, atr_period: int, threshold: float) -> pd.Series:
    clean = _validate(frame)
    return generate_target_position(
        clean,
        "ema_tsmom",
        {"fast": int(fast), "slow": int(slow), "atr_period": int(atr_period), "min_atr_spread": float(threshold)},
    ).astype(float).rename("target")


def execution_target(raw_target: pd.Series) -> pd.Series:
    return raw_target.shift(1).fillna(0.0).astype(float).rename("execution_target")


def _transition_times(series: pd.Series) -> list[str]:
    values = series.astype(float)
    changed = values.ne(values.shift(1).fillna(0.0))
    return [pd.Timestamp(ts).isoformat() for ts in values.index[changed]]


def compare_symbol(frame: pd.DataFrame, spec: Mapping[str, Any]) -> dict[str, Any]:
    fast = int(spec["fast_ema"])
    slow = int(spec["slow_ema"])
    atr_period = int(spec["atr_period"])
    threshold = float(spec["min_atr_spread"])
    ref = reference_target(frame, fast=fast, slow=slow, atr_period=atr_period, threshold=threshold)
    independent = independent_target(frame, fast=fast, slow=slow, atr_period=atr_period, threshold=threshold)
    if not ref.index.equals(independent.index):
        raise DiscoveryV2CalibrationError("timestamp set/order mismatch")
    ref_exec = execution_target(ref)
    independent_exec = execution_target(independent)
    raw_disagreements = ref.ne(independent)
    exec_disagreements = ref_exec.ne(independent_exec)
    ref_transitions = _transition_times(ref_exec)
    independent_transitions = _transition_times(independent_exec)
    return {
        "bars": int(len(ref)),
        "data_sha256": canonical_frame_sha256(frame),
        "raw_target_disagreements": int(raw_disagreements.sum()),
        "execution_target_disagreements": int(exec_disagreements.sum()),
        "reference_transition_count": len(ref_transitions),
        "independent_transition_count": len(independent_transitions),
        "transition_timestamps_match": ref_transitions == independent_transitions,
        "first_raw_disagreement": pd.Timestamp(ref.index[raw_disagreements.to_numpy().nonzero()[0][0]]).isoformat() if raw_disagreements.any() else None,
        "reference_counts": {str(int(k)): int(v) for k, v in ref.value_counts().sort_index().items()},
        "independent_counts": {str(int(k)): int(v) for k, v in independent.value_counts().sort_index().items()},
    }


def build_calibration_report(frames: Mapping[str, pd.DataFrame], protocol: Mapping[str, Any]) -> dict[str, Any]:
    strategy = protocol["strategy"]
    symbols = [str(x) for x in protocol["data"]["symbols"]]
    missing = [symbol for symbol in symbols if symbol not in frames]
    if missing:
        raise DiscoveryV2CalibrationError(f"missing symbols: {missing}")
    rows = {symbol: compare_symbol(frames[symbol], strategy) for symbol in symbols}
    gate = protocol["parity_gate"]
    passed = all(
        row["raw_target_disagreements"] <= int(gate["raw_target_disagreements_allowed_per_symbol"])
        and row["execution_target_disagreements"] <= int(gate["execution_target_disagreements_allowed_per_symbol"])
        and bool(row["transition_timestamps_match"])
        for row in rows.values()
    )
    return {
        "schema_version": 1,
        "protocol_name": protocol["protocol_name"],
        "candidate_id": protocol["candidate_id"],
        "status": "reference_independent_parity_pass" if passed else "reference_independent_parity_fail",
        "reference_independent_parity_pass": passed,
        "symbols": rows,
        "claims": {
            "calibration_is_strategy_edge_evidence": False,
            "external_engine_replication_complete": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }


def canonical_json_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()
