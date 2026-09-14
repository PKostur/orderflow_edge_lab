from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import rankdata

FEATURES = ("microprice_displacement_bps", "book_imbalance_10")
HORIZONS = (5, 15, 30, 60)


def _corr(x: np.ndarray, y: np.ndarray) -> float:
    mask = np.isfinite(x) & np.isfinite(y)
    if int(mask.sum()) < 3:
        return float("nan")
    xr = rankdata(x[mask], method="average")
    yr = rankdata(y[mask], method="average")
    if np.std(xr) == 0 or np.std(yr) == 0:
        return float("nan")
    return float(np.corrcoef(xr, yr)[0, 1])


def _read_features(path: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("event_type") not in {"depth", "trade"}:
                continue
            bid = row.get("best_bid")
            ask = row.get("best_ask")
            micro = row.get("microprice")
            imb = row.get("book_imbalance_10")
            if None in (bid, ask, micro, imb):
                continue
            bid = float(bid)
            ask = float(ask)
            micro = float(micro)
            imb = float(imb)
            if not all(math.isfinite(v) for v in (bid, ask, micro, imb)) or bid <= 0 or ask <= bid:
                continue
            ts_ms = row.get("exchange_ts_ms")
            if ts_ms is None:
                received = row.get("received_at_ns")
                if received is None:
                    continue
                ts_ms = int(received) // 1_000_000
            mid = (bid + ask) / 2.0
            rows.append({
                "symbol": str(row.get("symbol", "")),
                "ts_ms": int(ts_ms),
                "mid": mid,
                "microprice_displacement_bps": 10000.0 * (micro - mid) / mid,
                "book_imbalance_10": imb,
            })
    if not rows:
        return pd.DataFrame(columns=["symbol", "ts_ms", "mid", *FEATURES])
    frame = pd.DataFrame(rows).sort_values(["symbol", "ts_ms"])
    frame["sec"] = frame["ts_ms"] // 1000
    frame = frame.groupby(["symbol", "sec"], as_index=False).last()
    return frame.sort_values(["symbol", "ts_ms"]).reset_index(drop=True)


def _symbol_arrays(group: pd.DataFrame, horizon_s: int) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    ts = group["ts_ms"].to_numpy(dtype=np.int64)
    mid = group["mid"].to_numpy(dtype=float)
    future_index = np.searchsorted(ts, ts + horizon_s * 1000, side="left")
    valid = future_index < len(group)
    if not valid.any():
        return None
    current_idx = np.flatnonzero(valid)
    future_idx = future_index[valid]
    y = 10000.0 * (mid[future_idx] / mid[current_idx] - 1.0)
    return current_idx, future_idx, y


def run_batch(features_path: Path, batch_id: str, out: Path, epochs: int = 1000) -> None:
    frame = _read_features(features_path)
    rng = np.random.default_rng(20260914)
    metrics: list[dict[str, Any]] = []
    assoc_values: list[float] = []

    for symbol, group in frame.groupby("symbol", sort=True):
        if symbol == "BTC_USDT" or len(group) < 50:
            continue
        assoc_values.append(_corr(
            group["microprice_displacement_bps"].to_numpy(float),
            group["book_imbalance_10"].to_numpy(float),
        ))

    for feature in FEATURES:
        for horizon in HORIZONS:
            symbol_payload: list[tuple[str, np.ndarray, np.ndarray]] = []
            symbol_rhos: list[float] = []
            for symbol, group in frame.groupby("symbol", sort=True):
                if symbol == "BTC_USDT":
                    continue
                arrays = _symbol_arrays(group, horizon)
                if arrays is None:
                    continue
                current_idx, _future_idx, y = arrays
                if len(y) < 50:
                    continue
                x = group[feature].to_numpy(float)[current_idx]
                rho = _corr(x, y)
                if not math.isfinite(rho):
                    continue
                symbol_payload.append((symbol, x, y))
                symbol_rhos.append(rho)
            batch_rho = float(np.median(symbol_rhos)) if symbol_rhos else float("nan")
            perm_values: list[float] = []
            if len(symbol_payload) >= 1 and math.isfinite(batch_rho):
                for _ in range(epochs):
                    per_symbol: list[float] = []
                    for _symbol, x, y in symbol_payload:
                        shuffled = rng.permutation(y)
                        value = _corr(x, shuffled)
                        if math.isfinite(value):
                            per_symbol.append(value)
                    if per_symbol:
                        perm_values.append(float(np.median(per_symbol)))
            if perm_values:
                perm_p = (1.0 + sum(abs(v) >= abs(batch_rho) for v in perm_values)) / (1.0 + len(perm_values))
            else:
                perm_p = float("nan")
            metrics.append({
                "feature": feature,
                "horizon_seconds": horizon,
                "valid_symbols": len(symbol_rhos),
                "batch_median_spearman": batch_rho,
                "feature_sign_reversed_spearman": -batch_rho if math.isfinite(batch_rho) else None,
                "within_symbol_batch_permutation_p": perm_p if math.isfinite(perm_p) else None,
                "symbol_spearman": symbol_rhos,
            })

    payload = {
        "schema_version": 1,
        "protocol": "microprice-imbalance-forward-v1",
        "batch_id": batch_id,
        "source_file": features_path.name,
        "rows_after_1s_sampling": int(len(frame)),
        "feature_association": {
            "metric": "Spearman",
            "median_symbol_rho": float(np.nanmedian(assoc_values)) if assoc_values else None,
            "high_redundancy": bool(assoc_values and abs(float(np.nanmedian(assoc_values))) >= 0.80),
            "symbol_rhos": [v for v in assoc_values if math.isfinite(v)],
        },
        "state_metrics": metrics,
        "claims": {
            "strategy_pnl_inspected": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")


def _sign_test_two_sided(positive: int, total: int) -> float:
    if total <= 0:
        return 1.0
    k = min(positive, total - positive)
    tail = sum(math.comb(total, i) for i in range(k + 1)) / (2 ** total)
    return min(1.0, 2.0 * tail)


def run_aggregate(inputs: list[Path], out: Path) -> None:
    batches = [json.loads(p.read_text(encoding="utf-8")) for p in inputs]
    rows: list[dict[str, Any]] = []
    for feature in FEATURES:
        for horizon in HORIZONS:
            values: list[float] = []
            perm_ps: list[float] = []
            for batch in batches:
                match = next((r for r in batch.get("state_metrics", []) if r.get("feature") == feature and int(r.get("horizon_seconds", -1)) == horizon), None)
                if not match or int(match.get("valid_symbols", 0)) < 6:
                    continue
                rho = match.get("batch_median_spearman")
                if rho is None or not math.isfinite(float(rho)):
                    continue
                values.append(float(rho))
                p = match.get("within_symbol_batch_permutation_p")
                if p is not None and math.isfinite(float(p)):
                    perm_ps.append(float(p))
            n = len(values)
            positive = sum(v > 0 for v in values)
            median_rho = float(np.median(values)) if values else float("nan")
            positive_fraction = positive / n if n else 0.0
            sign_p = _sign_test_two_sided(positive, n)
            passed = bool(
                n >= 6
                and math.isfinite(median_rho)
                and median_rho > 0.02
                and positive_fraction >= (2.0 / 3.0)
                and sign_p <= 0.10
            )
            rows.append({
                "feature": feature,
                "horizon_seconds": horizon,
                "independent_batches": n,
                "median_batch_spearman": median_rho if math.isfinite(median_rho) else None,
                "positive_batch_fraction": positive_fraction,
                "two_sided_sign_test_p": sign_p,
                "median_within_batch_permutation_p": float(np.median(perm_ps)) if perm_ps else None,
                "state_pass": passed,
            })

    assoc = [b.get("feature_association", {}).get("median_symbol_rho") for b in batches]
    assoc = [float(v) for v in assoc if v is not None and math.isfinite(float(v))]
    payload = {
        "schema_version": 1,
        "protocol": "microprice-imbalance-forward-v1",
        "independent_batches_seen": len(batches),
        "feature_association_median_across_batches": float(np.median(assoc)) if assoc else None,
        "high_redundancy_across_batches": bool(assoc and abs(float(np.median(assoc))) >= 0.80),
        "state_results": rows,
        "state_passes": sum(bool(r["state_pass"]) for r in rows),
        "strategy_pnl_layer_open": False,
        "claims": {
            "profitable_edge_established": False,
            "untouched_oos": False,
            "live_order_transmission_supported": False,
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    batch = sub.add_parser("batch")
    batch.add_argument("--features", type=Path, required=True)
    batch.add_argument("--batch-id", required=True)
    batch.add_argument("--out", type=Path, required=True)
    batch.add_argument("--epochs", type=int, default=1000)
    aggregate = sub.add_parser("aggregate")
    aggregate.add_argument("inputs", nargs="+", type=Path)
    aggregate.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.cmd == "batch":
        run_batch(args.features, args.batch_id, args.out, args.epochs)
    else:
        run_aggregate(args.inputs, args.out)


if __name__ == "__main__":
    main()
