from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DERIBIT_API = "https://www.deribit.com/api/v2"
YEAR_MS = 365.25 * 24 * 60 * 60 * 1000


class GammaExposureError(ValueError):
    pass


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _iso_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def black_scholes_gamma(spot: float, strike: float, time_years: float, volatility: float, rate: float = 0.0) -> float:
    if spot <= 0 or strike <= 0 or time_years <= 0 or volatility <= 0:
        return 0.0
    root_t = math.sqrt(time_years)
    denom = volatility * root_t
    d1 = (math.log(spot / strike) + (rate + 0.5 * volatility * volatility) * time_years) / denom
    normal_pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    return normal_pdf / (spot * denom)


def _deribit_get(method: str, params: Mapping[str, Any], *, timeout: float = 20.0) -> list[dict[str, Any]]:
    url = f"{DERIBIT_API}/{method}?{urlencode(dict(params))}"
    request = Request(url, headers={"User-Agent": "orderflow-edge-lab-gamma-exposure-v1"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise GammaExposureError(f"Deribit request failed for {method}: {exc}") from exc
    if not isinstance(payload, Mapping) or payload.get("error"):
        raise GammaExposureError(f"Deribit returned an error for {method}: {payload!r}")
    result = payload.get("result")
    if not isinstance(result, list):
        raise GammaExposureError(f"Deribit result for {method} was not a list")
    return [dict(row) for row in result if isinstance(row, Mapping)]


def fetch_deribit_option_inputs(currency: str = "BTC") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    instruments = _deribit_get(
        "public/get_instruments",
        {"currency": currency, "kind": "option", "expired": "false"},
    )
    summaries = _deribit_get(
        "public/get_book_summary_by_currency",
        {"currency": currency, "kind": "option"},
    )
    return instruments, summaries


def _usable_rows(
    instruments: Sequence[Mapping[str, Any]],
    summaries: Sequence[Mapping[str, Any]],
    *,
    observed_at_ms: int,
    minimum_open_interest_btc: float,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    by_name = {str(row.get("instrument_name")): row for row in instruments if row.get("instrument_name")}
    rows: list[dict[str, Any]] = []
    counters = {
        "instrument_catalog_count": len(instruments),
        "summary_count": len(summaries),
        "matched_count": 0,
        "usable_count": 0,
        "excluded_missing_metadata": 0,
        "excluded_invalid_numeric": 0,
        "excluded_expired": 0,
        "excluded_below_minimum_open_interest": 0,
    }
    for summary in summaries:
        name = str(summary.get("instrument_name") or "")
        instrument = by_name.get(name)
        if instrument is None:
            counters["excluded_missing_metadata"] += 1
            continue
        counters["matched_count"] += 1
        strike = _float(instrument.get("strike"))
        expiry_ms = instrument.get("expiration_timestamp")
        contract_size = _float(instrument.get("contract_size"))
        oi = _float(summary.get("open_interest"))
        mark_iv_pct = _float(summary.get("mark_iv"))
        spot = _float(summary.get("underlying_price"))
        rate = _float(summary.get("interest_rate"))
        option_type = str(instrument.get("option_type") or "")
        if (
            strike is None
            or not isinstance(expiry_ms, int)
            or contract_size is None
            or oi is None
            or mark_iv_pct is None
            or spot is None
            or rate is None
            or option_type not in {"call", "put"}
            or strike <= 0
            or contract_size <= 0
            or oi < 0
            or mark_iv_pct <= 0
            or spot <= 0
        ):
            counters["excluded_invalid_numeric"] += 1
            continue
        if expiry_ms <= observed_at_ms:
            counters["excluded_expired"] += 1
            continue
        if oi < minimum_open_interest_btc:
            counters["excluded_below_minimum_open_interest"] += 1
            continue
        time_years = (expiry_ms - observed_at_ms) / YEAR_MS
        volatility = mark_iv_pct / 100.0
        gamma = black_scholes_gamma(spot, strike, time_years, volatility, rate)
        exposure = gamma * oi * contract_size * spot * spot * 0.01
        rows.append(
            {
                "instrument_name": name,
                "option_type": option_type,
                "strike": strike,
                "expiration_timestamp": expiry_ms,
                "contract_size": contract_size,
                "open_interest_btc": oi,
                "mark_iv_pct": mark_iv_pct,
                "underlying_price": spot,
                "interest_rate": rate,
                "time_years": time_years,
                "gamma": gamma,
                "gamma_exposure_usd_per_1pct": exposure,
                "signed_call_minus_put_gex_usd_per_1pct": exposure if option_type == "call" else -exposure,
            }
        )
    counters["usable_count"] = len(rows)
    return rows, counters


def _flip_proxy(rows: Sequence[Mapping[str, Any]], reference_spot: float, definition: Mapping[str, Any]) -> float | None:
    if not rows or not definition.get("enabled", True):
        return None
    lo = float(definition.get("spot_ratio_min", 0.6))
    hi = float(definition.get("spot_ratio_max", 1.4))
    points = int(definition.get("grid_points", 161))
    if lo <= 0 or hi <= lo or points < 3:
        raise GammaExposureError("invalid frozen balance-flip grid")

    def net_at(spot: float) -> float:
        total = 0.0
        for row in rows:
            gamma = black_scholes_gamma(
                spot,
                float(row["strike"]),
                float(row["time_years"]),
                float(row["mark_iv_pct"]) / 100.0,
                float(row["interest_rate"]),
            )
            exposure = gamma * float(row["open_interest_btc"]) * float(row["contract_size"]) * spot * spot * 0.01
            total += exposure if row["option_type"] == "call" else -exposure
        return total

    grid = [reference_spot * (lo + (hi - lo) * i / (points - 1)) for i in range(points)]
    values = [net_at(spot) for spot in grid]
    crossings: list[float] = []
    for i in range(1, len(grid)):
        left_s, right_s = grid[i - 1], grid[i]
        left_v, right_v = values[i - 1], values[i]
        if left_v == 0:
            crossings.append(left_s)
        if left_v * right_v < 0:
            weight = abs(left_v) / (abs(left_v) + abs(right_v))
            crossings.append(left_s + (right_s - left_s) * weight)
    if values and values[-1] == 0:
        crossings.append(grid[-1])
    if not crossings:
        return None
    return min(crossings, key=lambda value: abs(value - reference_spot))


def build_gamma_snapshot(
    instruments: Sequence[Mapping[str, Any]],
    summaries: Sequence[Mapping[str, Any]],
    protocol: Mapping[str, Any],
    *,
    observed_at_ms: int,
) -> dict[str, Any]:
    if protocol.get("protocol_name") != "gamma-exposure-trial-v1":
        raise GammaExposureError("unexpected gamma trial protocol")
    definition = protocol.get("snapshot_definition")
    if not isinstance(definition, Mapping):
        raise GammaExposureError("snapshot_definition missing")
    minimum_oi = float(definition.get("minimum_open_interest_btc", 0.0))
    rows, counters = _usable_rows(
        instruments,
        summaries,
        observed_at_ms=observed_at_ms,
        minimum_open_interest_btc=minimum_oi,
    )
    if not rows:
        raise GammaExposureError("no usable BTC option rows")
    reference_spot = median(float(row["underlying_price"]) for row in rows)
    gross = sum(abs(float(row["gamma_exposure_usd_per_1pct"])) for row in rows)
    call_gex = sum(float(row["gamma_exposure_usd_per_1pct"]) for row in rows if row["option_type"] == "call")
    put_gex = sum(float(row["gamma_exposure_usd_per_1pct"]) for row in rows if row["option_type"] == "put")
    signed = call_gex - put_gex
    sign = "positive" if signed > 0 else "negative" if signed < 0 else "zero"

    strikes: dict[float, dict[str, float]] = {}
    for row in rows:
        strike = float(row["strike"])
        slot = strikes.setdefault(strike, {"call": 0.0, "put": 0.0, "signed": 0.0, "gross": 0.0})
        exposure = float(row["gamma_exposure_usd_per_1pct"])
        slot[str(row["option_type"])] += exposure
        slot["signed"] += exposure if row["option_type"] == "call" else -exposure
        slot["gross"] += abs(exposure)

    strike_rows = [{"strike": strike, **values} for strike, values in strikes.items()]
    top_n = int(definition.get("top_strikes_each_side", 5))
    top_positive = sorted((row for row in strike_rows if row["signed"] > 0), key=lambda r: (-r["signed"], r["strike"]))[:top_n]
    top_negative = sorted((row for row in strike_rows if row["signed"] < 0), key=lambda r: (r["signed"], r["strike"]))[:top_n]
    top_abs = sorted(strike_rows, key=lambda r: (-r["gross"], r["strike"]))[:top_n]
    top_concentration = sum(float(row["gross"]) for row in top_abs) / gross if gross > 0 else None
    major_strike = float(top_abs[0]["strike"]) if top_abs else None
    major_distance = abs(major_strike / reference_spot - 1.0) * 100.0 if major_strike else None
    flip = _flip_proxy(rows, reference_spot, definition.get("balance_flip_proxy", {}))
    flip_distance = (reference_spot / flip - 1.0) * 100.0 if flip and flip > 0 else None

    input_manifest = {
        "instruments": sorted(
            (str(row.get("instrument_name")), row.get("strike"), row.get("option_type"), row.get("expiration_timestamp"), row.get("contract_size"))
            for row in instruments
            if row.get("instrument_name")
        ),
        "summaries": sorted(
            (str(row.get("instrument_name")), row.get("open_interest"), row.get("mark_iv"), row.get("underlying_price"), row.get("interest_rate"))
            for row in summaries
            if row.get("instrument_name")
        ),
    }
    snapshot = {
        "schema_version": 1,
        "trial": "gamma-exposure-trial-v1",
        "status": "forward_snapshot",
        "observed_at_ms": observed_at_ms,
        "observed_at_utc": _iso_from_ms(observed_at_ms),
        "protocol_sha256": _canonical_sha256(protocol),
        "source_input_sha256": _canonical_sha256(input_manifest),
        "source": {
            "venue": "Deribit",
            "currency": "BTC",
            "kind": "option",
            "instruments_endpoint": "public/get_instruments",
            "summary_endpoint": "public/get_book_summary_by_currency"
        },
        "data_integrity": counters,
        "metrics": {
            "reference_spot_usd": reference_spot,
            "gross_gamma_exposure_usd_per_1pct": gross,
            "call_gamma_exposure_usd_per_1pct": call_gex,
            "put_gamma_exposure_usd_per_1pct": put_gex,
            "call_minus_put_gamma_proxy_usd_per_1pct": signed,
            "call_minus_put_to_gross_ratio": signed / gross if gross > 0 else None,
            "call_minus_put_proxy_sign": sign,
            "balance_flip_proxy_usd": flip,
            "spot_distance_to_balance_flip_pct": flip_distance,
            "nearest_major_abs_gamma_strike_usd": major_strike,
            "nearest_major_abs_gamma_strike_distance_pct": major_distance,
            "top5_abs_gamma_concentration": top_concentration
        },
        "levels": {
            "top_positive_signed_strikes": top_positive,
            "top_negative_signed_strikes": top_negative,
            "top_absolute_gamma_strikes": top_abs
        },
        "limitations": {
            "dealer_positioning_observed": False,
            "call_minus_put_sign_is_positioning_proxy": True,
            "historical_open_interest_backfilled": False,
            "balance_flip_is_model_derived_proxy": True,
            "strategy_parameters_changed": False
        },
        "claims": {
            "research_only": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False
        }
    }
    snapshot["manifest_sha256"] = _canonical_sha256(snapshot)
    return snapshot


def verify_gamma_snapshot(payload: Mapping[str, Any]) -> bool:
    expected = payload.get("manifest_sha256")
    if payload.get("trial") != "gamma-exposure-trial-v1" or not isinstance(expected, str) or len(expected) != 64:
        return False
    unsigned = dict(payload)
    unsigned.pop("manifest_sha256", None)
    return _canonical_sha256(unsigned) == expected


def _strategy_state(ena: Mapping[str, Any], trend: Mapping[str, Any], xs: Mapping[str, Any]) -> dict[str, Any]:
    ena_metrics = ena.get("metrics", {})
    ena_open = ena.get("open_position") if isinstance(ena.get("open_position"), Mapping) else None
    ena_pnl = float(ena_metrics.get("compounded_return") or 0.0) * 1000.0
    if ena_open:
        ena_pnl += float(ena_open.get("unrealized_gross_return") or 0.0) * 1000.0
    return {
        "ena_1h": {
            "status": ena.get("status"),
            "completed_outcomes": int(ena_metrics.get("trades") or 0),
            "open_positions": 1 if ena_open else 0,
            "pnl_per_1000_usdt": ena_pnl
        },
        "trend_8h": {
            "status": trend.get("status"),
            "completed_outcomes": int(trend.get("metrics", {}).get("completed_symbol_trades") or 0),
            "open_positions": int(trend.get("metrics", {}).get("open_symbol_positions") or 0),
            "pnl_per_1000_usdt": float(trend.get("metrics", {}).get("net_pnl_per_1000_usdt") or 0.0)
        },
        "cross_sectional_30d_7d": {
            "status": xs.get("status"),
            "completed_outcomes": int(xs.get("metrics", {}).get("completed_holding_periods") or 0),
            "open_positions": int(xs.get("metrics", {}).get("open_symbol_positions") or 0),
            "pnl_per_1000_usdt": float(xs.get("metrics", {}).get("net_pnl_per_1000_usdt") or 0.0)
        }
    }


def append_comparison_history(
    snapshot: Mapping[str, Any],
    ena: Mapping[str, Any],
    trend: Mapping[str, Any],
    xs: Mapping[str, Any],
    protocol: Mapping[str, Any],
    previous_history: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    records = []
    if isinstance(previous_history, Mapping) and isinstance(previous_history.get("records"), list):
        records = [dict(row) for row in previous_history["records"] if isinstance(row, Mapping)]
    state = _strategy_state(ena, trend, xs)
    current = {
        "observed_at_utc": snapshot["observed_at_utc"],
        "gamma": dict(snapshot["metrics"]),
        "strategy": state
    }
    records.append(current)
    records.sort(key=lambda row: str(row.get("observed_at_utc") or ""))

    intervals: list[dict[str, Any]] = []
    for previous, present in zip(records, records[1:]):
        agent_delta: dict[str, Any] = {}
        for agent in ("ena_1h", "trend_8h", "cross_sectional_30d_7d"):
            before = previous["strategy"][agent]
            after = present["strategy"][agent]
            agent_delta[agent] = {
                "completed_outcomes_delta": int(after["completed_outcomes"]) - int(before["completed_outcomes"]),
                "pnl_per_1000_usdt_delta": float(after["pnl_per_1000_usdt"]) - float(before["pnl_per_1000_usdt"])
            }
        intervals.append(
            {
                "interval_start_utc": previous["observed_at_utc"],
                "interval_end_utc": present["observed_at_utc"],
                "prior_gamma_context": previous["gamma"],
                "strategy_delta": agent_delta
            }
        )

    comparison_cfg = protocol.get("comparison_definition", {})
    minimum_snapshots = int(comparison_cfg.get("minimum_forward_snapshots_before_descriptive_state_comparison", 12))
    minimum_outcomes = int(comparison_cfg.get("minimum_completed_strategy_outcomes_before_any_pnl_by_gamma_state_table", 5))
    total_outcome_increments = sum(
        max(0, int(item["completed_outcomes_delta"]))
        for interval in intervals
        for item in interval["strategy_delta"].values()
    )
    if len(records) < minimum_snapshots:
        status = "collecting_gamma_history"
    elif total_outcome_increments < minimum_outcomes:
        status = "gamma_history_ready_strategy_outcomes_insufficient"
    else:
        status = "descriptive_comparison_ready"

    sign_groups: dict[str, dict[str, Any]] = {}
    if status == "descriptive_comparison_ready":
        for interval in intervals:
            sign = str(interval["prior_gamma_context"].get("call_minus_put_proxy_sign") or "unknown")
            group = sign_groups.setdefault(sign, {"intervals": 0, "agents": {}})
            group["intervals"] += 1
            for agent, delta in interval["strategy_delta"].items():
                slot = group["agents"].setdefault(agent, {"completed_outcomes": 0, "pnl_delta_per_1000_usdt": 0.0})
                slot["completed_outcomes"] += int(delta["completed_outcomes_delta"])
                slot["pnl_delta_per_1000_usdt"] += float(delta["pnl_per_1000_usdt_delta"])

    payload = {
        "schema_version": 1,
        "trial": "gamma-exposure-trial-v1-forward-comparison",
        "status": status,
        "protocol_sha256": _canonical_sha256(protocol),
        "records": records,
        "intervals": intervals,
        "descriptive_by_prior_gamma_sign": sign_groups,
        "guards": {
            "minimum_forward_snapshots": minimum_snapshots,
            "minimum_completed_strategy_outcomes": minimum_outcomes,
            "observed_forward_snapshots": len(records),
            "observed_completed_outcome_increments": total_outcome_increments,
            "historical_strategy_results_relabelled_gamma_conditioned": False
        },
        "claims": {
            "research_only": True,
            "gamma_threshold_selected_from_strategy_pnl": False,
            "strategy_parameters_changed": False,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False
        }
    }
    payload["manifest_sha256"] = _canonical_sha256(payload)
    return payload


def load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GammaExposureError(f"cannot read JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise GammaExposureError(f"JSON must be an object: {path}")
    return value
