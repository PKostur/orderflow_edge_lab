"""Discovery-time economics screen.

Two things are wrong with screening candidates on gross or in-sample PnL and
checking friction later, at validation time:

1. a candidate that cannot pay for its own round trip is dead on arrival, and
   finding that out after a full validation window wastes the window;
2. the frozen round-trip cost is a constant typed into a config, while the
   capture stream already records the spread and depth needed to *measure* it.

So this module does two jobs and nothing else:

* ``cost_screen`` -- would the candidate clear the declared round-trip cost, and
  how much headroom does it have? The screen threshold is a **required
  argument**: the tool invents no threshold, and the caller must have declared
  one before running the screen.
* ``measured_friction`` / ``compare_declared_vs_measured`` -- estimate the round
  trip from observed spreads and fees, and flag it when the declared cost sits
  *below* what the market charged. Tightening a cost assumption is allowed;
  weakening one is not, so a shortfall is an error, not a note.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from orderflow_edge_lab.discovery_v2_evaluation import cost_surface

DEFAULT_MULTIPLIERS: tuple[float, ...] = (1.0, 1.5, 2.0, 3.0)

SCREEN_CLEARS = "clears_declared_screen"
SCREEN_FAILS = "fails_declared_screen"
SCREEN_INDETERMINATE = "indeterminate"

_SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2}


class DiscoveryScreenError(ValueError):
    """Raised when a screen input cannot be read or is malformed."""


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_observation_rows(path: Path | str) -> list[dict[str, Any]]:
    """Read observations from JSON-lines or a JSON array.

    Each row needs ``gross_bps`` and ``cost_bps``. ``net_bps`` alone is not
    enough: the screen has to separate what the strategy earned from what the
    market charged.
    """

    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise DiscoveryScreenError(f"cannot read observations: {target}") from exc

    rows: list[dict[str, Any]] = []
    stripped = text.lstrip()
    if stripped.startswith("["):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise DiscoveryScreenError(f"observations are not valid JSON: {target}") from exc
        if not isinstance(payload, list):
            raise DiscoveryScreenError("JSON observations must be an array")
        rows = [dict(row) for row in payload if isinstance(row, Mapping)]
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DiscoveryScreenError(f"observation line is not valid JSON: {exc}") from exc
            if isinstance(payload, Mapping):
                rows.append(dict(payload))

    if not rows:
        raise DiscoveryScreenError(f"no observations in {target}")
    for index, row in enumerate(rows, start=1):
        for key in ("gross_bps", "cost_bps"):
            value = row.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                raise DiscoveryScreenError(f"row {index} needs a finite numeric {key}")
    return rows


def cost_screen(
    rows: Sequence[Mapping[str, Any]],
    *,
    minimum_break_even_ratio: float,
    multipliers: Sequence[float] = DEFAULT_MULTIPLIERS,
) -> dict[str, Any]:
    """Report whether the candidate clears the caller's declared economics screen.

    ``minimum_break_even_ratio`` is required and must have been declared before
    the screen ran. The tool supplies no default.
    """

    if not isinstance(minimum_break_even_ratio, (int, float)) or isinstance(minimum_break_even_ratio, bool):
        raise DiscoveryScreenError("minimum_break_even_ratio must be a number declared by the caller")
    if float(minimum_break_even_ratio) <= 0.0:
        raise DiscoveryScreenError("minimum_break_even_ratio must be positive")
    if not rows:
        raise DiscoveryScreenError("no observations to screen")

    gross = [float(row["gross_bps"]) for row in rows]
    cost = [float(row["cost_bps"]) for row in rows]
    surface = cost_surface(gross, cost, list(multipliers))
    ratio = float(surface["break_even_to_base_cost_ratio"])
    base_net = float(surface["cases"][str(float(multipliers[0]))]["mean_net_bps"])

    if not math.isfinite(ratio):
        status = SCREEN_INDETERMINATE
        detail = "the paid cost is zero across every observation, so a break-even ratio is undefined"
    elif ratio >= float(minimum_break_even_ratio) and base_net > 0.0:
        status = SCREEN_CLEARS
        detail = "gross mean covers the declared multiple of paid friction"
    else:
        status = SCREEN_FAILS
        detail = "gross mean does not cover the declared multiple of paid friction"

    return {
        "screen_threshold_supplied_by_caller": True,
        "minimum_break_even_ratio": float(minimum_break_even_ratio),
        "observations": len(rows),
        "break_even_round_trip_cost_bps": float(surface["break_even_round_trip_cost_bps"]),
        "base_mean_cost_bps": float(surface["base_mean_cost_bps"]),
        "break_even_to_base_cost_ratio": ratio if math.isfinite(ratio) else None,
        "mean_net_bps_at_base_cost": base_net,
        "cases": surface["cases"],
        "screen_status": status,
        "detail": detail,
        "note": (
            "A discovery-time screen, not a promotion rule. It exists so that a candidate which cannot "
            "pay for its own friction is rejected before a validation window is spent on it."
        ),
    }


def spread_bps(row: Mapping[str, Any], *, spread_field: str = "spread_bps") -> float | None:
    """Read a quoted spread in bps from either a direct field or a bid/ask pair."""

    direct = row.get(spread_field)
    if isinstance(direct, (int, float)) and not isinstance(direct, bool) and math.isfinite(float(direct)):
        return float(direct)
    bid = row.get("bid")
    ask = row.get("ask")
    if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and not isinstance(bid, bool):
        bid_value = float(bid)
        ask_value = float(ask)
        mid = (bid_value + ask_value) / 2.0
        if mid > 0.0 and ask_value >= bid_value:
            return (ask_value - bid_value) / mid * 10_000.0
    return None


def measured_friction(
    rows: Iterable[Mapping[str, Any]],
    *,
    fee_bps_per_side: float,
    spread_field: str = "spread_bps",
) -> dict[str, Any]:
    """Estimate round-trip friction from observed spreads plus declared fees.

    A round trip crosses the spread once (half on entry, half on exit) and pays a
    fee per side, so the estimate is ``spread_bps + 2 * fee_bps_per_side``. The
    spread statistics are descriptive quantiles of what the capture actually
    recorded; no trading assumption is added on top.
    """

    if not isinstance(fee_bps_per_side, (int, float)) or isinstance(fee_bps_per_side, bool):
        raise DiscoveryScreenError("fee_bps_per_side must be a number declared by the caller")
    if float(fee_bps_per_side) < 0.0:
        raise DiscoveryScreenError("fee_bps_per_side cannot be negative")

    spreads: list[float] = []
    skipped = 0
    for row in rows:
        value = spread_bps(row, spread_field=spread_field)
        if value is None or not math.isfinite(value) or value < 0.0:
            skipped += 1
            continue
        spreads.append(value)

    if not spreads:
        return {
            "status": "no_usable_spreads",
            "quotes": 0,
            "skipped_quotes": skipped,
            "spread_field": spread_field,
        }

    ordered = sorted(spreads)
    median_spread = statistics.median(ordered)
    p90 = ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]
    return {
        "status": "ok",
        "quotes": len(ordered),
        "skipped_quotes": skipped,
        "spread_field": spread_field,
        "median_spread_bps": median_spread,
        "mean_spread_bps": statistics.fmean(ordered),
        "p90_spread_bps": p90,
        "fee_bps_per_side": float(fee_bps_per_side),
        "estimated_round_trip_cost_bps": median_spread + 2.0 * float(fee_bps_per_side),
        "conservative_round_trip_cost_bps": p90 + 2.0 * float(fee_bps_per_side),
        "note": "Round trip crosses the spread once and pays a fee per side; quantiles are of recorded quotes.",
    }


def compare_declared_vs_measured(
    *,
    declared_round_trip_cost_bps: float,
    measured: Mapping[str, Any],
) -> dict[str, Any]:
    """Flag a declared cost that sits below what the market charged."""

    if measured.get("status") != "ok":
        return {
            "status": "not_compared",
            "detail": f"measured friction unavailable: {measured.get('status')}",
            "findings": [],
        }
    estimate = float(measured["estimated_round_trip_cost_bps"])
    declared = float(declared_round_trip_cost_bps)
    delta = declared - estimate
    if delta < 0.0:
        status = "declared_cost_below_measured"
        severity = "error"
        detail = (
            "the declared round-trip cost is below the measured estimate; realistic friction assumptions "
            "must not be weakened, so a candidate screened at the declared cost is screened against a cost "
            "the market did not offer"
        )
    elif abs(delta) <= 1e-9:
        status = "declared_cost_matches_measured"
        severity = "info"
        detail = "the declared round-trip cost matches the measured estimate"
    else:
        status = "declared_cost_above_measured"
        severity = "info"
        detail = "the declared round-trip cost is more conservative than the measured estimate"
    return {
        "status": status,
        "declared_round_trip_cost_bps": declared,
        "measured_estimated_round_trip_cost_bps": estimate,
        "measured_conservative_round_trip_cost_bps": measured.get("conservative_round_trip_cost_bps"),
        "delta_bps": delta,
        "findings": [
            {
                "severity": severity,
                "code": status,
                "detail": detail,
            }
        ],
    }


def build_discovery_screen(
    rows: Sequence[Mapping[str, Any]],
    *,
    declared_round_trip_cost_bps: float,
    minimum_break_even_ratio: float,
    multipliers: Sequence[float] = DEFAULT_MULTIPLIERS,
    friction_rows: Iterable[Mapping[str, Any]] | None = None,
    fee_bps_per_side: float | None = None,
    spread_field: str = "spread_bps",
) -> dict[str, Any]:
    """Build the combined screen report."""

    screen = cost_screen(rows, minimum_break_even_ratio=minimum_break_even_ratio, multipliers=multipliers)
    friction: dict[str, Any]
    comparison: dict[str, Any]
    if friction_rows is not None:
        if fee_bps_per_side is None:
            raise DiscoveryScreenError("fee_bps_per_side is required when friction quotes are supplied")
        friction = measured_friction(friction_rows, fee_bps_per_side=fee_bps_per_side, spread_field=spread_field)
        comparison = compare_declared_vs_measured(
            declared_round_trip_cost_bps=float(declared_round_trip_cost_bps),
            measured=friction,
        )
    else:
        friction = {"status": "not_supplied"}
        comparison = {
            "status": "not_compared",
            "detail": "no measured friction quotes were supplied",
            "findings": [],
        }

    findings = list(comparison.get("findings", []))
    if screen["screen_status"] == SCREEN_FAILS:
        findings.append(
            {
                "severity": "warning",
                "code": "candidate_fails_declared_economics_screen",
                "detail": "the candidate does not clear the caller-declared break-even multiple",
            }
        )

    highest = max((finding["severity"] for finding in findings), key=lambda s: _SEVERITY_ORDER[s], default="info")
    report = {
        "schema_version": 1,
        "analysis": "discovery_time_economics_screen",
        "declared_round_trip_cost_bps": float(declared_round_trip_cost_bps),
        "screen": screen,
        "measured_friction": friction,
        "declared_vs_measured": comparison,
        "findings": findings,
        "highest_severity": highest,
        "screen_ok": not any(finding["severity"] == "error" for finding in findings),
        "threshold_policy": "every threshold in this report was supplied by the caller and recorded verbatim",
        "claims": {
            "changes_cost_assumptions": False,
            "counts_prospective_batches": False,
            "computes_strategy_verdicts": False,
            "promotes_strategy": False,
            "live_order_transmission_supported": False,
        },
    }
    report["report_sha256"] = _canonical_sha256(report)
    return report


def discovery_screen_markdown(report: Mapping[str, Any]) -> str:
    """Render the screen report."""

    screen = report["screen"]
    lines = [
        "# Discovery-time economics screen",
        "",
        f"- Screen status: `{screen['screen_status']}` — {screen['detail']}",
        f"- Declared round-trip cost: {report['declared_round_trip_cost_bps']} bps; "
        f"caller-declared minimum break-even ratio: {screen['minimum_break_even_ratio']}",
        f"- Observations: {screen['observations']}; break-even cost "
        f"{screen['break_even_round_trip_cost_bps']:.4f} bps; ratio `{screen['break_even_to_base_cost_ratio']}`",
        f"- Mean net at base cost: {screen['mean_net_bps_at_base_cost']:.4f} bps",
        "",
        "## Cost cases",
        "",
    ]
    for multiplier, case in sorted(screen["cases"].items()):
        lines.append(
            f"- x{multiplier}: mean net {case['mean_net_bps']:.4f} bps, "
            f"median {case['median_net_bps']:.4f} bps, positive fraction {case['positive_fraction']:.4f}"
        )
    friction = report["measured_friction"]
    lines += ["", "## Measured friction", ""]
    if friction.get("status") != "ok":
        lines.append(f"- Not available: `{friction.get('status')}`")
    else:
        lines.append(
            f"- {friction['quotes']} quotes ({friction['skipped_quotes']} skipped): median spread "
            f"{friction['median_spread_bps']:.4f} bps, p90 {friction['p90_spread_bps']:.4f} bps, fee "
            f"{friction['fee_bps_per_side']} bps per side"
        )
        lines.append(
            f"- Estimated round trip {friction['estimated_round_trip_cost_bps']:.4f} bps "
            f"(conservative {friction['conservative_round_trip_cost_bps']:.4f} bps)"
        )
    comparison = report["declared_vs_measured"]
    lines += ["", f"- Declared vs measured: `{comparison['status']}` — {comparison.get('detail')}", ""]
    lines += ["## Findings", ""]
    if not report["findings"]:
        lines.append("- None.")
    for finding in report["findings"]:
        lines.append(f"- `{finding['severity']}` `{finding['code']}` — {finding['detail']}")
    lines.append("")
    return "\n".join(lines)
