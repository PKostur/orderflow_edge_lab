"""Causal ablation evaluation for the isolated multi-agent trading trial.

Realized outcomes are supplied only after each frozen MarketSnapshot has been evaluated.
They are never exposed to the agents. This module is descriptive research tooling only:
it cannot transmit orders and never marks a configuration deployment-eligible.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from statistics import mean
from typing import Iterable

from experiments.multi_agent_trial.engine import (
    Agent,
    LimitAgent,
    MarketSnapshot,
    ProbeAgent,
    RegimeAgent,
    RiskAgent,
    SkepticAgent,
    TrialCoordinator,
)

UTC = timezone.utc


@dataclass(frozen=True)
class RealizedObservation:
    snapshot: MarketSnapshot
    outcome_time: str
    realized_net_r: float


@dataclass(frozen=True)
class TrialVariant:
    name: str
    agents: tuple[Agent, ...] | None

    def agent_names(self) -> list[str]:
        return [] if self.agents is None else [agent.name for agent in self.agents]


def default_variants() -> tuple[TrialVariant, ...]:
    """Progressive ablations. Baseline accepts every supplied candidate."""
    return (
        TrialVariant("baseline", None),
        TrialVariant("probe", (ProbeAgent(),)),
        TrialVariant("probe_prism", (ProbeAgent(), RegimeAgent())),
        TrialVariant("probe_prism_limit", (ProbeAgent(), RegimeAgent(), LimitAgent())),
        TrialVariant(
            "full",
            (ProbeAgent(), RegimeAgent(), RiskAgent(), LimitAgent(), SkepticAgent()),
        ),
    )


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return dt.astimezone(UTC)


def _finite_number(value: object, name: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _summary(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean_r": None, "total_r": 0.0, "win_rate": None}
    return {
        "n": len(values),
        "mean_r": mean(values),
        "total_r": sum(values),
        "win_rate": sum(value > 0 for value in values) / len(values),
    }


def _evidence_fingerprint(observations: list[RealizedObservation]) -> str:
    payload = [
        {
            "snapshot": asdict(item.snapshot),
            "outcome_time": _parse_utc(item.outcome_time).isoformat(),
            "realized_net_r": item.realized_net_r,
        }
        for item in observations
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evaluate_ablation(
    observations: Iterable[RealizedObservation],
    *,
    variants: tuple[TrialVariant, ...] | None = None,
) -> dict:
    """Compare deterministic gate combinations on one chronological realized sample.

    The input order is treated as evidence. It is validated and never silently sorted.
    A rejected candidate remains in the report so veto opportunity cost is measurable.
    """
    rows = list(observations)
    selected_variants = variants or default_variants()
    if not selected_variants:
        raise ValueError("at least one variant is required")
    names = [variant.name for variant in selected_variants]
    if any(not isinstance(name, str) or not name.strip() for name in names) or len(set(names)) != len(names):
        raise ValueError("variant names must be unique nonempty strings")

    seen_ids: set[str] = set()
    previous_event: datetime | None = None
    validated: list[tuple[RealizedObservation, float]] = []
    for item in rows:
        if not isinstance(item, RealizedObservation):
            raise ValueError("observations must be RealizedObservation instances")
        item.snapshot.validate()
        event_time = _parse_utc(item.snapshot.event_time)
        outcome_time = _parse_utc(item.outcome_time)
        if outcome_time <= event_time:
            raise ValueError("outcome_time must be strictly after snapshot event_time")
        if previous_event is not None and event_time < previous_event:
            raise ValueError("observations must be chronological; input is never silently sorted")
        previous_event = event_time
        if item.snapshot.snapshot_id in seen_ids:
            raise ValueError("duplicate snapshot_id")
        seen_ids.add(item.snapshot.snapshot_id)
        validated.append((item, _finite_number(item.realized_net_r, "realized_net_r")))

    variant_reports = []
    for variant in selected_variants:
        accepted: list[float] = []
        rejected: list[float] = []
        verdict_counts = {"PASS": 0, "REJECT": 0, "PENDING": 0}
        rejection_by_agent: dict[str, int] = {}

        coordinator = TrialCoordinator(variant.agents) if variant.agents is not None else None
        for item, realized in validated:
            if coordinator is None:
                verdict = "PASS"
                decisions = ()
            else:
                result = coordinator.evaluate(item.snapshot)
                verdict = result.final_verdict
                decisions = result.decisions
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
            if verdict == "PASS":
                accepted.append(realized)
            else:
                rejected.append(realized)
                for decision in decisions:
                    if decision.verdict == "VETO":
                        rejection_by_agent[decision.agent] = rejection_by_agent.get(decision.agent, 0) + 1

        count = len(validated)
        variant_reports.append(
            {
                "name": variant.name,
                "agents": variant.agent_names(),
                "candidate_count": count,
                "accepted_count": len(accepted),
                "rejected_count": len(rejected),
                "acceptance_rate": (len(accepted) / count) if count else None,
                "verdict_counts": verdict_counts,
                "rejection_by_agent": dict(sorted(rejection_by_agent.items())),
                "accepted_summary": _summary(accepted),
                "rejected_summary": _summary(rejected),
            }
        )

    variant_config = [
        {"name": variant.name, "agents": variant.agent_names()}
        for variant in selected_variants
    ]
    variant_sha = hashlib.sha256(
        json.dumps(variant_config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 1,
        "audit_type": "multi_agent_ablation",
        "observation_count": len(validated),
        "evidence_sha256": _evidence_fingerprint([item for item, _ in validated]),
        "variant_config_sha256": variant_sha,
        "variants": variant_reports,
        "deployment_eligible": False,
        "verified_out_of_sample_evidence": False,
        "limitations": [
            "This report is descriptive and does not establish profitability, statistical significance, or executable fills.",
            "Realized outcomes are used only for post-decision scoring and are not exposed to agents.",
            "Ablation results are only out-of-sample if the evaluated observations were genuinely unseen after all tested rules and thresholds were frozen.",
            "Repeated experimentation on the same evaluation sample can turn it into training data and invalidate an out-of-sample interpretation.",
        ],
    }
