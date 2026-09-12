from __future__ import annotations

from pathlib import Path
from typing import Any

from orderflow_edge_lab.orderflow_backtest import (
    BacktestConfig,
    _first_quote_at_or_after,
    _load,
    _quote_rows,
    evaluate,
)


class DirectionPairError(ValueError):
    pass


def _summarize(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int, float], list[dict[str, Any]]] = {}
    for row in observations:
        groups.setdefault(
            (str(row["family"]), int(row["horizon_ms"]), float(row["fee_bps_round_trip"])),
            [],
        ).append(row)

    summary: list[dict[str, Any]] = []
    for (family, horizon, fee), group in sorted(groups.items()):
        nets = [float(x["net_bps"]) for x in group]
        gross = [float(x["gross_bps"]) for x in group]
        if not nets:
            continue
        summary.append(
            {
                "family": family,
                "horizon_ms": horizon,
                "fee_bps_round_trip": fee,
                "observations": len(nets),
                "gross_mean_bps": sum(gross) / len(gross),
                "net_mean_bps": sum(nets) / len(nets),
                "net_win_rate": sum(x > 0 for x in nets) / len(nets),
                "net_total_bps": sum(nets),
            }
        )
    return summary


def _summary_key(row: dict[str, Any]) -> tuple[str, int, float]:
    return (
        str(row["family"]),
        int(row["horizon_ms"]),
        float(row["fee_bps_round_trip"]),
    )


def evaluate_pair(path: str | Path, cfg: BacktestConfig = BacktestConfig()) -> dict[str, Any]:
    """Evaluate the frozen signals twice, once as specified and once fully reversed.

    The reversed control keeps signal timestamps, families, horizons, cooldowns and
    fee assumptions identical. Only execution direction changes. Entry and exit
    prices are recalculated from the executable opposite-side quotes, so the
    reversed stream pays the spread rather than merely negating original PnL.
    """

    original = evaluate(path, cfg)
    rows = _load(path)
    quotes = _quote_rows(rows, cfg.symbol)

    original_observations: list[dict[str, Any]] = []
    reversed_observations: list[dict[str, Any]] = []

    for observation in original["observations"]:
        signal_side = int(observation["side"])
        original_observations.append(
            {
                **observation,
                "stream": "original",
                "signal_side": signal_side,
            }
        )

        trade_side = -signal_side
        target_ns = int(observation["signal_observed_at_ns"]) + int(observation["horizon_ms"]) * 1_000_000
        quote = _first_quote_at_or_after(quotes, target_ns)
        if quote is None:
            raise DirectionPairError("paired reversed stream lost an exit quote present in the original stream")

        exit_ns, bid, ask, exit_exchange_ts = quote
        entry_price = float(observation["signal_ask"]) if trade_side > 0 else float(observation["signal_bid"])
        exit_price = bid if trade_side > 0 else ask
        gross_bps = trade_side * (exit_price / entry_price - 1.0) * 10_000.0
        fee_bps = float(observation["fee_bps_round_trip"])

        reversed_observations.append(
            {
                **observation,
                "stream": "reversed",
                "signal_side": signal_side,
                "side": trade_side,
                "entry_price": entry_price,
                "exit_observed_at_ns": exit_ns,
                "exit_exchange_ts_ms": exit_exchange_ts,
                "exit_price": exit_price,
                "gross_bps": gross_bps,
                "net_bps": gross_bps - fee_bps,
            }
        )

    original_summary = _summarize(original_observations)
    reversed_summary = _summarize(reversed_observations)
    original_by_key = {_summary_key(row): row for row in original_summary}
    reversed_by_key = {_summary_key(row): row for row in reversed_summary}
    if original_by_key.keys() != reversed_by_key.keys():
        raise DirectionPairError("original and reversed summary keys diverged")

    comparison: list[dict[str, Any]] = []
    for key in sorted(original_by_key):
        original_row = original_by_key[key]
        reversed_row = reversed_by_key[key]
        if int(original_row["observations"]) != int(reversed_row["observations"]):
            raise DirectionPairError(f"observation count mismatch for {key}")
        comparison.append(
            {
                "family": key[0],
                "horizon_ms": key[1],
                "fee_bps_round_trip": key[2],
                "observations": int(original_row["observations"]),
                "original_gross_mean_bps": float(original_row["gross_mean_bps"]),
                "reversed_gross_mean_bps": float(reversed_row["gross_mean_bps"]),
                "original_net_mean_bps": float(original_row["net_mean_bps"]),
                "reversed_net_mean_bps": float(reversed_row["net_mean_bps"]),
                "original_net_win_rate": float(original_row["net_win_rate"]),
                "reversed_net_win_rate": float(reversed_row["net_win_rate"]),
                "original_minus_reversed_net_bps": float(original_row["net_mean_bps"])
                - float(reversed_row["net_mean_bps"]),
            }
        )

    return {
        "schema_version": 1,
        "experiment": "paired_original_vs_reversed_execution",
        "source_sha256": original["source_sha256"],
        "causal_clock": original["causal_clock"],
        "exchange_timestamps_used_for_ordering": original["exchange_timestamps_used_for_ordering"],
        "config": original["config"],
        "feature_rows": original["feature_rows"],
        "signals": original["signals"],
        "streams": {
            "original": {
                "summary": original_summary,
                "observations": original_observations,
            },
            "reversed": {
                "summary": reversed_summary,
                "observations": reversed_observations,
            },
        },
        "comparison": comparison,
        "claims": {
            "exploratory_only": True,
            "paired_control_only": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }
