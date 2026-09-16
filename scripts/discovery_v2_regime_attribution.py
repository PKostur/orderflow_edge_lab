from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _wilder_adx(frame: pd.DataFrame, period: int) -> pd.Series:
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")

    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=frame.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=frame.index)

    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)

    alpha = 1.0 / float(period)
    atr = tr.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus_smoothed = plus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    minus_smoothed = minus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus_di = 100.0 * plus_smoothed / atr.replace(0.0, np.nan)
    minus_di = 100.0 * minus_smoothed / atr.replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return dx.ewm(alpha=alpha, adjust=False, min_periods=period).mean()


def _build_regimes(btc: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    vol_cfg = cfg["volatility_state"]
    trend_cfg = cfg["trend_state"]
    btc = btc.sort_index().copy()
    close = pd.to_numeric(btc["close"], errors="coerce")
    logret = np.log(close).diff()

    rv_window = int(vol_cfg["realized_volatility_window_days"])
    annualization = float(vol_cfg["annualization_days"])
    threshold_history = int(vol_cfg["threshold_history_observations"])
    rv = logret.rolling(rv_window, min_periods=rv_window).std(ddof=1) * np.sqrt(annualization)
    rv_threshold = rv.shift(1).rolling(threshold_history, min_periods=threshold_history).median()

    adx_period = int(trend_cfg["period_days"])
    adx = _wilder_adx(btc, adx_period)
    direction_20 = np.log(close / close.shift(20))

    # Daily candle timestamps are candle opens. At execution open t, candle t is not completed,
    # so every regime feature is shifted one full daily bar and uses information through t-1 only.
    features = pd.DataFrame(
        {
            "rv20": rv.shift(1),
            "rv_threshold": rv_threshold.shift(1),
            "adx14": adx.shift(1),
            "direction_20": direction_20.shift(1),
        },
        index=btc.index,
    )
    valid = features.notna().all(axis=1)
    high_vol = features["rv20"] > features["rv_threshold"]
    trend = features["adx14"] >= float(trend_cfg["trend_threshold"])
    features["regime"] = np.where(
        high_vol & trend,
        "HIGH_VOL_TREND",
        np.where(
            high_vol & ~trend,
            "HIGH_VOL_RANGE",
            np.where(~high_vol & trend, "LOW_VOL_TREND", "LOW_VOL_RANGE"),
        ),
    )
    features["trend_direction"] = np.where(features["direction_20"] >= 0.0, "UP", "DOWN")
    features.loc[~valid, ["regime", "trend_direction"]] = None
    return features


def _read_observations(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["timestamp", "end_timestamp"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["end_timestamp"] = pd.to_datetime(frame["end_timestamp"], utc=True)
    return frame.set_index("timestamp").sort_index()


def run(cfg: dict[str, Any], results_root: Path) -> dict[str, Any]:
    btc_path = results_root / "data" / "daily" / "BTC_USDT_1d.csv"
    btc = pd.read_csv(btc_path, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    btc.index = pd.to_datetime(btc.index, utc=True)
    regimes = _build_regimes(btc, cfg)

    series_root = results_root / "series"
    rows: list[dict[str, Any]] = []
    direction_rows: list[dict[str, Any]] = []
    joined_counts: dict[str, int] = {}

    for family_dir in sorted(p for p in series_root.iterdir() if p.is_dir()):
        variants_dir = family_dir / "variants"
        if not variants_dir.exists():
            continue
        for variant_dir in sorted(p for p in variants_dir.iterdir() if p.is_dir()):
            obs = _read_observations(variant_dir / "observations.csv")
            joined = obs.join(regimes[["regime", "trend_direction", "rv20", "rv_threshold", "adx14"]], how="left")
            joined = joined.loc[joined["regime"].notna()].copy()
            strategy_id = variant_dir.name
            family = family_dir.name
            joined_counts[strategy_id] = int(len(joined))

            for regime, cell in joined.groupby("regime", sort=True):
                rows.append(
                    {
                        "family": family,
                        "strategy_id": strategy_id,
                        "regime": str(regime),
                        "observations": int(len(cell)),
                        "mean_net_bps": float(cell["net_return_bps"].mean()),
                        "median_net_bps": float(cell["net_return_bps"].median()),
                        "positive_fraction": float((cell["net_return_bps"] > 0.0).mean()),
                        "cumulative_net_bps": float(cell["net_return_bps"].sum()),
                        "mean_gross_bps": float(cell["gross_return_bps"].mean()),
                        "mean_cost_bps": float(cell["cost_bps"].mean()),
                    }
                )

            for (regime, direction), cell in joined.groupby(["regime", "trend_direction"], sort=True):
                direction_rows.append(
                    {
                        "family": family,
                        "strategy_id": strategy_id,
                        "regime": str(regime),
                        "trend_direction": str(direction),
                        "observations": int(len(cell)),
                        "mean_net_bps": float(cell["net_return_bps"].mean()),
                        "positive_fraction": float((cell["net_return_bps"] > 0.0).mean()),
                    }
                )

    matrix = pd.DataFrame(rows)
    if matrix.empty:
        raise RuntimeError("no eligible strategy-regime observations")
    minimum = int(cfg["minimum_cell_observations_for_comparison"])
    eligible = matrix.loc[matrix["observations"] >= minimum].copy()
    winners: list[dict[str, Any]] = []
    for regime in cfg["primary_regimes"]:
        cell = eligible.loc[eligible["regime"] == regime].sort_values(
            ["mean_net_bps", "observations", "strategy_id"], ascending=[False, False, True]
        )
        if cell.empty:
            winners.append({"regime": regime, "eligible": False, "reason": f"no strategy with >= {minimum} observations"})
            continue
        top = cell.iloc[0]
        winners.append(
            {
                "regime": regime,
                "eligible": True,
                "strategy_id": str(top["strategy_id"]),
                "family": str(top["family"]),
                "observations": int(top["observations"]),
                "mean_net_bps": float(top["mean_net_bps"]),
                "median_net_bps": float(top["median_net_bps"]),
                "positive_fraction": float(top["positive_fraction"]),
                "selection_status": "DESCRIPTIVE_ONLY_NOT_A_CANDIDATE",
            }
        )

    regime_counts = regimes["regime"].value_counts(dropna=True).to_dict()
    return {
        "protocol": cfg["protocol"],
        "status": "DIAGNOSTIC_COMPLETE",
        "source_sprint": cfg["source_sprint"],
        "state_timing": cfg["state_timing"],
        "regime_counts_available_market_days": {str(k): int(v) for k, v in regime_counts.items()},
        "joined_strategy_observations": joined_counts,
        "regime_winners": winners,
        "claims": cfg["claims"],
        "matrix_records": matrix.to_dict(orient="records"),
        "direction_records": pd.DataFrame(direction_rows).to_dict(orient="records"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default="config/discovery_v2_regime_attribution_v1.json")
    parser.add_argument("--results-root", default="research/discovery_v2/sprint2/results")
    parser.add_argument("--output-dir", default="research/discovery_v2/sprint2/regime_attribution")
    args = parser.parse_args()

    cfg = _load_json(args.protocol)
    assert cfg["status"] == "FROZEN_BEFORE_REGIME_RESULTS"
    results_root = Path(args.results_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report = _json_safe(run(cfg, results_root))
    (output_dir / "regime_attribution.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    pd.DataFrame(report["matrix_records"]).to_csv(output_dir / "regime_matrix.csv", index=False)
    pd.DataFrame(report["direction_records"]).to_csv(output_dir / "regime_direction_matrix.csv", index=False)
    pd.DataFrame(report["regime_winners"]).to_csv(output_dir / "regime_winners.csv", index=False)
    print(json.dumps(report["regime_winners"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
