from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any, Callable

import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.htf_trend_forward_shadow import load_candidate
from orderflow_edge_lab.markov_ev_shadow import build_trend_shadow_report
from orderflow_edge_lab.markov_trend_veto_audit import audit_trend_decisions
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


def _retry(fn: Callable[[], Any], *, attempts: int = 4) -> Any:
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last = exc
            if i + 1 < attempts:
                time.sleep(1.0 * (2 ** i))
    assert last is not None
    raise last


def _load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit realized outcomes of frozen Markov PASS/VETO decisions.")
    parser.add_argument("--config", default="config/markov_trend_veto_forward_audit_v1.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--max-workers", type=int, default=5)
    args = parser.parse_args()

    audit_config = _load(args.config)
    base_candidate, base_file_sha = load_candidate(audit_config["base_candidate_config"])
    if base_candidate["candidate_id"] != audit_config["base_candidate_id"]:
        raise SystemExit("base candidate id changed")
    if base_candidate["spec_sha256"] != audit_config["base_candidate_spec_sha256"]:
        raise SystemExit("base candidate hash changed")

    shadow = _load(audit_config["shadow_config"])
    markov = _load(audit_config["markov_config"])
    ev = _load(audit_config["ev_config"])
    clones = [x for x in shadow["clones"] if x["shadow_candidate_id"] == audit_config["shadow_candidate_id"]]
    if len(clones) != 1:
        raise SystemExit("frozen trend shadow clone not found exactly once")
    clone = clones[0]
    evaluation = audit_config["evaluation"]
    if int(clone["primary_horizon_bars"]) != int(evaluation["horizon_bars"]):
        raise SystemExit("audit horizon differs from frozen Markov horizon")
    if str(clone["shadow_execution_start_utc"]) != str(evaluation["execution_start_utc"]):
        raise SystemExit("audit start differs from frozen Markov start")

    as_of = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp.now(tz="UTC")
    as_of = as_of.tz_localize("UTC") if as_of.tzinfo is None else as_of.tz_convert("UTC")
    symbols = [str(x) for x in base_candidate["specification"]["symbols"]]
    warmup = str(base_candidate["forward_protocol"]["indicator_warmup_start_utc"])
    funding_start = str(evaluation["execution_start_utc"])
    source_dir = Path(args.source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)

    frames: dict[str, pd.DataFrame] = {}
    funding: dict[str, pd.DataFrame] = {}
    hashes: dict[str, str] = {}

    def load_symbol(symbol: str):
        frame = _retry(lambda: fetch_mexc_futures_klines(symbol, "8h", warmup, as_of.isoformat()))
        fund = _retry(lambda: fetch_mexc_funding_history(symbol, funding_start, as_of.isoformat()))
        return symbol, frame, fund

    with ThreadPoolExecutor(max_workers=max(1, min(int(args.max_workers), len(symbols)))) as pool:
        futures = {pool.submit(load_symbol, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            expected = futures[future]
            symbol, frame, fund = future.result()
            if symbol != expected:
                raise SystemExit("symbol identity mismatch")
            frames[symbol] = frame
            funding[symbol] = fund
            frame_path = source_dir / f"{symbol}_8h.csv"
            fund_path = source_dir / f"{symbol}_funding.csv"
            frame.to_csv(frame_path, index_label="timestamp")
            fund.to_csv(fund_path, index_label="timestamp")
            hashes[f"{symbol}:8h"] = sha256(frame_path.read_bytes()).hexdigest()
            hashes[f"{symbol}:funding"] = sha256(fund_path.read_bytes()).hexdigest()

    shadow_report = build_trend_shadow_report(
        frames,
        funding,
        base_candidate,
        clone,
        markov,
        ev,
        as_of_utc=as_of,
    )
    audit = audit_trend_decisions(
        shadow_report["entry_decisions"],
        frames,
        funding,
        horizon_bars=int(evaluation["horizon_bars"]),
        round_trip_cost_bps=float(evaluation["round_trip_cost_bps"]),
        minimum_completed_decisions_for_review=int(evaluation["minimum_completed_decisions_for_review"]),
    )
    report = {
        "schema_version": 1,
        "experiment_id": audit_config["experiment_id"],
        "frozen_at_utc": audit_config["frozen_at_utc"],
        "as_of_utc": as_of.isoformat(),
        "base_candidate_id": base_candidate["candidate_id"],
        "base_candidate_spec_sha256": base_candidate["spec_sha256"],
        "base_candidate_file_sha256": base_file_sha,
        "shadow_candidate_id": clone["shadow_candidate_id"],
        "source_sha256": hashes,
        "frozen_shadow_metrics": shadow_report["metrics"],
        "audit": audit,
        "claims": audit_config["claims"],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "as_of_utc": report["as_of_utc"],
        "shadow_metrics": report["frozen_shadow_metrics"],
        "audit_summary": {
            "completed_decisions": audit["completed_decisions"],
            "censored_decisions": audit["censored_decisions"],
            "reviewable_count_reached": audit["reviewable_count_reached"],
            "pass": audit["pass"],
            "veto": audit["veto"],
            "pass_minus_veto_mean_realized_net_bps": audit["pass_minus_veto_mean_realized_net_bps"],
            "avoided_veto_losses": audit["avoided_veto_losses"],
            "missed_veto_winners": audit["missed_veto_winners"],
        },
    }, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
