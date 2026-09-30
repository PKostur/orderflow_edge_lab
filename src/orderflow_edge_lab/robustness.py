"""Descriptive robustness layer for an already-frozen prospective report.

This module is an **analysis-only** layer. It never re-scores a strategy, never
changes a frozen definition, and computes no verdict. It reads the interval rows
that a frozen forward report already retains and adds the uncertainty,
concentration, friction-sensitivity and negative-control context that the
prospective reports themselves do not carry.

Two rules govern everything here:

1. **The dependence cluster is the resampling unit, not the row.** Rows inside
   one bar/batch are correlated (the same timestamp across ten symbols, the same
   capture session). A row-level bootstrap would understate the interval and
   manufacture significance.
2. **Nothing here is pre-registered for an already-open watch.** Any number this
   module produces is labelled ``post_hoc_descriptive`` and carries
   ``decision_rule_status``. It may appear in a review record only with that
   label, and it may not be used as a pass/fail rule for a watch whose window
   was opened without one.

Reused rather than re-implemented: the block-bootstrap convention, the cost
surface, the concentration diagnostics and the deflated-Sharpe/PBO/reality-check
family diagnostics all come from :mod:`orderflow_edge_lab.discovery_v2_evaluation`.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import warnings
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from orderflow_edge_lab.discovery_v2_evaluation import (
    concentration_diagnostics,
    cost_surface,
    cscv_pbo,
    deflated_sharpe_probability,
    moving_block_bootstrap_mean,
    sharpe_unannualized,
    white_style_reality_check,
)

DEFAULT_ROLE = "PRIMARY_SESSION_HYPOTHESIS"
DEFAULT_CONFIDENCE = 0.95
DEFAULT_RESAMPLES = 4000
DEFAULT_SEED = 29
DEFAULT_COST_MULTIPLIERS: tuple[float, ...] = (1.0, 1.5, 2.0, 3.0)

#: Resampling units. ``bar`` is the corrent unit for an 8h/4h forward report
#: (one timestamp, all symbols). ``day`` is the conservative choice when several
#: bars share a session. ``bucket`` collapses to the session bucket.
CLUSTER_KEYS = ("bar", "day", "bucket")

_MIN_BOOTSTRAP_RESAMPLES = 100


class RobustnessError(ValueError):
    """Raised when a robustness input cannot be read or is malformed."""


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_object(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RobustnessError(f"cannot read report: {target}") from exc
    except json.JSONDecodeError as exc:
        raise RobustnessError(f"report is not valid JSON: {target}") from exc
    if not isinstance(payload, dict):
        raise RobustnessError(f"report must be a JSON object: {target}")
    return payload


def forward_variants(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the variant reports carried inside a frozen forward report."""

    variants = report.get("reports")
    if not isinstance(variants, list) or not variants:
        raise RobustnessError("report has no 'reports' variant list")
    out: list[dict[str, Any]] = []
    for entry in variants:
        if not isinstance(entry, Mapping):
            raise RobustnessError("variant entry is not an object")
        rows = entry.get("interval_rows")
        if not isinstance(rows, list):
            raise RobustnessError(f"variant {entry.get('audit_id')!r} retains no interval_rows")
        out.append(dict(entry))
    return out


def select_variant(
    report: Mapping[str, Any],
    *,
    audit_id: str | None = None,
    role: str = DEFAULT_ROLE,
) -> dict[str, Any]:
    """Select one variant report by audit id, or the first with the given role."""

    variants = forward_variants(report)
    if audit_id is not None:
        for variant in variants:
            if str(variant.get("audit_id")) == audit_id:
                return variant
        raise RobustnessError(f"no variant with audit_id {audit_id!r}")
    for variant in variants:
        if str(variant.get("role")) == role:
            return variant
    raise RobustnessError(f"no variant with role {role!r}")


def interval_observations(
    variant: Mapping[str, Any],
    *,
    cluster: str = "bar",
    bucket: str | None = None,
) -> list[dict[str, Any]]:
    """Normalize a variant's retained interval rows into analysis observations.

    The value analysed is the retained ``portfolio_net_return`` (already after
    the frozen round-trip cost). ``gross_bps`` and ``cost_bps`` are carried
    alongside so the cost surface and the side-reversed control can be computed
    without re-deriving any position.
    """

    if cluster not in CLUSTER_KEYS:
        raise RobustnessError(f"cluster must be one of {CLUSTER_KEYS}")
    rows = variant.get("interval_rows")
    if not isinstance(rows, list) or not rows:
        raise RobustnessError("variant retains no interval rows")

    observations: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise RobustnessError("interval row is not an object")
        name = str(row.get("session_bucket"))
        if bucket is not None and name != bucket:
            continue
        start = str(row.get("start"))
        symbols = row.get("symbol_net_contribution_bps") or {}
        if not isinstance(symbols, Mapping):
            raise RobustnessError("symbol_net_contribution_bps must be an object")
        gross_bps = float(row.get("portfolio_long_gross_bps", 0.0)) + float(row.get("portfolio_short_gross_bps", 0.0))
        key = start
        if cluster == "day":
            key = start[:10]
        elif cluster == "bucket":
            key = name
        observations.append(
            {
                "cluster": key,
                "bar_start_utc": start,
                "session_bucket": name,
                "bps": float(row.get("portfolio_net_return", 0.0)) * 10_000.0,
                "gross_bps": gross_bps,
                "cost_bps": float(row.get("portfolio_turnover_cost_bps", 0.0)),
                "symbol_bps": {str(sym): float(value) for sym, value in symbols.items()},
            }
        )
    if not observations:
        raise RobustnessError("no interval rows matched the requested bucket")
    observations.sort(key=lambda obs: obs["bar_start_utc"])
    return observations


def cluster_units(observations: Sequence[Mapping[str, Any]]) -> list[list[float]]:
    """Group observations into dependence clusters, preserving order."""

    grouped: dict[str, list[float]] = {}
    for observation in observations:
        grouped.setdefault(str(observation["cluster"]), []).append(float(observation["bps"]))
    if not grouped:
        raise RobustnessError("no observations to cluster")
    return [grouped[key] for key in sorted(grouped)]


def cluster_bootstrap_mean(
    units: Sequence[Sequence[float]],
    *,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Bootstrap the observation-weighted mean by resampling whole clusters.

    The point estimate is exactly the frozen report's own statistic
    (mean over intervals). Only the interval around it is new, and it is
    wider than a row-level bootstrap by construction because correlated rows
    move together.
    """

    if not units:
        raise RobustnessError("no clusters to resample")
    if int(resamples) < _MIN_BOOTSTRAP_RESAMPLES:
        raise RobustnessError(f"resamples must be at least {_MIN_BOOTSTRAP_RESAMPLES}")
    if not 0.0 < float(confidence) < 1.0:
        raise RobustnessError("confidence must be between 0 and 1")

    sums = np.asarray([float(np.sum(unit)) for unit in units], dtype=float)
    counts = np.asarray([float(len(unit)) for unit in units], dtype=float)
    total = float(sums.sum())
    observed = total / float(counts.sum())

    rng = np.random.default_rng(int(seed))
    draws = rng.integers(0, len(units), size=(int(resamples), len(units)))
    resampled = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    alpha = 1.0 - float(confidence)
    lower = float(np.quantile(resampled, alpha / 2.0))
    upper = float(np.quantile(resampled, 1.0 - alpha / 2.0))

    cluster_means = [float(np.mean(unit)) for unit in units]
    sd = float(np.std(cluster_means, ddof=1)) if len(cluster_means) > 1 else 0.0
    return {
        "mean_bps": observed,
        "ci_lower_bps": lower,
        "ci_upper_bps": upper,
        "confidence": float(confidence),
        "resamples": int(resamples),
        "seed": int(seed),
        "observation_count": int(counts.sum()),
        "cluster_count": len(units),
        "cluster_mean_std_bps": sd,
        "cluster_mean_standard_error_bps": sd / math.sqrt(len(cluster_means)) if cluster_means else None,
        "interval_excludes_zero": bool(lower > 0.0 or upper < 0.0),
        "interval_entirely_narrower_than_zero": bool(upper < 0.0),
    }


def minimum_detectable_effect(
    units: Sequence[Sequence[float]],
    *,
    design_clusters: int,
    confidence: float = DEFAULT_CONFIDENCE,
) -> dict[str, Any]:
    """Report the smallest mean effect a design of this size could resolve.

    ``design_clusters`` must come from the frozen gate (for example a 30-day
    window at three 8h bars per day is 90 clusters, or 30 day-clusters). This is
    a *design* statement, computed before the window matures: at the frozen gate
    size, an effect smaller than the reported value cannot be concluded on.
    """

    if int(design_clusters) < 2:
        raise RobustnessError("design_clusters must be at least 2")
    cluster_means = [float(np.mean(unit)) for unit in units]
    if len(cluster_means) < 2:
        return {
            "design_clusters": int(design_clusters),
            "cluster_mean_std_bps": None,
            "minimum_detectable_effect_bps": None,
            "status": "insufficient_observed_clusters",
        }
    sd = float(np.std(cluster_means, ddof=1))
    z = statistics.NormalDist().inv_cdf(1.0 - (1.0 - float(confidence)) / 2.0)
    mde = z * sd / math.sqrt(float(int(design_clusters)))
    return {
        "design_clusters": int(design_clusters),
        "cluster_mean_std_bps": sd,
        "observed_clusters": len(cluster_means),
        "minimum_detectable_effect_bps": mde,
        "confidence": float(confidence),
        "status": "ok",
        "note": (
            "Two-sided normal approximation on the observed cluster-level dispersion. "
            "Effects smaller than this cannot be resolved at the frozen gate size."
        ),
    }


def symbol_concentration(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Reuse the discovery-v2 concentration diagnostics over retained symbol rows."""

    import pandas as pd

    records = [
        {
            "symbol": symbol,
            "timestamp": observation["bar_start_utc"],
            "net_return_bps": value,
        }
        for observation in observations
        for symbol, value in dict(observation["symbol_bps"]).items()
    ]
    if not records:
        # A report that carries no per-symbol attribution is not an error; the
        # concentration block simply has nothing to say and says so.
        return {
            "status": "no_symbol_attribution",
            "per_symbol_sum_bps": {},
            "symbol_count": 0,
            "positive_symbol_count": 0,
            "best_symbol_positive_pnl_share": None,
            "top5_positive_pnl_share": None,
            "best_month_positive_pnl_share": None,
            "leave_one_symbol_out_mean_bps": {},
            "minimum_leave_one_symbol_out_mean_bps": None,
        }
    distinct_symbols = sorted({str(record["symbol"]) for record in records})
    if len(distinct_symbols) < 2:
        # The shared concentration helper computes a leave-one-symbol-out mean and
        # needs at least two symbols to do so; with one symbol the honest answer is
        # that the check is not available rather than a crash.
        totals: dict[str, float] = {}
        for record in records:
            totals[str(record["symbol"])] = totals.get(str(record["symbol"]), 0.0) + float(
                record["net_return_bps"]
            )
        return {
            "status": "insufficient_symbols_for_leave_one_out",
            "per_symbol_sum_bps": totals,
            "symbol_count": len(distinct_symbols),
            "positive_symbol_count": sum(1 for value in totals.values() if value > 0.0),
            "best_symbol_positive_pnl_share": None,
            "top5_positive_pnl_share": None,
            "best_month_positive_pnl_share": None,
            "leave_one_symbol_out_mean_bps": {},
            "minimum_leave_one_symbol_out_mean_bps": None,
        }

    frame = pd.DataFrame.from_records(records)
    with warnings.catch_warnings():
        # pandas warns that converting a tz-aware index to monthly periods drops
        # the timezone. The monthly grouping is only used for a positive-PnL share,
        # and the shared frozen implementation is intentionally left untouched.
        warnings.simplefilter("ignore", UserWarning)
        diagnostics = concentration_diagnostics(frame, return_col="net_return_bps")
    return {
        "status": "ok",
        "per_symbol_sum_bps": {
            str(symbol): float(value)
            for symbol, value in diagnostics["per_symbol_sum_bps"].items()
        },
        "symbol_count": len(diagnostics["per_symbol_sum_bps"]),
        "best_symbol_positive_pnl_share": diagnostics["best_symbol_positive_pnl_share"],
        "top5_positive_pnl_share": diagnostics["top5_positive_pnl_share"],
        "best_month_positive_pnl_share": diagnostics["best_calendar_month_positive_pnl_share"],
        "leave_one_symbol_out_mean_bps": {
            str(symbol): value for symbol, value in diagnostics["leave_one_symbol_out_mean_bps"].items()
        },
        "minimum_leave_one_symbol_out_mean_bps": diagnostics["minimum_leave_one_symbol_out_mean_bps"],
        "positive_symbol_count": sum(1 for value in diagnostics["per_symbol_sum_bps"].values() if float(value) > 0.0),
    }


def cost_surface_bps(
    observations: Sequence[Mapping[str, Any]],
    *,
    multipliers: Sequence[float] = DEFAULT_COST_MULTIPLIERS,
) -> dict[str, Any]:
    """Friction sensitivity: reuse the discovery-v2 cost surface on retained rows."""

    gross = np.asarray([float(obs["gross_bps"]) for obs in observations], dtype=float)
    cost = np.asarray([float(obs["cost_bps"]) for obs in observations], dtype=float)
    surface = cost_surface(gross, cost, list(multipliers))
    if not math.isfinite(float(surface["break_even_to_base_cost_ratio"])):
        surface["break_even_to_base_cost_ratio"] = None
    surface["note"] = (
        "Break-even ratio = gross mean bps divided by the mean cost actually paid. "
        "Below 1.0 the strategy does not pay for its own friction; it is a "
        "descriptive sensitivity, not a promotion rule."
    )
    return surface


def control_arm_comparison(
    primary: Sequence[Mapping[str, Any]],
    control: Sequence[Mapping[str, Any]],
    *,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Paired cluster bootstrap of primary minus control on shared timestamps."""

    primary_by_bar = {str(obs["bar_start_utc"]): float(obs["bps"]) for obs in primary}
    control_by_bar = {str(obs["bar_start_utc"]): float(obs["bps"]) for obs in control}
    shared = sorted(set(primary_by_bar) & set(control_by_bar))
    if len(shared) < 2:
        return {
            "shared_clusters": len(shared),
            "difference_mean_bps": None,
            "status": "insufficient_shared_clusters",
        }
    units = [[primary_by_bar[bar] - control_by_bar[bar]] for bar in shared]
    paired = cluster_bootstrap_mean(units, resamples=resamples, confidence=confidence, seed=seed)
    return {
        "shared_clusters": len(shared),
        "difference_mean_bps": paired["mean_bps"],
        "difference_ci_lower_bps": paired["ci_lower_bps"],
        "difference_ci_upper_bps": paired["ci_upper_bps"],
        "interval_excludes_zero": paired["interval_excludes_zero"],
        "status": "ok",
        "note": "Negative means the primary arm is weaker than this control over the same bars.",
    }


def _block_bootstrap(observations: Sequence[Mapping[str, Any]], *, resamples: int, confidence: float, seed: int) -> dict[str, Any]:
    """Moving-block bootstrap over the bar-ordered series (reused convention)."""

    values = [float(obs["bps"]) for obs in observations]
    result = moving_block_bootstrap_mean(
        values,
        block_length=max(1, min(5, len(values))),
        resamples=int(resamples),
        confidence=float(confidence),
        seed=int(seed),
    )
    return {
        "mean_bps": result.mean,
        "ci_lower_bps": result.lower,
        "ci_upper_bps": result.upper,
        "block_length": max(1, min(5, len(values))),
    }


def placebo_arms(
    observations: Sequence[Mapping[str, Any]],
    *,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Negative controls computed from the same retained rows.

    Three controls, none of which changes a frozen definition:

    ``side_reversed``
        Mirror arm. Flipping every position sign flips gross PnL and leaves
        turnover (hence cost) unchanged, so ``-gross - cost`` is exactly the
        mirrored arm. If the mirror is also positive after costs, the result is
        not directional skill.
    ``bucket_rotation``
        The same statistic computed one session bucket over. A session claim
        that only holds for one hand-picked bucket and not for its neighbour is
        fragile. Only 8h buckets are retained, so an hour-level phase shift is
        not computable from this artifact; that limitation is reported rather
        than papered over.
    ``single_symbol_baskets``
        Each symbol's own sleeve in isolation. This is the "one symbol carried
        it" control, reported as a distribution rather than a pick.
    """

    bucket_order = sorted({str(obs["session_bucket"]) for obs in observations})
    by_bucket: dict[str, list[float]] = {}
    for observation in observations:
        by_bucket.setdefault(str(observation["session_bucket"]), []).append(float(observation["bps"]))
    bucket_means = {name: float(np.mean(values)) for name, values in sorted(by_bucket.items())}
    rotation = {}
    for index, name in enumerate(bucket_order):
        shifted = bucket_order[(index + 1) % len(bucket_order)]
        rotation[name] = bucket_means.get(shifted)

    # net = gross - cost, so the mirrored arm is (-gross) - cost: gross flips sign,
    # while turnover (and therefore cost) is untouched by the flip.
    reversed_units = [
        [-float(observation["gross_bps"]) - float(observation["cost_bps"])] for observation in observations
    ]
    reversed_result = cluster_bootstrap_mean(
        reversed_units, resamples=resamples, confidence=confidence, seed=seed
    )

    symbols = sorted({symbol for obs in observations for symbol in obs["symbol_bps"]})
    single_symbol: dict[str, float] = {}
    for symbol in symbols:
        values = [float(obs["symbol_bps"].get(symbol, 0.0)) for obs in observations]
        single_symbol[symbol] = float(np.mean(values))
    ordered = sorted(single_symbol.values())

    return {
        "side_reversed": {
            "mean_bps": reversed_result["mean_bps"],
            "ci_lower_bps": reversed_result["ci_lower_bps"],
            "ci_upper_bps": reversed_result["ci_upper_bps"],
            "cluster_count": reversed_result["cluster_count"],
            "note": "Mirror arm: -gross - cost. Turnover, and therefore cost, is unchanged by the sign flip.",
        },
        "bucket_rotation": {
            "bucket_means_bps": bucket_means,
            "rotated_assignment_bps": rotation,
            "phase_shift_available": False,
            "phase_shift_note": (
                "Interval rows are retained only at the frozen 8h bucket resolution, so an "
                "hour-level phase-shifted clock cannot be reconstructed from this artifact."
            ),
        },
        "single_symbol_baskets": {
            "mean_bps": single_symbol,
            "minimum_mean_bps": ordered[0] if ordered else None,
            "median_mean_bps": float(np.median(ordered)) if ordered else None,
            "maximum_mean_bps": ordered[-1] if ordered else None,
            "positive_symbol_count": sum(1 for value in ordered if value > 0.0),
            "symbol_count": len(ordered),
        },
    }


def multiplicity_report(*, family_size: int | None, alpha: float = 0.05) -> dict[str, Any]:
    """Declare the family the review belongs to and the bound that implies.

    Bonferroni over a declared family is a *bound*, not a calibrated p-value,
    and the honest family for this repository is everything that was inspected
    before the window opened -- which is why an undeclared family size is
    reported as ``None`` rather than guessed.
    """

    if family_size is None:
        return {
            "family_size": None,
            "family_alpha": None,
            "adjusted_alpha": None,
            "status": "family_not_declared",
            "note": (
                "No trial family was declared for this watch. Multiplicity is therefore "
                "not adjusted and no family-wise claim may be made."
            ),
        }
    if int(family_size) < 1:
        raise RobustnessError("family_size must be at least 1")
    if not 0.0 < float(alpha) < 1.0:
        raise RobustnessError("alpha must be between 0 and 1")
    return {
        "family_size": int(family_size),
        "family_alpha": float(alpha),
        "adjusted_alpha": float(alpha) / int(family_size),
        "status": "declared",
        "note": (
            "Bonferroni bound over the declared family. Capture batches are dependent, so this "
            "is deliberately conservative and is reported as a bound, not a calibrated p-value."
        ),
    }


def family_selection_diagnostics(
    observations_by_variant: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    partitions: int = 8,
    block_length: int = 5,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Deflated Sharpe, PBO and reality check -- only when a real family exists.

    ``config/evidence_v2_session_forward_watch_v1.json`` declares EMA8/VOL8/EMA4
    as ``CONTROL``. Controls are context; treating them as a variant family would
    invent a selection procedure that the frozen config does not contain. So this
    diagnostic runs only when at least two *non-control* variants are supplied,
    and otherwise says so.
    """

    import pandas as pd

    if len(observations_by_variant) < 2:
        return {
            "status": "insufficient_variant_family",
            "variants": len(observations_by_variant),
            "note": (
                "Fewer than two non-control variants. Selection-family diagnostics "
                "(deflated Sharpe, PBO, reality check) are not applicable and were not computed."
            ),
        }

    columns: dict[str, list[float]] = {}
    for name, observations in observations_by_variant.items():
        series = pd.Series(
            [float(obs["bps"]) / 10_000.0 for obs in observations],
            index=[str(obs["bar_start_utc"]) for obs in observations],
            dtype=float,
        )
        columns[str(name)] = series
    frame = pd.DataFrame(columns).dropna(how="any")
    if frame.shape[0] < max(3, int(partitions)):
        return {
            "status": "insufficient_aligned_observations",
            "variants": int(frame.shape[1]),
            "aligned_observations": int(frame.shape[0]),
        }

    trial_sharpes = [sharpe_unannualized(frame[col].to_numpy()) for col in frame.columns]
    selected = str(frame.mean().idxmax())
    diagnostics: dict[str, Any] = {
        "status": "ok",
        "variants": list(frame.columns),
        "selected_variant_for_family_diagnostics": selected,
        "deflated_sharpe": deflated_sharpe_probability(frame[selected].to_numpy(), trial_sharpes),
        "reality_check": white_style_reality_check(
            frame, block_length=int(block_length), resamples=int(resamples), seed=int(seed)
        ),
    }
    try:
        diagnostics["pbo_cscv"] = cscv_pbo(frame, partitions=int(partitions))
    except ValueError as exc:
        diagnostics["pbo_cscv"] = {"status": "not_computed", "reason": str(exc)}
    return diagnostics


def _decision_rule_status(watch_config: Path | str | None) -> str:
    if watch_config is None:
        return "watch_config_not_supplied"
    from orderflow_edge_lab.preregistration import describe_decision_rule

    return describe_decision_rule(_load_object(watch_config))["decision_rule_status"]


def build_robustness_report(
    report: Mapping[str, Any] | Path | str,
    *,
    audit_id: str | None = None,
    role: str = DEFAULT_ROLE,
    cluster: str = "bar",
    bucket: str | None = None,
    watch_config: Path | str | None = None,
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
    family_size: int | None = None,
    design_clusters: int | None = None,
    cost_multipliers: Sequence[float] = DEFAULT_COST_MULTIPLIERS,
) -> dict[str, Any]:
    """Build the descriptive robustness report for one frozen forward report."""

    payload = report if isinstance(report, Mapping) else _load_object(report)
    variants = forward_variants(payload)
    primary_variant = select_variant(payload, audit_id=audit_id, role=role)
    primary = interval_observations(primary_variant, cluster=cluster, bucket=bucket)
    units = cluster_units(primary)

    controls: dict[str, Any] = {}
    for variant in variants:
        if str(variant.get("role")) != "CONTROL":
            continue
        control = interval_observations(variant, cluster=cluster, bucket=bucket)
        controls[str(variant.get("audit_id"))] = {
            "mean_bps": float(np.mean([float(obs["bps"]) for obs in control])),
            "observations": len(control),
            "comparison_to_primary": control_arm_comparison(
                primary, control, resamples=resamples, confidence=confidence, seed=seed
            ),
        }

    non_control = {
        str(variant.get("audit_id")): interval_observations(variant, cluster=cluster, bucket=bucket)
        for variant in variants
        if str(variant.get("role")) not in ("CONTROL",)
    }

    watch_hypothesis = payload.get("primary_hypothesis") or {}
    bootstrap = cluster_bootstrap_mean(units, resamples=resamples, confidence=confidence, seed=seed)
    mde = (
        minimum_detectable_effect(units, design_clusters=int(design_clusters), confidence=confidence)
        if design_clusters is not None
        else {"status": "design_size_not_supplied", "minimum_detectable_effect_bps": None}
    )

    analysis = {
        "schema_version": 1,
        "analysis": "post_hoc_descriptive_robustness",
        "analysis_label": "post_hoc_descriptive",
        "source_analysis": payload.get("analysis"),
        "source_watch_id": payload.get("watch_id"),
        "source_status": payload.get("status"),
        "source_days_elapsed": payload.get("days_elapsed"),
        "source_as_of_utc": payload.get("as_of_utc"),
        "variant": {
            "audit_id": primary_variant.get("audit_id"),
            "role": primary_variant.get("role"),
            "family": primary_variant.get("family"),
            "interval": primary_variant.get("interval"),
        },
        "bucket_filter": bucket,
        "dependence_cluster_unit": cluster,
        "declared_hypothesis": (
            str(watch_hypothesis.get("statement")) if isinstance(watch_hypothesis, Mapping) else None
        ),
        "interval": bootstrap,
        "moving_block_interval": _block_bootstrap(
            primary, resamples=resamples, confidence=confidence, seed=seed
        ),
        "minimum_detectable_effect": mde,
        "concentration": symbol_concentration(primary),
        "cost_surface": cost_surface_bps(primary, multipliers=cost_multipliers),
        "control_arms": controls,
        "placebo_arms": placebo_arms(primary, resamples=resamples, confidence=confidence, seed=seed),
        "family_selection_diagnostics": family_selection_diagnostics(
            non_control, resamples=resamples, seed=seed
        ),
        "multiplicity": multiplicity_report(family_size=family_size),
        "decision_rule_status": _decision_rule_status(watch_config),
        "verdict": None,
        "verdict_requires_human_review": True,
        "numeric_thresholds_invented": False,
        "claims": {
            "counts_prospective_intervals": False,
            "computes_strategy_verdicts": False,
            "certifies_data_quality": False,
            "selects_or_promotes_strategy": False,
            "changes_frozen_definition": False,
            "live_order_transmission_supported": False,
        },
    }
    if payload.get("source_sha256"):
        analysis["source_report_sha256"] = payload["source_sha256"]
    analysis["report_sha256"] = _canonical_sha256(analysis)
    return analysis


def robustness_markdown(report: Mapping[str, Any]) -> str:
    """Render the robustness report as review-ready markdown."""

    interval = report["interval"]
    lines = [
        "# Post-hoc descriptive robustness",
        "",
        f"- Analysis label: `{report['analysis_label']}` (not pre-registered for this watch)",
        f"- Variant: `{report['variant']['audit_id']}` ({report['variant']['role']})",
        f"- Source watch: `{report['source_watch_id']}` status `{report['source_status']}`, "
        f"{report['source_days_elapsed']} days elapsed as of {report['source_as_of_utc']}",
        f"- Dependence cluster unit: `{report['dependence_cluster_unit']}`",
        f"- Decision-rule status: `{report['decision_rule_status']}`",
        f"- Verdict: **withheld** (`verdict_requires_human_review`); no numeric threshold was invented",
        "",
        "## Interval (clustered bootstrap)",
        "",
        f"- Mean: {interval['mean_bps']:.4f} bps over {interval['observation_count']} intervals "
        f"in {interval['cluster_count']} clusters",
        f"- {int(interval['confidence'] * 100)}% interval: "
        f"[{interval['ci_lower_bps']:.4f}, {interval['ci_upper_bps']:.4f}] bps",
        f"- Interval excludes zero: `{interval['interval_excludes_zero']}` (descriptive fact only)",
        "",
        "## Minimum detectable effect",
        "",
    ]
    mde = report["minimum_detectable_effect"]
    if mde.get("minimum_detectable_effect_bps") is None:
        lines.append(f"- Not computed: `{mde.get('status')}`")
    else:
        lines.append(
            f"- At {mde['design_clusters']} design clusters: "
            f"{mde['minimum_detectable_effect_bps']:.4f} bps "
            f"(observed cluster dispersion {mde['cluster_mean_std_bps']:.4f} bps)"
        )
    lines += ["", "## Concentration", ""]
    concentration = report["concentration"]
    if concentration.get("status") != "ok":
        lines.append(
            f"- Not available: `{concentration.get('status')}` "
            f"({concentration.get('symbol_count')} symbol(s) with contribution)."
        )
    else:
        lines.append(
            f"- Best-symbol share of positive PnL: `{concentration['best_symbol_positive_pnl_share']}`; "
            f"top-5 share `{concentration['top5_positive_pnl_share']}`"
        )
        lines.append(
            f"- Leave-one-symbol-out mean range: "
            f"{concentration['minimum_leave_one_symbol_out_mean_bps']} bps is the worst case; "
            f"{concentration['positive_symbol_count']}/{concentration['symbol_count']} symbols positive"
        )
    lines += ["", "## Friction sensitivity", ""]
    surface = report["cost_surface"]
    lines.append(
        f"- Break-even round-trip cost: {surface['break_even_round_trip_cost_bps']:.4f} bps vs base "
        f"{surface['base_mean_cost_bps']:.4f} bps (ratio `{surface['break_even_to_base_cost_ratio']}`)"
    )
    for multiplier, case in sorted(surface["cases"].items()):
        lines.append(
            f"  - x{multiplier}: mean net {case['mean_net_bps']:.4f} bps, "
            f"positive fraction {case['positive_fraction']:.4f}"
        )
    lines += ["", "## Control arms (context only)", ""]
    if not report["control_arms"]:
        lines.append("- None declared.")
    if report["variant"].get("role") != "CONTROL" and report["control_arms"]:
        lines.append(
            "- Controls are context only. They are not a selection family, and no variant is chosen "
            "by comparing against them."
        )
    for audit_id, arm in sorted(report["control_arms"].items()):
        comparison = arm["comparison_to_primary"]
        lines.append(
            f"- `{audit_id}`: mean {arm['mean_bps']:.4f} bps; primary minus control "
            f"{comparison.get('difference_mean_bps')} bps "
            f"[{comparison.get('difference_ci_lower_bps')}, {comparison.get('difference_ci_upper_bps')}]"
        )
    placebo = report["placebo_arms"]
    lines += [
        "",
        "## Negative controls",
        "",
        f"- Side-reversed mirror arm: {placebo['side_reversed']['mean_bps']:.4f} bps "
        f"[{placebo['side_reversed']['ci_lower_bps']:.4f}, {placebo['side_reversed']['ci_upper_bps']:.4f}]",
        f"- Bucket means: {json.dumps(placebo['bucket_rotation']['bucket_means_bps'], sort_keys=True)}",
        f"- Single-symbol baskets: min {placebo['single_symbol_baskets']['minimum_mean_bps']} bps, "
        f"median {placebo['single_symbol_baskets']['median_mean_bps']} bps, "
        f"max {placebo['single_symbol_baskets']['maximum_mean_bps']} bps, "
        f"{placebo['single_symbol_baskets']['positive_symbol_count']}/"
        f"{placebo['single_symbol_baskets']['symbol_count']} positive",
        f"- Hour-level phase shift: {placebo['bucket_rotation']['phase_shift_note']}",
        "",
        "## Multiplicity",
        "",
        f"- `{report['multiplicity']['status']}`: {report['multiplicity']['note']}",
        "",
        f"- Self hash: `{report['report_sha256']}`",
        "",
    ]
    return "\n".join(lines)
