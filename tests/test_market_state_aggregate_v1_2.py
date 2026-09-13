from __future__ import annotations

import json
from pathlib import Path

from orderflow_edge_lab.market_state_aggregate_v1_2 import build_v1_2_state_screen


BOUNDARY_NS = 1_789_264_800_000_000_000


def _write_protocol(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "protocol_name": "regime-research-v1.2",
                "frozen_at_utc": "2026-09-13T00:50:00Z",
                "evidence_start_utc": "2026-09-13T02:00:00Z",
                "evidence_start_batch_id": "20260913T020000Z",
                "state_screen": {
                    "minimum_independent_batches": 5,
                    "minimum_dominant_sign_fraction": 0.8,
                    "minimum_association_observations_per_batch": 20,
                    "minimum_median_abs_spearman": 0.10,
                    "minimum_median_abs_partial_spearman": 0.10,
                    "redundancy_abs_spearman_threshold": 0.80,
                },
                "dependence_clustering": {"dependence_gap_seconds": 300},
                "claims": {
                    "changes_regime_research_v1_scan_definitions": False,
                    "uses_strategy_pnl_for_state_selection": False,
                    "profitable_edge_established": False,
                    "live_order_transmission_supported": False,
                },
            }
        ),
        encoding="utf-8",
    )


def _write_report(path: Path, batch_id: str, start_ns: int, observations: int = 20) -> None:
    rows = []
    for index in range(observations):
        rows.append(
            {
                "batch_id": batch_id,
                "symbol": "ENA_USDT",
                "observed_at_ns": start_ns + index * 5_000_000_000,
                "features": {"spread_bps": 1.0 + index / 100.0},
                "targets": {"future_spread_bps_5s": 1.1 + index / 100.0},
            }
        )
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "experiment": "regime_research_v1_market_state_scan",
                "batch_id": batch_id,
                "associations": [
                    {
                        "research_family": "liquidity_stability_deterioration",
                        "feature": "spread_bps",
                        "target": "future_spread_bps_5s",
                        "observations": observations,
                        "spearman": 0.25,
                    }
                ],
                "feature_redundancy": {"pairs": [], "clusters": []},
                "observations": rows,
            }
        ),
        encoding="utf-8",
    )


def test_five_separated_captures_reach_screen_ready(tmp_path: Path) -> None:
    protocol = tmp_path / "protocol.json"
    _write_protocol(protocol)
    reports = []
    for index in range(5):
        path = tmp_path / f"report_{index}.json"
        _write_report(
            path,
            f"20260913T0{2 + index}0000Z",
            BOUNDARY_NS + index * 3_600_000_000_000,
        )
        reports.append(path)

    result = build_v1_2_state_screen(reports, protocol)

    assert result["status"] == "screen_ready"
    assert result["independent_batch_count"] == 5
    assert result["dependence_audit"]["independent_cluster_count"] == 5
    assert result["dependence_audit"]["collapsed_report_count"] == 0
    assert result["eligible_state_association_count"] == 1
    assert result["claims"]["strategy_pnl_used"] is False


def test_overlapping_captures_collapse_into_one_dependence_cluster(tmp_path: Path) -> None:
    protocol = tmp_path / "protocol.json"
    _write_protocol(protocol)
    reports = []
    starts = [
        BOUNDARY_NS,
        BOUNDARY_NS + 60_000_000_000,
        BOUNDARY_NS + 3_600_000_000_000,
        BOUNDARY_NS + 7_200_000_000_000,
        BOUNDARY_NS + 10_800_000_000_000,
    ]
    for index, start_ns in enumerate(starts):
        path = tmp_path / f"report_{index}.json"
        _write_report(path, f"20260913T0{2 + index}0000Z", start_ns)
        reports.append(path)

    result = build_v1_2_state_screen(reports, protocol)

    assert result["status"] == "collecting_forward_dependence_clusters"
    assert result["independent_batch_count"] == 4
    assert result["dependence_audit"]["independent_cluster_count"] == 4
    assert result["dependence_audit"]["collapsed_report_count"] == 1
    first = result["dependence_audit"]["clusters"][0]
    assert len(first["member_batch_ids"]) == 2


def test_gap_rule_is_transitive(tmp_path: Path) -> None:
    protocol = tmp_path / "protocol.json"
    _write_protocol(protocol)
    reports = []
    for index, offset_seconds in enumerate((0, 350, 700)):
        path = tmp_path / f"report_{index}.json"
        _write_report(
            path,
            f"20260913T0{2 + index}0000Z",
            BOUNDARY_NS + offset_seconds * 1_000_000_000,
        )
        reports.append(path)

    result = build_v1_2_state_screen(reports, protocol)

    assert result["dependence_audit"]["independent_cluster_count"] == 1
    assert result["dependence_audit"]["collapsed_report_count"] == 2


def test_preboundary_timestamp_is_excluded_even_with_future_batch_id(tmp_path: Path) -> None:
    protocol = tmp_path / "protocol.json"
    _write_protocol(protocol)
    report = tmp_path / "report.json"
    _write_report(report, "20260913T030000Z", BOUNDARY_NS - 1)

    result = build_v1_2_state_screen([report], protocol)

    assert result["status"] == "waiting_for_forward_dependence_clusters"
    assert result["independent_batch_count"] == 0
    assert result["dependence_audit"]["eligible_report_count"] == 0
