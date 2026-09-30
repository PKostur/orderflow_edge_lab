"""Pre-registration contract for prospective watches.

A watch is only as good as what it fixed before the window opened. Two real gaps
motivated this module:

* ``config/evidence_v2_session_forward_watch_v1.json`` declares which metrics the
   2026-10-23 review must report, but no numeric threshold for any of them.
* the session watches declare batch/day/signal counts, which are dependence
   guards rather than decision rules.

This module does **not** retrofit thresholds onto either one -- inventing a
numeric rule after the window opened is the exact failure the repository forbids.
Instead it:

* describes, mechanically, whether a watch config carries a complete numeric
  decision rule, a declared trial family, and a declared design (dependence
  cluster plus the effect size the gate could resolve);
* audits every registered watch against that contract, reporting an
  *acknowledged gap* as a warning and an undeclared gap as an error;
* states the contract that future watches must satisfy.

Adding a numeric rule to an already-frozen watch remains a versioned change for a
new watch, never a patch to the old one.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

DEFAULT_REGISTRY = Path("config/preregistration_registry_v1.json")

REQUIRED_DECISION_RULE_FIELDS = ("metric", "direction", "threshold", "inconclusive_when")
REQUIRED_DESIGN_FIELDS = ("dependence_cluster", "design_effect_bps", "design_units")

_SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2}

STATUS_PRE_REGISTERED = "pre_registered_numeric_thresholds"
STATUS_REVIEW_RULE_THRESHOLDS = "pre_registered_thresholds_in_review_rule"
STATUS_GATES_ONLY = "dependence_gates_only"
STATUS_METRICS_WITHOUT_THRESHOLDS = "declared_metrics_without_numeric_thresholds"
STATUS_INCOMPLETE = "incomplete_decision_rule"
STATUS_ABSENT = "no_decision_rule_declared"

#: Statuses that count as carrying a pre-registered decision rule. The three
#: frozen shapes in this repository are all legitimate; only their *absence* is
#: the finding.
COMPLIANT_STATUSES = (STATUS_PRE_REGISTERED, STATUS_REVIEW_RULE_THRESHOLDS)

SHAPE_CANONICAL = "canonical_decision_rule"
SHAPE_REVIEW_RULE = "review_rule_numeric_thresholds"
SHAPE_GATES_ONLY = "dependence_gates_only"
SHAPE_METRICS_ONLY = "declared_metrics_only"
SHAPE_INCOMPLETE = "incomplete_decision_rule"
SHAPE_ABSENT = "absent"


class PreregistrationError(ValueError):
    """Raised when a registry or watch config cannot be read."""


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_object(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PreregistrationError(f"cannot read JSON object: {target}") from exc
    except json.JSONDecodeError as exc:
        raise PreregistrationError(f"invalid JSON: {target}") from exc
    if not isinstance(payload, dict):
        raise PreregistrationError(f"JSON must be an object: {target}")
    return payload


def load_registry(path: Path | str = DEFAULT_REGISTRY) -> dict[str, Any]:
    """Load and structurally validate the pre-registration registry."""

    payload = _load_object(path)
    if payload.get("schema_version") != 1:
        raise PreregistrationError("registry schema_version must be 1")
    watches = payload.get("watches")
    if not isinstance(watches, list) or not watches:
        raise PreregistrationError("registry must declare at least one watch")
    for entry in watches:
        if not isinstance(entry, Mapping):
            raise PreregistrationError("every registry watch entry must be an object")
        if not entry.get("watch_id") or not entry.get("config_path"):
            raise PreregistrationError("every registry watch entry needs watch_id and config_path")
    return payload


def _declared_metrics(config: Mapping[str, Any]) -> list[str]:
    """Collect every metric list a watch config spells out, in declaration order."""

    metrics: list[str] = []
    reporting = config.get("reporting")
    if isinstance(reporting, Mapping) and isinstance(reporting.get("metrics"), list):
        metrics.extend(str(item) for item in reporting["metrics"])
    for key in ("primary_review_metrics", "secondary_review_metrics"):
        value = config.get(key)
        if isinstance(value, list):
            metrics.extend(str(item) for item in value)
    for container in ("prospective_review_requirement",):
        value = config.get(container)
        if isinstance(value, Mapping) and isinstance(value.get("evaluate"), list):
            metrics.extend(str(item) for item in value["evaluate"])
    seen: set[str] = set()
    ordered: list[str] = []
    for metric in metrics:
        if metric not in seen:
            seen.add(metric)
            ordered.append(metric)
    return ordered


def _numeric_gates(config: Mapping[str, Any]) -> dict[str, float]:
    """Numeric data-volume gates (batches, days, signals) -- not outcome thresholds.

    ``reporting.review_after_calendar_days`` is deliberately *not* a gate here:
    it says when a review is due, not how much evidence must accumulate.
    """

    gates: dict[str, float] = {}
    for container in ("minimum_review_target", "prospective_review_requirement"):
        value = config.get(container)
        if isinstance(value, Mapping):
            for key, item in value.items():
                if isinstance(item, (int, float)) and not isinstance(item, bool):
                    gates[f"{container}.{key}"] = float(item)
    return gates


def _review_rule_thresholds(config: Mapping[str, Any]) -> dict[str, float]:
    """Numeric outcome thresholds declared in a ``review_rule`` block.

    This is the shape used by ``config/session_watch_cvd_lny_v1.json``: a set of
    inequality requirements, some of them expressed as a numeric bound
    (``profit_factor_requires_above: 1.0``) and some as a boolean that embeds the
    bound in its own key (``primary_endpoint_requires_positive_cumulative_net_at_4bps``).
    """

    rule = config.get("review_rule")
    if not isinstance(rule, Mapping):
        return {}
    thresholds = {
        str(key): float(value)
        for key, value in rule.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    if not thresholds:
        return {}
    has_requirement = any(value is True and "requires" in str(key) for key, value in rule.items())
    return thresholds if has_requirement else {}


def describe_decision_rule(config: Mapping[str, Any]) -> dict[str, Any]:
    """Report what a watch config actually fixes, without judging it.

    Three pre-registered shapes exist in this repository and all three are
    legitimate:

    ``pre_registered_numeric_thresholds``
        A complete canonical ``decision_rule`` block.
    ``pre_registered_thresholds_in_review_rule``
        A ``review_rule`` block carrying numeric bounds and requirement flags
        together with a declared metric list.
    ``dependence_gates_only``
        Numeric gates on how much data must accumulate (batches, days, signals)
        plus a metric list, but no threshold on the outcome itself. These gates
        are dependence guards, not decision rules.

    A config that declares metrics but nothing numeric at all is reported as
    ``declared_metrics_without_numeric_thresholds``. That is the DON8 shape, and
    it is reported, never patched.
    """

    declared_metrics = _declared_metrics(config)
    gates = _numeric_gates(config)
    review_rule_thresholds = _review_rule_thresholds(config)

    rule = config.get("decision_rule")
    missing: list[str] = []
    if isinstance(rule, Mapping):
        missing = [field for field in REQUIRED_DECISION_RULE_FIELDS if rule.get(field) in (None, "")]
        if not missing:
            status = STATUS_PRE_REGISTERED
            shape = SHAPE_CANONICAL
        else:
            status = STATUS_INCOMPLETE
            shape = SHAPE_INCOMPLETE
    elif review_rule_thresholds and declared_metrics:
        status = STATUS_REVIEW_RULE_THRESHOLDS
        shape = SHAPE_REVIEW_RULE
    elif gates and declared_metrics:
        status = STATUS_GATES_ONLY
        shape = SHAPE_GATES_ONLY
        missing = list(REQUIRED_DECISION_RULE_FIELDS)
    elif declared_metrics:
        status = STATUS_METRICS_WITHOUT_THRESHOLDS
        shape = SHAPE_METRICS_ONLY
        missing = list(REQUIRED_DECISION_RULE_FIELDS)
    else:
        status = STATUS_ABSENT
        shape = SHAPE_ABSENT
        missing = list(REQUIRED_DECISION_RULE_FIELDS)

    design = config.get("design")
    if isinstance(design, Mapping):
        design_missing = [field for field in REQUIRED_DESIGN_FIELDS if design.get(field) in (None, "")]
    else:
        design_missing = list(REQUIRED_DESIGN_FIELDS)

    trial_family = None
    reporting = config.get("reporting")
    for candidate in (
        config.get("trial_family"),
        reporting.get("trial_family") if isinstance(reporting, Mapping) else None,
        config.get("family"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            trial_family = candidate.strip()
            break

    thresholds = {
        key: value
        for key, value in (review_rule_thresholds or (rule if isinstance(rule, Mapping) else {})).items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    return {
        "decision_rule_status": status,
        "decision_rule_shape": shape,
        "has_pre_registered_decision_rule": status in COMPLIANT_STATUSES,
        "numeric_thresholds_present": status in COMPLIANT_STATUSES,
        "declared_thresholds": {str(key): float(value) for key, value in thresholds.items()},
        "declared_metrics": declared_metrics,
        "declared_data_volume_gates": gates,
        "missing_decision_rule_fields": missing,
        "design_status": "declared" if not design_missing else "incomplete_or_absent",
        "missing_design_fields": design_missing,
        "trial_family": trial_family,
    }


def _acknowledged_gap_status(entry: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    gap = entry.get("acknowledged_gap")
    if not isinstance(gap, Mapping):
        return False, {}
    if not gap.get("reason") or not gap.get("recorded_at_utc"):
        return False, dict(gap)
    return True, dict(gap)


def audit_preregistration(
    registry: Mapping[str, Any],
    *,
    repo_root: Path | str = Path("."),
) -> dict[str, Any]:
    """Audit every registered watch against the pre-registration contract."""

    root = Path(repo_root)
    findings: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    seen: dict[str, str] = {}

    for entry in registry.get("watches", []):
        watch_id = str(entry["watch_id"])
        config_path = str(entry["config_path"])
        if watch_id in seen:
            findings.append(
                {
                    "severity": "error",
                    "code": "registry_entry_duplicate",
                    "watch_id": watch_id,
                    "detail": f"watch_id appears twice ({seen[watch_id]} and {config_path})",
                }
            )
            continue
        seen[watch_id] = config_path

        acknowledged, gap = _acknowledged_gap_status(entry)
        frozen = bool(entry.get("frozen"))
        target = root / config_path
        if not target.is_file():
            findings.append(
                {
                    "severity": "error",
                    "code": "config_missing",
                    "watch_id": watch_id,
                    "detail": f"declared config does not exist: {config_path}",
                }
            )
            records.append(
                {
                    "watch_id": watch_id,
                    "config_path": config_path,
                    "config_found": False,
                    "acknowledged_gap": acknowledged,
                }
            )
            continue

        config = _load_object(target)
        description = describe_decision_rule(config)
        record = {
            "watch_id": watch_id,
            "config_path": config_path,
            "config_found": True,
            "frozen": frozen,
            "config_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "acknowledged_gap": acknowledged,
            "acknowledged_gap_record": gap or None,
            **description,
        }
        records.append(record)

        # Severity rule: a gap in an already-frozen watch cannot be repaired
        # without changing the frozen definition, so it is a documented warning.
        # The same gap in a watch that is not yet frozen is still fixable and is
        # therefore an error that fails the hygiene gate.
        severity = "warning" if (frozen or acknowledged) else "error"
        suffix = "" if severity == "error" else "_in_frozen_watch"

        if acknowledged:
            findings.append(
                {
                    "severity": "info",
                    "code": "acknowledged_gap_recorded",
                    "watch_id": watch_id,
                    "detail": (
                        f"gap recorded {gap.get('recorded_at_utc')} in "
                        f"{gap.get('canonical_record')}: {str(gap.get('reason'))[:160]}"
                    ),
                }
            )

        if not description["has_pre_registered_decision_rule"]:
            code = {
                STATUS_INCOMPLETE: f"decision_rule_incomplete{suffix}",
            }.get(description["decision_rule_status"], f"decision_rule_missing{suffix}")
            findings.append(
                {
                    "severity": severity,
                    "code": code,
                    "watch_id": watch_id,
                    "detail": (
                        f"{description['decision_rule_status']}: missing "
                        f"{', '.join(description['missing_decision_rule_fields'])}"
                    ),
                }
            )
        if description["trial_family"] is None:
            findings.append(
                {
                    "severity": severity,
                    "code": f"trial_family_missing{suffix}",
                    "watch_id": watch_id,
                    "detail": "no trial_family declared; multiplicity cannot be adjusted for this watch",
                }
            )
        if description["design_status"] != "declared":
            findings.append(
                {
                    "severity": severity,
                    "code": f"design_block_missing{suffix}",
                    "watch_id": watch_id,
                    "detail": (
                        "no design block (dependence_cluster, design_effect_bps, design_units); "
                        "the smallest resolvable effect at the frozen gate is undocumented"
                    ),
                }
            )

    highest = max((finding["severity"] for finding in findings), key=lambda s: _SEVERITY_ORDER[s], default="info")
    report = {
        "schema_version": 1,
        "analysis": "watch_preregistration_audit",
        "registry_path": str(registry.get("registry_path", DEFAULT_REGISTRY)),
        "registry_version": registry.get("version"),
        "watches_total": len(registry.get("watches", [])),
        "compliant_count": sum(1 for record in records if record.get("has_pre_registered_decision_rule")),
        "acknowledged_gap_count": sum(1 for record in records if record.get("acknowledged_gap")),
        "frozen_watch_count": sum(1 for record in records if record.get("frozen")),
        "unfrozen_watch_count": sum(1 for record in records if record.get("config_found") and not record.get("frozen")),
        "future_watch_requirements": registry.get("requirements", {}),
        "watches": records,
        "findings": findings,
        "highest_severity": highest,
        "audit_ok": not any(finding["severity"] == "error" for finding in findings),
        "claims": {
            "changes_frozen_definitions": False,
            "retrofits_thresholds_onto_open_windows": False,
            "computes_strategy_verdicts": False,
            "promotes_strategy": False,
            "live_order_transmission_supported": False,
        },
    }
    report["report_sha256"] = _canonical_sha256(report)
    return report


def preregistration_markdown(report: Mapping[str, Any]) -> str:
    """Render the pre-registration audit for a review packet or step summary."""

    lines = [
        "# Pre-registration audit",
        "",
        f"- Registry version: `{report['registry_version']}`",
        f"- Watches: {report['watches_total']} ({report['compliant_count']} carry a pre-registered decision rule, "
        f"{report['acknowledged_gap_count']} recorded as acknowledged gaps)",
        f"- Highest severity: `{report['highest_severity']}`; audit ok: `{report['audit_ok']}`",
        "",
        "## Watches",
        "",
        "| Watch | Decision rule shape | Pre-registered thresholds | Acknowledged gap |",
        "|---|---|---|---|",
    ]
    for record in report["watches"]:
        thresholds = record.get("declared_thresholds") or {}
        rendered = ", ".join(f"{key}={value}" for key, value in sorted(thresholds.items())) or "none"
        lines.append(
            f"| `{record['watch_id']}` | `{record.get('decision_rule_shape')}` | {rendered} | "
            f"`{bool(record.get('acknowledged_gap'))}` |"
        )
    lines += ["", "## Findings", ""]
    if not report["findings"]:
        lines.append("- None.")
    for finding in report["findings"]:
        lines.append(f"- `{finding['severity']}` `{finding['code']}` — {finding['detail']}")
    requirements = report.get("future_watch_requirements") or {}
    if requirements:
        lines += [
            "",
            "## Requirements for watches frozen after this registry",
            "",
            f"- Decision rule fields: {', '.join(requirements.get('required_decision_rule_fields', []))}",
            f"- Design fields: {', '.join(requirements.get('required_design_fields', []))}",
            f"- Trial family required: `{requirements.get('required_trial_family')}`",
        ]
    lines.append("")
    return "\n".join(lines)
