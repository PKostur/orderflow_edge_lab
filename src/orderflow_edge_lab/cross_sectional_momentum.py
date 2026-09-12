from __future__ import annotations

import math
from statistics import median
from typing import Any, Mapping

import numpy as np
import pandas as pd


class CrossSectionalMomentumError(ValueError):
    pass


def _align_frames(frames: Mapping[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    if len(frames) < 4:
        raise CrossSectionalMomentumError("at least four symbols are required")
    closes: dict[str, pd.Series] = {}
    opens: dict[str, pd.Series] = {}
    for symbol, frame in sorted(frames.items()):
        if not isinstance(frame.index, pd.DatetimeIndex):
            raise CrossSectionalMomentumError(f"{symbol}: index must be DatetimeIndex")
        if not {"open", "close"}.issubset(frame.columns):
            raise CrossSectionalMomentumError(f"{symbol}: open/close columns required")
        clean = frame.sort_index()
        if clean.index.has_duplicates:
            raise CrossSectionalMomentumError(f"{symbol}: duplicate timestamps")
        opens[symbol] = pd.to_numeric(clean["open"], errors="coerce")
        closes[symbol] = pd.to_numeric(clean["close"], errors="coerce")
    open_frame = pd.concat(opens, axis=1, join="inner").dropna()
    close_frame = pd.concat(closes, axis=1, join="inner").dropna()
    idx = open_frame.index.intersection(close_frame.index)
    open_frame = open_frame.loc[idx].sort_index()
    close_frame = close_frame.loc[idx].sort_index()
    if len(idx) < 200:
        raise CrossSectionalMomentumError(f"insufficient common history: {len(idx)} rows")
    if (open_frame <= 0).any().any() or (close_frame <= 0).any().any():
        raise CrossSectionalMomentumError("non-positive prices are not allowed")
    return open_frame.astype(float), close_frame.astype(float)


def build_signal_weights(
    close_frame: pd.DataFrame,
    *,
    lookback_days: int = 30,
    holding_days: int = 7,
    quantile_fraction: float = 0.25,
    variant: str = "long_only_top",
) -> pd.DataFrame:
    if lookback_days < 2 or holding_days < 1:
        raise CrossSectionalMomentumError("invalid lookback/holding period")
    if not 0 < quantile_fraction < 0.5:
        raise CrossSectionalMomentumError("quantile_fraction must be between 0 and 0.5")
    if variant not in {"long_only_top", "dollar_neutral_top_bottom"}:
        raise CrossSectionalMomentumError(f"unknown variant: {variant}")
    symbols = list(close_frame.columns)
    n_select = max(1, int(math.floor(len(symbols) * quantile_fraction)))
    trailing = close_frame / close_frame.shift(lookback_days) - 1.0
    signal = pd.DataFrame(0.0, index=close_frame.index, columns=symbols)
    rebalance_rows = range(lookback_days, len(close_frame), holding_days)
    current = pd.Series(0.0, index=symbols, dtype=float)
    rebalance_set = set(rebalance_rows)
    for i in range(len(close_frame)):
        if i in rebalance_set:
            scores = trailing.iloc[i].dropna().sort_values()
            if len(scores) >= max(4, n_select * 2):
                winners = list(scores.index[-n_select:])
                losers = list(scores.index[:n_select])
                current = pd.Series(0.0, index=symbols, dtype=float)
                if variant == "long_only_top":
                    current.loc[winners] = 1.0 / len(winners)
                else:
                    current.loc[winners] = 0.5 / len(winners)
                    current.loc[losers] = -0.5 / len(losers)
        signal.iloc[i] = current
    return signal


def backtest_cross_sectional_momentum(
    frames: Mapping[str, pd.DataFrame],
    *,
    lookback_days: int,
    holding_days: int,
    quantile_fraction: float,
    variant: str,
    round_trip_cost_bps: float,
    fold_days: int,
) -> dict[str, Any]:
    opens, closes = _align_frames(frames)
    signal_weights = build_signal_weights(
        closes,
        lookback_days=lookback_days,
        holding_days=holding_days,
        quantile_fraction=quantile_fraction,
        variant=variant,
    )
    # A signal formed on the completed close at t is first executable at open(t+1).
    weights = signal_weights.shift(1).fillna(0.0)
    next_open_returns = opens.shift(-1) / opens - 1.0
    gross_daily = (weights * next_open_returns).sum(axis=1).fillna(0.0)
    turnover = (weights - weights.shift(1).fillna(0.0)).abs().sum(axis=1)
    side_cost = float(round_trip_cost_bps) / 2.0 / 10_000.0
    net_daily = gross_daily - turnover * side_cost
    if len(net_daily) > 1:
        # Include liquidation to cash at the end of the sample.
        net_daily.iloc[-2] -= float(weights.iloc[-2].abs().sum()) * side_cost
    usable = net_daily.iloc[:-1].copy()
    gross_usable = gross_daily.iloc[:-1].copy()
    turnover_usable = turnover.iloc[:-1].copy()
    weights_usable = weights.iloc[:-1].copy()

    equity = (1.0 + usable).cumprod()
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    std = float(usable.std(ddof=0))
    sharpe = float(usable.mean() / std * math.sqrt(365.25)) if std > 0 else None
    rebalances = int((turnover_usable > 1e-12).sum())

    anchor = usable.index.min().normalize()
    fold_ids = ((usable.index.normalize() - anchor).days // int(fold_days)).astype(int)
    folds: list[dict[str, Any]] = []
    for fold in sorted(set(int(v) for v in fold_ids)):
        mask = np.asarray(fold_ids == fold)
        returns = usable.iloc[mask]
        if len(returns) < 20:
            continue
        fold_eq = (1.0 + returns).cumprod()
        fold_std = float(returns.std(ddof=0))
        fold_sharpe = float(returns.mean() / fold_std * math.sqrt(365.25)) if fold_std > 0 else None
        folds.append(
            {
                "fold": fold,
                "start": returns.index.min().isoformat(),
                "end": returns.index.max().isoformat(),
                "observations": len(returns),
                "net_return": float(fold_eq.iloc[-1] - 1.0),
                "sharpe": fold_sharpe,
                "turnover": float(turnover_usable.iloc[mask].sum()),
                "rebalances": int((turnover_usable.iloc[mask] > 1e-12).sum()),
            }
        )
    fold_returns = [float(row["net_return"]) for row in folds]
    fold_sharpes = [float(row["sharpe"]) for row in folds if row.get("sharpe") is not None]
    positive_fold_fraction = sum(v > 0 for v in fold_returns) / len(fold_returns) if fold_returns else None

    btc_benchmark = None
    if "BTC_USDT" in opens.columns:
        btc = (opens["BTC_USDT"].shift(-1) / opens["BTC_USDT"] - 1.0).iloc[:-1].fillna(0.0)
        btc_eq = (1.0 + btc).cumprod()
        btc_std = float(btc.std(ddof=0))
        btc_benchmark = {
            "return": float(btc_eq.iloc[-1] - 1.0),
            "sharpe": float(btc.mean() / btc_std * math.sqrt(365.25)) if btc_std > 0 else None,
        }

    return {
        "variant": variant,
        "lookback_days": int(lookback_days),
        "holding_days": int(holding_days),
        "quantile_fraction": float(quantile_fraction),
        "round_trip_cost_bps": float(round_trip_cost_bps),
        "symbols": list(opens.columns),
        "start": usable.index.min().isoformat(),
        "end": usable.index.max().isoformat(),
        "rebalances": rebalances,
        "total_turnover": float(turnover_usable.sum()),
        "gross_return": float((1.0 + gross_usable).cumprod().iloc[-1] - 1.0),
        "net_return": float(equity.iloc[-1] - 1.0),
        "max_drawdown": float(drawdown.min()),
        "sharpe": sharpe,
        "exposure_fraction": float((weights_usable.abs().sum(axis=1) > 0).mean()),
        "fold_observations": len(folds),
        "positive_fold_fraction": positive_fold_fraction,
        "median_fold_return": float(median(fold_returns)) if fold_returns else None,
        "median_fold_sharpe": float(median(fold_sharpes)) if fold_sharpes else None,
        "folds": folds,
        "btc_buy_hold_open_to_open": btc_benchmark,
    }


def run_frozen_grid(frames: Mapping[str, pd.DataFrame], protocol: Mapping[str, Any]) -> dict[str, Any]:
    strategy = protocol["strategy"]
    validation = protocol["validation"]
    rows: list[dict[str, Any]] = []
    for variant in strategy["variants"]:
        for cost in protocol["economics"]["round_trip_cost_bps"]:
            result = backtest_cross_sectional_momentum(
                frames,
                lookback_days=int(strategy["lookback_days"]),
                holding_days=int(strategy["holding_days"]),
                quantile_fraction=float(strategy["quantile_fraction"]),
                variant=str(variant),
                round_trip_cost_bps=float(cost),
                fold_days=int(validation["fold_days"]),
            )
            eligible = bool(
                result["rebalances"] >= int(validation["minimum_rebalances"])
                and result["fold_observations"] >= int(validation["minimum_folds"])
                and result["positive_fold_fraction"] is not None
                and float(result["positive_fold_fraction"]) >= float(validation["minimum_positive_fold_fraction"])
                and result["median_fold_return"] is not None and float(result["median_fold_return"]) > float(validation["median_fold_return_gt"])
                and result["median_fold_sharpe"] is not None and float(result["median_fold_sharpe"]) > float(validation["median_fold_sharpe_gt"])
            )
            result["screening_eligible"] = eligible
            rows.append(result)
    rows.sort(key=lambda row: (bool(row["screening_eligible"]), float(row.get("median_fold_return") or -1e18)), reverse=True)
    return {
        "schema_version": 1,
        "protocol_name": protocol["protocol_name"],
        "source_prior": protocol["source_prior"],
        "trial_count": len(rows),
        "eligible_count": sum(bool(row["screening_eligible"]) for row in rows),
        "trials": rows,
        "claims": dict(protocol["claims"]),
    }
