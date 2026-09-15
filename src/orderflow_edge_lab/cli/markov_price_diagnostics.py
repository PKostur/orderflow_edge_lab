from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from orderflow_edge_lab.markov_price_diagnostics import (
    MarkovStateSpec,
    aggregate_candidate,
    analyze_symbol,
)
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


_INTERVAL_SECONDS = {
    "1h": 60 * 60,
    "8h": 8 * 60 * 60,
    "1d": 24 * 60 * 60,
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Frozen price-state Markov diagnostics")
    parser.add_argument("--config", default="config/markov_price_diagnostics_v1.json")
    parser.add_argument("--output", default="artifacts/markov_price_diagnostics_v1.json")
    parser.add_argument("--source-dir", default="artifacts/markov_price_sources")
    parser.add_argument("--as-of-utc", default=None)
    return parser.parse_args()


def _as_utc(value: str | None) -> pd.Timestamp:
    if value is None:
        return pd.Timestamp(datetime.now(timezone.utc))
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _state_spec(payload: dict) -> MarkovStateSpec:
    state = payload["state_definition"]
    return MarkovStateSpec(
        direction_scale_lookback_bars=int(state["direction_scale_lookback_bars"]),
        direction_z_down_lt=float(state["direction_z_down_lt"]),
        direction_z_up_gt=float(state["direction_z_up_gt"]),
        volatility_short_lookback_bars=int(state["volatility_short_lookback_bars"]),
        volatility_long_lookback_bars=int(state["volatility_long_lookback_bars"]),
        volatility_ratio_low_lt=float(state["volatility_ratio_low_lt"]),
        volatility_ratio_high_gt=float(state["volatility_ratio_high_gt"]),
        transition_smoothing_alpha=float(state["transition_smoothing_alpha"]),
        minimum_state_transition_count_for_reliable_label=int(
            state["minimum_state_transition_count_for_reliable_label"]
        ),
    )


def _completed_only(frame: pd.DataFrame, interval: str, as_of: pd.Timestamp) -> pd.DataFrame:
    seconds = _INTERVAL_SECONDS[interval]
    completed = frame.index + pd.to_timedelta(seconds, unit="s") <= as_of
    return frame.loc[completed].copy()


def main() -> None:
    args = _parse_args()
    config_path = Path(args.config)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    spec = _state_spec(payload)
    as_of = _as_utc(args.as_of_utc)
    source_dir = Path(args.source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "schema_version": 1,
        "protocol_id": payload["protocol_id"],
        "protocol_frozen_at_utc": payload["frozen_at_utc"],
        "as_of_utc": as_of.isoformat(),
        "fit_policy": payload["fit_policy"],
        "state_definition": payload["state_definition"],
        "candidates": {},
        "claims": {
            "diagnostic_only": True,
            "candidate_specifications_modified": False,
            "verified_out_of_sample_edge": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }

    for candidate in payload["candidates"]:
        candidate_id = candidate["candidate_id"]
        interval = candidate["interval"]
        symbol_results = {}
        errors = {}
        for symbol in candidate["symbols"]:
            try:
                frame = fetch_mexc_futures_klines(
                    symbol=symbol,
                    interval=interval,
                    start=candidate["training_start_utc"],
                    end=as_of.isoformat(),
                )
                frame = _completed_only(frame, interval, as_of)
                if frame.empty:
                    raise ValueError("no completed candles at requested as-of time")
                source_path = source_dir / f"{candidate_id}__{symbol}__{interval}.csv"
                frame.to_csv(source_path)
                symbol_results[symbol] = analyze_symbol(
                    frame,
                    training_end_exclusive_utc=candidate["training_end_exclusive_utc"],
                    forecast_steps=candidate["forecast_steps"],
                    spec=spec,
                )
            except Exception as exc:  # report per-symbol failure without hiding other diagnostics
                errors[symbol] = f"{type(exc).__name__}: {exc}"

        result["candidates"][candidate_id] = {
            "candidate_config": candidate["candidate_config"],
            "interval": interval,
            "training_start_utc": candidate["training_start_utc"],
            "training_end_exclusive_utc": candidate["training_end_exclusive_utc"],
            "forecast_steps": candidate["forecast_steps"],
            "symbols": symbol_results,
            "aggregate": aggregate_candidate(symbol_results),
            "errors": errors,
        }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
