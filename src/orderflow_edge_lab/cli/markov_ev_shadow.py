from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path

import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.cross_sectional_forward_shadow import load_candidate as load_xs_candidate
from orderflow_edge_lab.ena_forward_shadow import load_candidate as load_ena_candidate
from orderflow_edge_lab.htf_trend_forward_shadow import load_candidate as load_trend_candidate
from orderflow_edge_lab.markov_ev_shadow import (
    build_cross_sectional_shadow_report,
    build_ena_shadow_report,
    build_trend_shadow_report,
)
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


def _utc(value: str | None) -> pd.Timestamp:
    ts = pd.Timestamp.now(tz="UTC") if value is None else pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _clone_map(config: dict) -> dict[str, dict]:
    return {str(item["base_candidate_id"]): item for item in config["clones"]}


def _funding_or_empty(symbol: str, start: str, as_of: pd.Timestamp) -> pd.DataFrame:
    start_ts = pd.Timestamp(start)
    start_ts = start_ts.tz_localize("UTC") if start_ts.tzinfo is None else start_ts.tz_convert("UTC")
    if as_of <= start_ts:
        return pd.DataFrame(columns=["funding_rate"])
    return fetch_mexc_funding_history(symbol, start_ts.isoformat(), as_of.isoformat())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run prospective Markov EV veto-only paper-shadow clones.")
    parser.add_argument("--shadow-config", default="config/markov_ev_shadow_v1.json")
    parser.add_argument("--markov-config", default="config/markov_price_diagnostics_v1.json")
    parser.add_argument("--ev-config", default="config/markov_ev_overlay_v1.json")
    parser.add_argument("--output", default="artifacts/markov_ev_shadow/report.json")
    parser.add_argument("--source-dir", default="artifacts/markov_ev_shadow/source")
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--max-workers", type=int, default=6)
    args = parser.parse_args()

    as_of = _utc(args.as_of)
    shadow = _load_json(args.shadow_config)
    markov = _load_json(args.markov_config)
    ev = _load_json(args.ev_config)
    clones = _clone_map(shadow)
    source_dir = Path(args.source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)

    ena_candidate, _ = load_ena_candidate(clones["ena_bb40_rsi25_75_atr15_v1"]["base_candidate_config"])
    trend_candidate, _ = load_trend_candidate(clones["mexc_8h_ema24_96_atr025_v1"]["base_candidate_config"])
    xs_candidate, _ = load_xs_candidate(clones["mexc_xs_mom30_7_dn_v1"]["base_candidate_config"])

    ena_clone = clones[ena_candidate["candidate_id"]]
    ena_closed_end = as_of.floor("h")
    ena_frame = fetch_mexc_futures_klines(
        "ENA_USDT", "1h", str(ena_clone["training_start_utc"]), ena_closed_end.isoformat()
    )
    ena_frame.to_csv(source_dir / "ENA_USDT_1h.csv", index_label="timestamp")

    symbols = [str(s) for s in trend_candidate["specification"]["symbols"]]
    trend_frames: dict[str, pd.DataFrame] = {}
    trend_funding: dict[str, pd.DataFrame] = {}
    xs_frames: dict[str, pd.DataFrame] = {}
    xs_funding: dict[str, pd.DataFrame] = {}

    def load_symbol(symbol: str):
        trend = fetch_mexc_futures_klines(
            symbol, "8h", str(clones[trend_candidate["candidate_id"]]["training_start_utc"]), as_of.isoformat()
        )
        daily = fetch_mexc_futures_klines(
            symbol, "1d", str(clones[xs_candidate["candidate_id"]]["training_start_utc"]), as_of.isoformat()
        )
        trend_fund = _funding_or_empty(symbol, clones[trend_candidate["candidate_id"]]["shadow_execution_start_utc"], as_of)
        xs_fund = _funding_or_empty(symbol, clones[xs_candidate["candidate_id"]]["shadow_execution_start_utc"], as_of)
        return symbol, trend, daily, trend_fund, xs_fund

    with ThreadPoolExecutor(max_workers=max(1, min(int(args.max_workers), len(symbols)))) as pool:
        futures = {pool.submit(load_symbol, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol, trend, daily, trend_fund, xs_fund = future.result()
            trend_frames[symbol] = trend
            xs_frames[symbol] = daily
            trend_funding[symbol] = trend_fund
            xs_funding[symbol] = xs_fund
            trend.to_csv(source_dir / f"{symbol}_8h.csv", index_label="timestamp")
            daily.to_csv(source_dir / f"{symbol}_1d.csv", index_label="timestamp")
            trend_fund.to_csv(source_dir / f"{symbol}_trend_funding.csv", index_label="timestamp")
            xs_fund.to_csv(source_dir / f"{symbol}_xs_funding.csv", index_label="timestamp")

    ena_report = build_ena_shadow_report(
        ena_frame, ena_candidate, ena_clone, markov, ev, as_of_utc=as_of
    )
    trend_report = build_trend_shadow_report(
        trend_frames, trend_funding, trend_candidate, clones[trend_candidate["candidate_id"]], markov, ev, as_of_utc=as_of
    )
    xs_report = build_cross_sectional_shadow_report(
        xs_frames, xs_funding, xs_candidate, clones[xs_candidate["candidate_id"]], markov, ev, as_of_utc=as_of
    )

    report = {
        "schema_version": 1,
        "experiment_id": shadow["experiment_id"],
        "as_of_utc": as_of.isoformat(),
        "shadow_config_frozen_at_utc": shadow["frozen_at_utc"],
        "policy": shadow["policy"],
        "reports": {
            ena_report["shadow_candidate_id"]: ena_report,
            trend_report["shadow_candidate_id"]: trend_report,
            xs_report["shadow_candidate_id"]: xs_report,
        },
        "claims": shadow["claims"],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "experiment_id": report["experiment_id"],
        "as_of_utc": report["as_of_utc"],
        "clones": {
            key: {
                "status": value["status"],
                "metrics": value["metrics"],
                "current_weights": value.get("current_weights"),
            }
            for key, value in report["reports"].items()
        },
        "claims": report["claims"],
    }, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
