from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

import fibonacci_setup_quality_v1 as parent
from orderflow_edge_lab.strategy_tournament import generate_target_position


def _trade_stats(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    returns = [float(row["net_return"]) for row in trades]
    stats = parent._return_stats(returns)
    if not trades:
        return {
            **stats,
            "setup_count": 0,
            "median_mae_bps": None,
            "median_mfe_bps": None,
        }
    mae = np.asarray([float(row.get("mae_bps", np.nan)) for row in trades], dtype=float)
    mfe = np.asarray([float(row.get("mfe_bps", np.nan)) for row in trades], dtype=float)
    return {
        **stats,
        "setup_count": int(len(trades)),
        "median_mae_bps": float(np.nanmedian(mae)) if np.isfinite(mae).any() else None,
        "median_mfe_bps": float(np.nanmedian(mfe)) if np.isfinite(mfe).any() else None,
    }


def _concentration(values: Sequence[str]) -> dict[str, Any]:
    items = [str(value) for value in values if value is not None]
    if not items:
        return {
            "observations": 0,
            "distinct_units": 0,
            "max_share": None,
            "hhi": None,
            "counts": {},
        }
    counts: dict[str, int] = {}
    for value in items:
        counts[value] = counts.get(value, 0) + 1
    total = float(len(items))
    shares = [count / total for count in counts.values()]
    return {
        "observations": int(len(items)),
        "distinct_units": int(len(counts)),
        "max_share": float(max(shares)),
        "hhi": float(sum(share * share for share in shares)),
        "counts": dict(sorted(counts.items())),
    }


def _fixed_fold_id(ts: pd.Timestamp, start: pd.Timestamp, fold_days: int) -> str:
    elapsed_days = (parent._utc(ts) - parent._utc(start)).total_seconds() / 86400.0
    idx = max(0, int(math.floor(elapsed_days / float(fold_days))))
    return f"fold_{idx:02d}"


def _btc_regimes(
    frame: pd.DataFrame,
    strategy_family: str,
    strategy_parameters: Mapping[str, Any],
    *,
    vol_history_bars: int,
    vol_min_history_bars: int,
) -> tuple[pd.Series, pd.Series]:
    target = generate_target_position(frame, strategy_family, strategy_parameters)
    causal_target = target.shift(1).reindex(frame.index).fillna(0.0)

    trend = pd.Series("neutral", index=frame.index, dtype=object)
    trend.loc[causal_target > 0] = "bull"
    trend.loc[causal_target < 0] = "bear"

    atr = parent._atr(frame, int(strategy_parameters["atr_period"]))
    vol = (atr / frame["close"].astype(float)).shift(1)
    historical = vol.shift(1)
    q_low = historical.rolling(
        int(vol_history_bars), min_periods=int(vol_min_history_bars)
    ).quantile(1.0 / 3.0)
    q_high = historical.rolling(
        int(vol_history_bars), min_periods=int(vol_min_history_bars)
    ).quantile(2.0 / 3.0)

    vol_state = pd.Series("unknown", index=frame.index, dtype=object)
    valid = vol.notna() & q_low.notna() & q_high.notna()
    vol_state.loc[valid & (vol < q_low)] = "low"
    vol_state.loc[valid & (vol > q_high)] = "high"
    vol_state.loc[valid & (vol >= q_low) & (vol <= q_high)] = "middle"
    return trend, vol_state


def _enrich_trade(
    row: Mapping[str, Any],
    *,
    symbol: str,
    fold_start: pd.Timestamp,
    fold_days: int,
    btc_trend: pd.Series,
    btc_vol: pd.Series,
) -> dict[str, Any]:
    entry = parent._utc(row["entry_time"])
    trend_value = str(btc_trend.asof(entry)) if len(btc_trend) else "unknown"
    vol_value = str(btc_vol.asof(entry)) if len(btc_vol) else "unknown"
    out = dict(row)
    out.update(
        {
            "symbol": symbol,
            "fold_id": _fixed_fold_id(entry, fold_start, fold_days),
            "btc_trend_regime": trend_value,
            "btc_volatility_regime": vol_value,
        }
    )
    return out


def _slice_rows(
    trades_by_overlay: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    cost_bps: float,
    dimension: str,
) -> list[dict[str, Any]]:
    values: set[str] = set()
    for rows in trades_by_overlay.values():
        values.update(str(row[dimension]) for row in rows)
    out: list[dict[str, Any]] = []
    for value in sorted(values):
        for overlay, rows in trades_by_overlay.items():
            subset = [row for row in rows if str(row[dimension]) == value]
            out.append(
                {
                    "cost_bps": float(cost_bps),
                    "dimension": dimension,
                    "value": value,
                    "overlay": overlay,
                    "stats": _trade_stats(subset),
                }
            )
    return out


def _portfolio_cell(
    prices: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.DataFrame],
    raw_positions: pd.DataFrame,
    cost_bps: float,
) -> dict[str, Any]:
    net, funding_ret, transaction_cost = parent._portfolio_returns(
        prices, funding, raw_positions, float(cost_bps)
    )
    stats = parent._return_stats(net.tolist())
    stats.update(
        {
            "funding_contribution": float(funding_ret.sum()),
            "transaction_cost_drag": float(transaction_cost.sum()),
            "active_bar_fraction": float((raw_positions.abs().sum(axis=1) > 0).mean()),
        }
    )
    return {"stats": stats, "net_returns": net}


def _delta(a: Any, b: Any) -> float | None:
    if a is None or b is None:
        return None
    try:
        return float(a) - float(b)
    except (TypeError, ValueError):
        return None


def run(config: Mapping[str, Any], max_workers: int) -> dict[str, Any]:
    data_cfg = config["data"]
    strat_cfg = config["frozen_strategy"]
    fib_cfg = config["frozen_fibonacci"]
    symbols = list(data_cfg["symbols"])
    start = str(data_cfg["start"])
    end = str(data_cfg["end_exclusive"])
    interval = str(data_cfg["interval"])

    prices = parent._fetch_prices(symbols, interval, start, end, max_workers)
    funding = parent._fetch_funding(symbols, start, end, max_workers)
    declared_start = parent._utc(start)
    for symbol in symbols:
        if funding[symbol].empty:
            raise RuntimeError(f"no observed funding for {symbol}")
        first = funding[symbol].index.min()
        if first > declared_start:
            raise RuntimeError(
                f"funding coverage for {symbol} begins {first.isoformat()}, after declared start {declared_start.isoformat()}"
            )

    common = parent._common_index(prices, symbols)
    if len(common) < 200:
        raise RuntimeError("insufficient common HTF history")

    strategy_family = str(strat_cfg["signal_family"])
    strategy_parameters = dict(strat_cfg["parameters"])
    overlays = {
        "baseline": None,
        "fib_core": list(fib_cfg["fib_core_levels"]),
        "nonfib_matched_control": list(fib_cfg["matched_nonfib_levels"]),
    }
    raw_by_overlay = {
        name: pd.DataFrame(0.0, index=common, columns=symbols) for name in overlays
    }

    for symbol in symbols:
        frame = prices[symbol].loc[common]
        target = generate_target_position(frame, strategy_family, strategy_parameters)
        depth = parent.directional_fib_depth(
            frame,
            target,
            lookback_bars=int(fib_cfg["anchor_lookback_bars"]),
            minimum_impulse_atr=float(fib_cfg["minimum_impulse_atr"]),
            atr_period=int(strategy_parameters["atr_period"]),
        )
        for name, levels in overlays.items():
            gated = (
                target
                if levels is None
                else parent.gate_target_on_entry_transitions(
                    target,
                    parent._eligible(
                        depth, levels, float(fib_cfg["level_tolerance"])
                    ),
                )
            )
            raw_by_overlay[name][symbol] = gated.shift(1).reindex(common).fillna(0.0)

    btc_frame = prices["BTC_USDT"].loc[common]
    regime_cfg = config["regime_robustness"]["btc_volatility"]
    btc_trend, btc_vol = _btc_regimes(
        btc_frame,
        strategy_family,
        strategy_parameters,
        vol_history_bars=int(regime_cfg["history_bars"]),
        vol_min_history_bars=int(regime_cfg["minimum_history_bars"]),
    )

    fold_days = int(config["time_robustness"]["fold_days"])
    fold_start = parent._utc(start)
    aggregate_cells: list[dict[str, Any]] = []
    slice_cells: list[dict[str, Any]] = []
    trade_ledgers: dict[str, dict[str, list[dict[str, Any]]]] = {}
    primary_cost = float(config["costs"]["primary_diagnostic_bps"])
    primary_payload: dict[str, Any] | None = None

    common_prices = {symbol: prices[symbol].loc[common] for symbol in symbols}
    for cost_value in config["costs"]["round_trip_bps"]:
        cost = float(cost_value)
        trades_by_overlay: dict[str, list[dict[str, Any]]] = {}
        portfolio_by_overlay: dict[str, dict[str, Any]] = {}

        for overlay, raw_positions in raw_by_overlay.items():
            all_trades: list[dict[str, Any]] = []
            for symbol in symbols:
                rows = parent._extract_position_trades(
                    prices[symbol].loc[common],
                    funding[symbol],
                    raw_positions[symbol],
                    round_trip_cost_bps=cost,
                )
                all_trades.extend(
                    _enrich_trade(
                        row,
                        symbol=symbol,
                        fold_start=fold_start,
                        fold_days=fold_days,
                        btc_trend=btc_trend,
                        btc_vol=btc_vol,
                    )
                    for row in rows
                )
            trades_by_overlay[overlay] = all_trades
            portfolio_by_overlay[overlay] = _portfolio_cell(
                common_prices, funding, raw_positions, cost
            )

        for overlay in overlays:
            setup = _trade_stats(trades_by_overlay[overlay])
            port = portfolio_by_overlay[overlay]["stats"]
            aggregate_cells.append(
                {
                    "cost_bps": cost,
                    "overlay": overlay,
                    "setup_stats": setup,
                    "portfolio_stats": port,
                }
            )

        for dimension in (
            "symbol",
            "fold_id",
            "btc_trend_regime",
            "btc_volatility_regime",
        ):
            slice_cells.extend(
                _slice_rows(trades_by_overlay, cost_bps=cost, dimension=dimension)
            )

        trade_ledgers[f"{cost:g}bps"] = {
            overlay: list(rows) for overlay, rows in trades_by_overlay.items()
        }

        if abs(cost - primary_cost) < 1e-12:
            core = trades_by_overlay["fib_core"]
            concentration = {
                "symbol": _concentration([row["symbol"] for row in core]),
                "fold_id": _concentration([row["fold_id"] for row in core]),
                "btc_trend_regime": _concentration(
                    [row["btc_trend_regime"] for row in core]
                ),
                "btc_volatility_regime": _concentration(
                    [row["btc_volatility_regime"] for row in core]
                ),
            }

            leave_one_symbol_out: list[dict[str, Any]] = []
            for omitted in symbols:
                keep = [symbol for symbol in symbols if symbol != omitted]
                by_overlay: dict[str, dict[str, Any]] = {}
                for overlay, raw_positions in raw_by_overlay.items():
                    cell = _portfolio_cell(
                        {symbol: common_prices[symbol] for symbol in keep},
                        {symbol: funding[symbol] for symbol in keep},
                        raw_positions[keep],
                        cost,
                    )
                    by_overlay[overlay] = cell["stats"]
                leave_one_symbol_out.append(
                    {
                        "omitted_symbol": omitted,
                        "baseline_return": by_overlay["baseline"]["compounded_return"],
                        "fib_core_return": by_overlay["fib_core"]["compounded_return"],
                        "nonfib_control_return": by_overlay["nonfib_matched_control"][
                            "compounded_return"
                        ],
                        "fib_minus_baseline_return": _delta(
                            by_overlay["fib_core"]["compounded_return"],
                            by_overlay["baseline"]["compounded_return"],
                        ),
                        "fib_minus_nonfib_return": _delta(
                            by_overlay["fib_core"]["compounded_return"],
                            by_overlay["nonfib_matched_control"]["compounded_return"],
                        ),
                    }
                )

            all_fold_ids = sorted(
                {
                    _fixed_fold_id(ts, fold_start, fold_days)
                    for ts in portfolio_by_overlay["baseline"]["net_returns"].index
                }
            )
            leave_one_fold_out: list[dict[str, Any]] = []
            for omitted_fold in all_fold_ids:
                stats_by_overlay: dict[str, dict[str, Any]] = {}
                for overlay in overlays:
                    series = portfolio_by_overlay[overlay]["net_returns"]
                    mask = pd.Series(
                        [
                            _fixed_fold_id(ts, fold_start, fold_days) != omitted_fold
                            for ts in series.index
                        ],
                        index=series.index,
                        dtype=bool,
                    )
                    stats_by_overlay[overlay] = parent._return_stats(
                        series.loc[mask].tolist()
                    )
                leave_one_fold_out.append(
                    {
                        "omitted_fold": omitted_fold,
                        "baseline_return": stats_by_overlay["baseline"][
                            "compounded_return"
                        ],
                        "fib_core_return": stats_by_overlay["fib_core"][
                            "compounded_return"
                        ],
                        "nonfib_control_return": stats_by_overlay[
                            "nonfib_matched_control"
                        ]["compounded_return"],
                        "fib_minus_baseline_return": _delta(
                            stats_by_overlay["fib_core"]["compounded_return"],
                            stats_by_overlay["baseline"]["compounded_return"],
                        ),
                        "fib_minus_nonfib_return": _delta(
                            stats_by_overlay["fib_core"]["compounded_return"],
                            stats_by_overlay["nonfib_matched_control"][
                                "compounded_return"
                            ],
                        ),
                    }
                )

            primary_payload = {
                "cost_bps": cost,
                "fib_core_setup_concentration": concentration,
                "leave_one_symbol_out": leave_one_symbol_out,
                "leave_one_fold_out": leave_one_fold_out,
                "interpretation": (
                    "These are descriptive development robustness diagnostics only. "
                    "They cannot promote the Fib overlay or replace untouched OOS evidence."
                ),
            }

    if primary_payload is None:
        raise RuntimeError("primary diagnostic cost was not evaluated")

    return {
        "schema_version": 1,
        "protocol_name": config["protocol_name"],
        "status": config["status"],
        "parent_protocol": config["parent_protocol"],
        "parent_branch_head": config["parent_branch_head"],
        "data_start": start,
        "data_end_exclusive": end,
        "symbols": symbols,
        "frozen_fibonacci": fib_cfg,
        "frozen_strategy": strat_cfg,
        "aggregate_cells": aggregate_cells,
        "slice_cells": slice_cells,
        "primary_robustness": primary_payload,
        "trade_ledgers": trade_ledgers,
        "analysis_rules": config["analysis_rules"],
        "claims": config["claims"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run frozen HTF Fibonacci robustness diagnostics"
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-workers", type=int, default=6)
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    report = run(config, max_workers=max(1, int(args.max_workers)))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    primary = report["primary_robustness"]["fib_core_setup_concentration"]
    print(
        json.dumps(
            {
                "protocol": report["protocol_name"],
                "fib_core_concentration": primary,
                "claims": report["claims"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
