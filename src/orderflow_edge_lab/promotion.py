from __future__ import annotations

from dataclasses import dataclass
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
        }


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _require_dict(value: object, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(message)
    return value


def assess_candidate_promotion(
    validation_report: dict[str, Any],
    candidate_id: str,
    economics: EconomicsPolicy,
) -> PromotionAssessment:
    """Fail-closed strategy promotion gate.

    This intentionally does not infer an edge from descriptive statistics. A candidate
    can pass only when an upstream validation artifact explicitly certifies both
    deployment eligibility and verified out-of-sample evidence. Current project
    validation artifacts deliberately do neither, so they remain research-only.

    Recurring project costs are also a hard gate. Until the validation artifact carries
    a currency-denominated strategy return that can be compared with those fixed costs,
    any non-zero recurring infrastructure cost prevents promotion rather than being
    silently ignored.
    """
    report = _require_dict(validation_report, "validation report must be an object")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError("candidate_id must be a nonempty string")
    candidate_id = candidate_id.strip()

    reasons: list[str] = []
    if report.get("deployment_eligible") is not True:
        reasons.append("validation_report_not_deployment_eligible")
    if report.get("verified_out_of_sample_evidence") is not True:
        reasons.append("out_of_sample_edge_not_verified")

    source = report.get("source_verification")
    if not isinstance(source, dict) or source.get("verified_against_local_files") is not True:
        reasons.append("source_bytes_not_locally_verified")

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

    summary = candidate.get("summary")
    if not isinstance(summary, dict) or not isinstance(summary.get("n"), int) or summary.get("n", 0) <= 0:
        reasons.append("no_matured_candidate_outcomes")

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
    )


def assess_candidate_promotion_files(
    validation_report_path: str | Path,
    candidate_id: str,
    economics_path: str | Path,
) -> PromotionAssessment:
    validation_raw = json.loads(Path(validation_report_path).read_text(encoding="utf-8"))
    economics_raw = json.loads(Path(economics_path).read_text(encoding="utf-8"))
    economics = load_economics_policy(_require_dict(economics_raw, "economics policy must be an object"))
    return assess_candidate_promotion(
        _require_dict(validation_raw, "validation report must be an object"),
        candidate_id,
        economics,
    )
