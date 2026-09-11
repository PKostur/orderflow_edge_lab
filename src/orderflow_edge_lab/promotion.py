from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Any

from .economics import EconomicsPolicy, load_economics_policy


@dataclass(frozen=True)
class PromotionAssessment:
    candidate_id: str
    promotable: bool
    research_only: bool
    reasons: tuple[str, ...]
    validation_report_sha256: str
    economics_sha256: str
    monthly_fixed_cost: float
    monthly_cost_hurdle_fraction: float
    source_files_reverified: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "promotable": self.promotable,
            "research_only": self.research_only,
            "reasons": list(self.reasons),
            "validation_report_sha256": self.validation_report_sha256,
            "economics_sha256": self.economics_sha256,
            "monthly_fixed_cost": self.monthly_fixed_cost,
            "monthly_cost_hurdle_fraction": self.monthly_cost_hurdle_fraction,
            "source_files_reverified": self.source_files_reverified,
        }


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _require_dict(value: object, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(message)
    return value


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value.lower())
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reverify_source_files(report: dict[str, Any]) -> tuple[str, ...]:
    """Re-hash the exact source paths recorded in a promotable report.

    This is intentionally a second verification at the paper-promotion boundary.
    The structural report may have been generated earlier; a boolean marker in that
    report is not enough to prove that the referenced bytes still match now.
    Relative paths are interpreted using the current process working directory,
    matching normal Path semantics. Missing, non-file, duplicate, unreadable, or
    changed inputs all fail closed.
    """
    source = report.get("source_verification")
    files = source.get("files") if isinstance(source, dict) else None
    if not isinstance(files, list) or not files:
        return ("source_file_reverification_unavailable",)

    seen: set[Path] = set()
    reasons: list[str] = []
    for item in files:
        if not isinstance(item, dict):
            return ("source_file_reverification_unavailable",)
        raw_path = item.get("path")
        expected = item.get("sha256")
        if not isinstance(raw_path, str) or not raw_path.strip() or not _valid_sha256(expected):
            return ("source_file_reverification_unavailable",)
        path = Path(raw_path).expanduser().resolve()
        if path in seen:
            reasons.append("source_file_evidence_ambiguous")
            continue
        seen.add(path)
        try:
            if not path.is_file():
                reasons.append("source_file_not_reverifiable")
                continue
            actual = _sha256_file(path)
        except OSError:
            reasons.append("source_file_not_reverifiable")
            continue
        if actual.lower() != str(expected).lower():
            reasons.append("source_file_sha256_mismatch")
    return tuple(dict.fromkeys(reasons))


def assess_candidate_promotion(
    validation_report: dict[str, Any],
    candidate_id: str,
    economics: EconomicsPolicy,
) -> PromotionAssessment:
    """Fail-closed strategy promotion gate.

    Descriptive statistics never establish an edge. Promotion requires explicit
    upstream OOS certification plus internally consistent evidence counts, causal
    window summaries, verified source bytes, and acceptable project economics.
    Current project validation artifacts deliberately do not certify an edge.

    This in-memory assessment validates report structure only. File-backed callers
    must use ``assess_candidate_promotion_files`` so source bytes are re-hashed at
    the promotion boundary.
    """
    report = _require_dict(validation_report, "validation report must be an object")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError("candidate_id must be a nonempty string")
    candidate_id = candidate_id.strip()

    reasons: list[str] = []
    if report.get("schema_version") != 7:
        reasons.append("unsupported_validation_schema")
    if report.get("causal_window_summaries") is not True:
        reasons.append("causal_window_summaries_not_verified")
    if report.get("deployment_eligible") is not True:
        reasons.append("validation_report_not_deployment_eligible")
    if report.get("verified_out_of_sample_evidence") is not True:
        reasons.append("out_of_sample_edge_not_verified")

    source = report.get("source_verification")
    source_ok = isinstance(source, dict) and source.get("verified_against_local_files") is True
    if not source_ok:
        reasons.append("source_bytes_not_locally_verified")
    else:
        files = source.get("files")
        if (
            not isinstance(files, list)
            or not files
            or any(
                not isinstance(item, dict)
                or not isinstance(item.get("path"), str)
                or not item["path"].strip()
                or not _valid_sha256(item.get("sha256"))
                for item in files
            )
        ):
            reasons.append("source_file_evidence_missing")

    candidates = report.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("validation report candidates must be a list")
    matching = [row for row in candidates if isinstance(row, dict) and row.get("candidate_id") == candidate_id]
    if len(matching) != 1:
        raise ValueError("candidate_id must identify exactly one validation candidate")
    candidate = matching[0]

    windows = candidate.get("windows")
    if not isinstance(windows, list):
        raise ValueError("candidate windows must be a list")
    complete_windows = [window for window in windows if isinstance(window, dict) and window.get("complete") is True]
    if not complete_windows:
        reasons.append("no_complete_causal_validation_window")
    elif any(
        not isinstance(window.get("matured_event_count"), int)
        or not isinstance(window.get("matured_active_days"), int)
        or not isinstance(window.get("summary"), dict)
        or window["summary"].get("n") != window["matured_event_count"]
        or window["matured_event_count"] <= 0
        or window["matured_active_days"] <= 0
        for window in complete_windows
    ):
        reasons.append("causal_window_evidence_inconsistent")

    summary = candidate.get("summary")
    candidate_n = summary.get("n") if isinstance(summary, dict) else None
    if not isinstance(candidate_n, int) or candidate_n <= 0:
        reasons.append("no_matured_candidate_outcomes")
    else:
        source_provenance = candidate.get("source_provenance")
        return_provenance = candidate.get("return_provenance")
        cost_provenance = candidate.get("cost_provenance")
        evidence_counts = (
            source_provenance.get("unique_records") if isinstance(source_provenance, dict) else None,
            return_provenance.get("observations_recomputed") if isinstance(return_provenance, dict) else None,
            cost_provenance.get("observations") if isinstance(cost_provenance, dict) else None,
        )
        if any(value != candidate_n for value in evidence_counts):
            reasons.append("candidate_evidence_count_mismatch")

    report_count = report.get("observation_count")
    if isinstance(candidates, list) and isinstance(report_count, int):
        candidate_counts = []
        for row in candidates:
            row_summary = row.get("summary") if isinstance(row, dict) else None
            n = row_summary.get("n") if isinstance(row_summary, dict) else None
            if not isinstance(n, int) or n < 0:
                candidate_counts = []
                break
            candidate_counts.append(n)
        if not candidate_counts or sum(candidate_counts) != report_count:
            reasons.append("report_observation_count_mismatch")
    else:
        reasons.append("report_observation_count_mismatch")

    if economics.monthly_fixed_cost > 0:
        reasons.append("fixed_operating_cost_not_mapped_to_validated_currency_pnl")

    economics_report = economics.report()
    return PromotionAssessment(
        candidate_id=candidate_id,
        promotable=not reasons,
        research_only=bool(reasons),
        reasons=tuple(reasons),
        validation_report_sha256=_canonical_sha256(report),
        economics_sha256=_canonical_sha256(economics_report),
        monthly_fixed_cost=economics.monthly_fixed_cost,
        monthly_cost_hurdle_fraction=economics.monthly_cost_hurdle_fraction,
        source_files_reverified=False,
    )


def assess_candidate_promotion_files(
    validation_report_path: str | Path,
    candidate_id: str,
    economics_path: str | Path,
) -> PromotionAssessment:
    validation_raw = json.loads(Path(validation_report_path).read_text(encoding="utf-8"))
    economics_raw = json.loads(Path(economics_path).read_text(encoding="utf-8"))
    report = _require_dict(validation_raw, "validation report must be an object")
    economics = load_economics_policy(_require_dict(economics_raw, "economics policy must be an object"))
    assessment = assess_candidate_promotion(report, candidate_id, economics)

    # Re-hashing is required only when the structural/economic gate would otherwise
    # permit promotion. Rejected research artifacts remain rejected without requiring
    # old source files to still be mounted.
    if not assessment.promotable:
        return assessment

    reverify_reasons = _reverify_source_files(report)
    if reverify_reasons:
        return replace(
            assessment,
            promotable=False,
            research_only=True,
            reasons=assessment.reasons + reverify_reasons,
            source_files_reverified=False,
        )
    return replace(assessment, source_files_reverified=True)
