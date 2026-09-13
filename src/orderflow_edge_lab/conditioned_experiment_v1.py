from __future__ import annotations

from bisect import bisect_right
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from orderflow_edge_lab.direction_pair import _summarize as _direction_summarize
from orderflow_edge_lab.market_state_scan import MarketStateScanError
from orderflow_edge_lab.orderflow_backtest import (
    BacktestConfig,
    _first_quote_at_or_after,
    _load,
    _quote_rows,
    candidate_signals,
)
from orderflow_edge_lab.stop_risk import StopRiskConfig, _simulate_sequence
from orderflow_edge_lab.strategy_state_mapping_v1 import verify_strategy_state_mapping_v1


class ConditionedExperimentV1Error(ValueError):
    pass


def _load_object(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConditionedExperimentV1Error(f"cannot read JSON object: {source}") from exc
    if not isinstance(value, dict):
        raise ConditionedExperimentV1Error(f"JSON must be an object: {source}")
    return value


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _profit_factor(values: Sequence[float]) -> float | str | None:
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    if losses > 0:
        return gains / losses
    if gains > 0:
        return "INF"
    return None


def _summary(observations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int, float], list[Mapping[str, Any]]] = {}
    for row in observations:
        groups.setdefault(
            (str(row["family"]), int(row["horizon_ms"]), float(row["fee_bps_round_trip"])),
            [],
        ).append(row)
    out: list[dict[str, Any]] = []
    for (family, horizon, fee), group in sorted(groups.items()):
        nets = [float(row["net_bps"]) for row in group]
        gross = [float(row["gross_bps"]) for row in group]
        out.append(
            {
                "family": family,
                "horizon_ms": horizon,
                "fee_bps_round_trip": fee,
                "observations": len(group),
                "gross_mean_bps": sum(gross) / len(gross),
                "net_expectancy_bps": sum(nets) / len(nets),
                "net_profit_factor": _profit_factor(nets),
                "net_win_rate": sum(value > 0 for value in nets) / len(nets),
                "net_total_bps": sum(nets),
            }
        )
    return out


def _evaluate_signals(signals: Sequence[Mapping[str, Any]], quotes: list[tuple[int, float, float, int | None]], cfg: BacktestConfig) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for signal in signals:
        for horizon in cfg.horizons_ms:
            target_ns = int(signal["signal_observed_at_ns"]) + horizon * 1_000_000
            quote = _first_quote_at_or_after(quotes, target_ns)
            if quote is None:
                continue
            exit_ns, bid, ask, exit_exchange_ts = quote
            side = int(signal["side"])
            exit_price = bid if side > 0 else ask
            gross = side * (exit_price / float(signal["entry_price"]) - 1.0) * 10_000.0
            base = {
                **dict(signal),
                "horizon_ms": horizon,
                "exit_observed_at_ns": exit_ns,
                "exit_exchange_ts_ms": exit_exchange_ts,
                "exit_price": exit_price,
                "gross_bps": gross,
            }
            for fee in cfg.fee_bps_round_trip:
                observations.append({**base, "fee_bps_round_trip": fee, "net_bps": gross - fee})
    return observations


def _reversed_observations(original: Sequence[Mapping[str, Any]], quotes: list[tuple[int, float, float, int | None]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for observation in original:
        signal_side = int(observation["side"])
        trade_side = -signal_side
        target_ns = int(observation["signal_observed_at_ns"]) + int(observation["horizon_ms"]) * 1_000_000
        quote = _first_quote_at_or_after(quotes, target_ns)
        if quote is None:
            raise ConditionedExperimentV1Error("paired reversed stream lost an exit quote present in original stream")
        exit_ns, bid, ask, exit_exchange_ts = quote
        entry_price = float(observation["signal_ask"]) if trade_side > 0 else float(observation["signal_bid"])
        exit_price = bid if trade_side > 0 else ask
        gross = trade_side * (exit_price / entry_price - 1.0) * 10_000.0
        fee = float(observation["fee_bps_round_trip"])
        out.append(
            {
                **dict(observation),
                "stream": "reversed",
                "signal_side": signal_side,
                "side": trade_side,
                "entry_price": entry_price,
                "exit_observed_at_ns": exit_ns,
                "exit_exchange_ts_ms": exit_exchange_ts,
                "exit_price": exit_price,
                "gross_bps": gross,
                "net_bps": gross - fee,
            }
        )
    return out


def _state_gate(mapping: Mapping[str, Any], market_state: Mapping[str, Any]):
    hypothesis = mapping.get("state_hypothesis")
    state_mapping = mapping.get("strategy_state_mapping")
    if not isinstance(hypothesis, Mapping) or not isinstance(state_mapping, Mapping):
        raise ConditionedExperimentV1Error("frozen mapping is incomplete")
    feature = str(hypothesis.get("feature") or "")
    raw_bucket = str(state_mapping.get("selected_raw_feature_bucket") or "")
    thresholds = state_mapping.get("feature_thresholds")
    if raw_bucket not in {"lower", "middle", "upper"} or not isinstance(thresholds, Mapping):
        raise ConditionedExperimentV1Error("frozen mapping lacks a valid raw bucket")
    lower = float(thresholds["lower"])
    upper = float(thresholds["upper"])
    if not math.isfinite(lower) or not math.isfinite(upper) or lower > upper:
        raise ConditionedExperimentV1Error("invalid frozen state thresholds")

    observations = market_state.get("observations")
    sampling = market_state.get("sampling")
    if not isinstance(observations, list) or not observations or not isinstance(sampling, Mapping):
        raise ConditionedExperimentV1Error("market-state report has no usable observations")
    sample_seconds = int(sampling.get("sample_seconds") or 0)
    if sample_seconds <= 0:
        raise ConditionedExperimentV1Error("market-state sampling interval is invalid")
    ordered = sorted(
        (row for row in observations if isinstance(row, Mapping) and isinstance(row.get("observed_at_ns"), int)),
        key=lambda row: int(row["observed_at_ns"]),
    )
    times = [int(row["observed_at_ns"]) for row in ordered]
    max_staleness_ns = sample_seconds * 1_000_000_000

    def qualifies(signal: Mapping[str, Any]) -> bool:
        signal_ns = int(signal["signal_observed_at_ns"])
        index = bisect_right(times, signal_ns) - 1
        if index < 0 or signal_ns - times[index] > max_staleness_ns:
            return False
        features = ordered[index].get("features")
        if not isinstance(features, Mapping):
            return False
        try:
            value = float(features.get(feature))
        except (TypeError, ValueError):
            return False
        if not math.isfinite(value):
            return False
        if raw_bucket == "lower":
            return value <= lower
        if raw_bucket == "middle":
            return lower < value < upper
        return value >= upper

    return qualifies, {
        "feature": feature,
        "raw_bucket": raw_bucket,
        "lower": lower,
        "upper": upper,
        "max_state_staleness_seconds": sample_seconds,
    }


def _risk_arm(signals, quotes, *, cfg: BacktestConfig, risk_cfg: StopRiskConfig) -> dict[str, Any]:
    quote_times = [int(row[0]) for row in quotes]
    families = sorted({str(signal["family"]) for signal in signals})
    summaries: list[dict[str, Any]] = []
    for stream in ("original", "reversed"):
        for family in families:
            for rr in risk_cfg.rr_targets:
                for risk_fraction in risk_cfg.risk_fractions:
                    for fee_bps in risk_cfg.fee_bps_round_trip:
                        summary, _ = _simulate_sequence(
                            signals,
                            quotes,
                            quote_times,
                            stream=stream,
                            family=family,
                            rr=float(rr),
                            risk_fraction=float(risk_fraction),
                            fee_bps=float(fee_bps),
                            cfg=risk_cfg,
                        )
                        summaries.append(summary)
    return {"families": families, "summary": summaries}


def run_conditioned_experiment_v1(
    features_path: str | Path,
    market_state_path: str | Path,
    state_mapping_path: str | Path,
    *,
    backtest_cfg: BacktestConfig = BacktestConfig(),
    risk_cfg: StopRiskConfig = StopRiskConfig(),
) -> dict[str, Any]:
    mapping = _load_object(state_mapping_path)
    if not verify_strategy_state_mapping_v1(mapping):
        raise ConditionedExperimentV1Error("strategy-state mapping verification failed")
    if mapping.get("status") != "frozen" or mapping.get("claims", {}).get("conditioned_pnl_may_run") is not True:
        payload = {
            "schema_version": 1,
            "experiment": "strategy_conditioned_experiment_v1",
            "status": "waiting_for_frozen_strategy_state_mapping",
            "mapping_status": mapping.get("status"),
            "pnl_inspected": False,
            "claims": {
                "research_only": True,
                "verified_out_of_sample_evidence": False,
                "profitable_edge_established": False,
                "live_order_transmission_supported": False,
            },
        }
        payload["manifest_sha256"] = _canonical_sha256(payload)
        return payload

    market_state = _load_object(market_state_path)
    if market_state.get("experiment") != "regime_research_v1_market_state_scan":
        raise ConditionedExperimentV1Error("unexpected market-state report")
    qualifies, gate = _state_gate(mapping, market_state)

    rows = _load(features_path)
    signals = candidate_signals(rows, backtest_cfg)
    conditioned_signals = [signal for signal in signals if qualifies(signal)]
    quotes = _quote_rows(rows, backtest_cfg.symbol)

    baseline_obs = _evaluate_signals(signals, quotes, backtest_cfg)
    conditioned_obs = _evaluate_signals(conditioned_signals, quotes, backtest_cfg)
    baseline_reversed = _reversed_observations(baseline_obs, quotes)
    conditioned_reversed = _reversed_observations(conditioned_obs, quotes)

    payload = {
        "schema_version": 1,
        "experiment": "strategy_conditioned_experiment_v1",
        "status": "evaluated_research_only",
        "source_sha256": hashlib.sha256(Path(features_path).read_bytes()).hexdigest(),
        "market_state_file_sha256": hashlib.sha256(Path(market_state_path).read_bytes()).hexdigest(),
        "strategy_state_mapping_file_sha256": hashlib.sha256(Path(state_mapping_path).read_bytes()).hexdigest(),
        "strategy_state_mapping_manifest_sha256": mapping.get("manifest_sha256"),
        "batch_id": market_state.get("batch_id"),
        "state_gate": gate,
        "signal_counts": {
            "baseline": len(signals),
            "conditioned": len(conditioned_signals),
            "conditioned_fraction": len(conditioned_signals) / len(signals) if signals else None,
        },
        "baseline": {
            "summary": _summary(baseline_obs),
        },
        "conditioned": {
            "summary": _summary(conditioned_obs),
        },
        "original_vs_reversed_control": {
            "baseline_original": _direction_summarize([dict(row, stream="original", signal_side=int(row["side"])) for row in baseline_obs]),
            "baseline_reversed": _direction_summarize(baseline_reversed),
            "conditioned_original": _direction_summarize([dict(row, stream="original", signal_side=int(row["side"])) for row in conditioned_obs]),
            "conditioned_reversed": _direction_summarize(conditioned_reversed),
        },
        "mae_mfe_stop_risk_comparison": {
            "baseline": _risk_arm(signals, quotes, cfg=backtest_cfg, risk_cfg=risk_cfg),
            "conditioned": _risk_arm(conditioned_signals, quotes, cfg=backtest_cfg, risk_cfg=risk_cfg),
        },
        "economics": {
            "spread_execution": "long entry ask/exit bid; short entry bid/exit ask",
            "fee_bps_round_trip": list(backtest_cfg.fee_bps_round_trip),
            "causal_clock": "received_at_ns",
            "state_staleness_max_seconds": gate["max_state_staleness_seconds"],
            "additional_slippage_model": None,
            "additional_latency_model": None,
            "note": "Baseline and conditioned arms use identical frozen discovery-v1 execution assumptions. No unmodeled slippage or latency benefit is credited to the conditioned arm.",
        },
        "limitations": {
            "single_capture_batch_is_not_independent_inference": True,
            "state_selection_and_thresholds_are_market_state_based_not_strategy_pnl_based": True,
            "additional_market_impact_modeled": False,
            "funding_modeled": False,
        },
        "claims": {
            "research_only": True,
            "pnl_inspected_after_frozen_mapping": True,
            "state_selected_from_strategy_pnl": False,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }
    payload["manifest_sha256"] = _canonical_sha256(payload)
    return payload


def verify_conditioned_experiment_v1(payload: Mapping[str, Any]) -> bool:
    if payload.get("experiment") != "strategy_conditioned_experiment_v1":
        return False
    expected = payload.get("manifest_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    unsigned = dict(payload)
    unsigned.pop("manifest_sha256", None)
    return _canonical_sha256(unsigned) == expected
