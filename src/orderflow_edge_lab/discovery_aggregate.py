from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from statistics import median, stdev
from typing import Any, Iterable


class DiscoveryAggregateError(ValueError):
    pass


def _sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_protocol(path: str | Path) -> dict[str, Any]:
    try:
        protocol = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscoveryAggregateError(f"cannot read discovery protocol: {path}") from exc
    if not isinstance(protocol, dict) or protocol.get("schema_version") != 1:
        raise DiscoveryAggregateError("unsupported discovery protocol")
    config = protocol.get("backtest_config")
    if not isinstance(config, dict):
        raise DiscoveryAggregateError("discovery protocol is missing backtest_config")
    return protocol


def _load_report(path: str | Path, expected_config: dict[str, Any]) -> dict[str, Any]:
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscoveryAggregateError(f"cannot read backtest report: {path}") from exc
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        raise DiscoveryAggregateError(f"unsupported backtest report: {path}")
    if report.get("config") != expected_config:
        raise DiscoveryAggregateError(f"backtest config does not match frozen protocol: {path}")
    claims = report.get("claims") or {}
    if claims.get("profitable_edge_established") is not False:
        raise DiscoveryAggregateError(f"backtest report contains an invalid profitability claim: {path}")
    source = report.get("source_sha256")
    if not isinstance(source, str) or len(source) != 64:
        raise DiscoveryAggregateError(f"backtest report lacks source_sha256: {path}")
    return report


def aggregate(
    report_paths: Iterable[str | Path],
    protocol_path: str | Path,
) -> dict[str, Any]:
    paths = [Path(p) for p in report_paths]
    if not paths:
        raise DiscoveryAggregateError("at least one backtest report is required")
    protocol = load_protocol(protocol_path)
    expected_config = protocol["backtest_config"]
    reports: list[tuple[Path, dict[str, Any]]] = []
    seen_sources: set[str] = set()
    for path in paths:
        report = _load_report(path, expected_config)
        source = report["source_sha256"]
        if source in seen_sources:
            raise DiscoveryAggregateError(f"duplicate source capture in discovery aggregate: {source}")
        seen_sources.add(source)
        reports.append((path, report))

    groups: dict[tuple[str, int, float], list[dict[str, Any]]] = {}
    for _path, report in reports:
        for row in report.get("summary", []):
            key = (str(row["family"]), int(row["horizon_ms"]), float(row["fee_bps_round_trip"]))
            groups.setdefault(key, []).append(row)

    summary: list[dict[str, Any]] = []
    minimum_batches = int(protocol.get("research_rules", {}).get("minimum_batches_before_inference", 10))
    for (family, horizon, fee), rows in sorted(groups.items()):
        batch_means = [float(r["net_mean_bps"]) for r in rows if int(r.get("observations", 0)) > 0]
        observations = [int(r.get("observations", 0)) for r in rows if int(r.get("observations", 0)) > 0]
        gross_means = [float(r["gross_mean_bps"]) for r in rows if int(r.get("observations", 0)) > 0]
        if not batch_means:
            continue
        n = len(batch_means)
        total_obs = sum(observations)
        weighted_net = sum(v * count for v, count in zip(batch_means, observations)) / total_obs
        weighted_gross = sum(v * count for v, count in zip(gross_means, observations)) / total_obs
        mean_batch = sum(batch_means) / n
        se = stdev(batch_means) / math.sqrt(n) if n >= 2 else None
        summary.append({
            "family": family,
            "horizon_ms": horizon,
            "fee_bps_round_trip": fee,
            "batches_with_observations": n,
            "observations_total": total_obs,
            "batch_mean_net_bps": mean_batch,
            "batch_median_net_bps": median(batch_means),
            "positive_batch_fraction": sum(v > 0 for v in batch_means) / n,
            "batch_standard_error_bps": se,
            "approx_95pct_batch_mean_low_bps": None if se is None else mean_batch - 1.96 * se,
            "approx_95pct_batch_mean_high_bps": None if se is None else mean_batch + 1.96 * se,
            "event_weighted_net_mean_bps_descriptive": weighted_net,
            "event_weighted_gross_mean_bps_descriptive": weighted_gross,
            "minimum_batches_for_inference": minimum_batches,
            "inference_ready": n >= minimum_batches,
        })

    evidence = [
        {
            "path": str(path),
            "report_sha256": _sha256(path),
            "source_sha256": report["source_sha256"],
            "feature_rows": int(report.get("feature_rows", 0)),
            "signals": int(report.get("signals", 0)),
        }
        for path, report in reports
    ]
    payload: dict[str, Any] = {
        "schema_version": 1,
        "protocol_id": protocol.get("protocol_id"),
        "protocol_sha256": _sha256(protocol_path),
        "backtest_config": expected_config,
        "batches": len(reports),
        "feature_rows_total": sum(item["feature_rows"] for item in evidence),
        "signals_total": sum(item["signals"] for item in evidence),
        "evidence": evidence,
        "summary": summary,
        "interpretation": {
            "primary_independence_unit": "capture_batch",
            "event_weighted_statistics_are_descriptive_only": True,
            "thresholds_frozen_for_discovery_v1": True,
        },
        "claims": {
            "exploratory_only": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }
    payload["manifest_sha256"] = _canonical_hash(payload)
    return payload


def verify_manifest(report: dict[str, Any]) -> bool:
    stored = report.get("manifest_sha256")
    if not isinstance(stored, str):
        return False
    copy = dict(report)
    copy.pop("manifest_sha256", None)
    return stored == _canonical_hash(copy)
