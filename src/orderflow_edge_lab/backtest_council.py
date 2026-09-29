"""Backtest council: deterministic adversarial review of a universal backtest.

Each council member is a fixed statistical or engineering test, not an opinion.
Members attack a candidate from a different angle (look-ahead leakage, costs,
luck, concentration, time stability, breadth, direction, multiple testing and
leverage path risk). A judge applies frozen rules to their findings.

The council is descriptive. It never establishes a profitable edge, never
authorizes live trading and never counts inspected data as out-of-sample
evidence. Its best possible verdict is eligibility for a prospective forward
shadow under a separate freeze.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
from statistics import NormalDist
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .discovery_v2_evaluation import (
    deflated_sharpe_probability,
    moving_block_bootstrap_mean,
    sharpe_unannualized,
)
from .research import canonical_json, sha256_text
from .universal_backtest import (
    ExecutionModel,
    StrategyPlugin,
    _validate_frame,
    parameter_variants,
    run_backtest,
    walk_forward_report,
)

COUNCIL_ID = "backtest_council_v1"

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
INFO = "INFO"

REJECT = "REJECT"
REVISE_OR_EXTEND = "REVISE_OR_EXTEND"
SHADOW_ELIGIBLE = "SHADOW_ELIGIBLE"

# Order matters: the judge reports the first failing member as the deciding reason.
MEMBER_ORDER = (
    "lookahead_auditor",
    "sample_clerk",
    "cost_skeptic",
    "null_examiner",
    "concentration_prosecutor",
    "fold_examiner",
    "breadth_examiner",
    "multiple_testing_auditor",
    "risk_path_auditor",
    "direction_auditor",
    "believer",
)

DEFAULT_THRESHOLDS: dict[str, Any] = {
    "lookahead_cut_points": 12,
    "lookahead_tolerance": 1e-9,
    "min_trades_fail": 30,
    "min_trades_warn": 100,
    "cost_stress_multiplier": 1.5,
    "funding_interval_hours": 8,
    "funding_stress_bps_per_crossing": 1.0,
    "null_draws": 500,
    "null_min_shift_fraction": 0.1,
    "null_p_warn": 0.05,
    "null_p_fail": 0.20,
    "top_trade_fraction": 0.05,
    "best_day_share_warn": 0.5,
    "fold_days": 30,
    "fold_positive_warn": 0.5,
    "fold_positive_fail": 0.35,
    "bootstrap_block_length": 10,
    "bootstrap_resamples": 2000,
    "bootstrap_confidence": 0.95,
    "breadth_positive_warn": 0.6,
    "breadth_positive_fail": 0.5,
    "dsr_probability_warn": 0.95,
    "dsr_probability_fail": 0.5,
    "adjusted_p_warn": 0.05,
    "neighborhood_positive_warn": 0.5,
    "maintenance_margin_rate": 0.004,
    "seed": 17,
}


class BacktestCouncilError(ValueError):
    pass


@dataclass(frozen=True)
class MemberFinding:
    member: str
    control: str
    status: str
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CouncilInputs:
    frames: Mapping[str, pd.DataFrame]
    strategy: StrategyPlugin
    params: Mapping[str, Any]
    execution: ExecutionModel
    parameter_grid: Mapping[str, Sequence[Any]] | None = None
    trial_count: int | None = None
    leverage: float | None = None
    data_role: str = "development"


def load_thresholds(path: str | Path | None = None) -> dict[str, Any]:
    thresholds = dict(DEFAULT_THRESHOLDS)
    if path is None:
        return thresholds
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    overrides = payload.get("thresholds", payload)
    unknown = set(overrides) - set(DEFAULT_THRESHOLDS)
    if unknown:
        raise BacktestCouncilError(f"unknown council thresholds: {sorted(unknown)}")
    thresholds.update(overrides)
    return thresholds


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _mean(values: Sequence[float]) -> float | None:
    return float(np.mean(values)) if len(values) else None


def _cost_per_trade_bps(execution: ExecutionModel) -> float:
    return float(execution.round_trip_cost_bps) + 2.0 * float(execution.slippage_bps_per_turnover_unit)


def _funding_crossings(entry: pd.Timestamp, exit_: pd.Timestamp, interval_hours: int) -> int:
    """Count funding timestamps (multiples of interval from 00:00 UTC) in (entry, exit]."""
    step = pd.Timedelta(hours=int(interval_hours))
    origin = entry.normalize()
    first = origin + step * math.floor((entry - origin) / step)
    if first <= entry:
        first += step
    if first > exit_:
        return 0
    return int((exit_ - first) // step) + 1


def _pooled_trades(results: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    for symbol, result in sorted(results.items()):
        for trade in result.get("trades_ledger", []):
            trades.append({"symbol": symbol, **trade})
    trades.sort(key=lambda t: (t["exit"], t["symbol"]))
    return trades


def _target_series(strategy: StrategyPlugin, frame: pd.DataFrame, params: Mapping[str, Any]) -> pd.Series:
    target = strategy.generate_target(frame, params, None).reindex(frame.index).fillna(0.0)
    return target.astype(float)


# ---------------------------------------------------------------------------
# Council members
# ---------------------------------------------------------------------------


def lookahead_auditor(inputs: CouncilInputs, th: Mapping[str, Any]) -> MemberFinding:
    """Recompute targets on truncated history; any change means future data leaked in."""
    violations: list[dict[str, Any]] = []
    checked = 0
    tol = float(th["lookahead_tolerance"])
    for symbol, frame in sorted(inputs.frames.items()):
        n = len(frame)
        start = max(int(inputs.strategy.warmup_bars) + 2, 3)
        if n <= start + 1:
            continue
        full = _target_series(inputs.strategy, frame, inputs.params)
        k = max(1, int(th["lookahead_cut_points"]))
        cuts = sorted({int(x) for x in np.linspace(start, n - 1, num=k)})
        for cut in cuts:
            truncated = _target_series(inputs.strategy, frame.iloc[:cut], inputs.params)
            reference = full.iloc[:cut]
            diff = (truncated - reference).abs()
            checked += 1
            if bool((diff > tol).any()):
                first_bad = diff[diff > tol].index[0]
                violations.append({
                    "symbol": symbol,
                    "cut_bars": cut,
                    "first_divergent_bar": first_bad.isoformat(),
                    "max_abs_difference": float(diff.max()),
                })
                break
    if checked == 0:
        return MemberFinding("lookahead_auditor", "no_lookahead_check", WARN,
                             "Not enough bars after warmup to test for look-ahead.", {"cut_checks": 0})
    if violations:
        return MemberFinding(
            "lookahead_auditor", "no_lookahead_check", FAIL,
            "Signal changes when future bars are removed. The strategy uses information it could not have had.",
            {"cut_checks": checked, "violations": violations},
        )
    return MemberFinding("lookahead_auditor", "no_lookahead_check", PASS,
                         "Signals are identical on truncated history.", {"cut_checks": checked})


def sample_clerk(trades: Sequence[Mapping[str, Any]], th: Mapping[str, Any]) -> MemberFinding:
    n = len(trades)
    evidence = {"trades": n, "fail_below": th["min_trades_fail"], "warn_below": th["min_trades_warn"]}
    if n < int(th["min_trades_fail"]):
        return MemberFinding("sample_clerk", "sample_size", FAIL, f"Only {n} trades. Too few to judge anything.", evidence)
    if n < int(th["min_trades_warn"]):
        return MemberFinding("sample_clerk", "sample_size", WARN, f"{n} trades. Thin sample; statistics are unstable.", evidence)
    return MemberFinding("sample_clerk", "sample_size", PASS, f"{n} trades.", evidence)


def cost_skeptic(trades: Sequence[Mapping[str, Any]], inputs: CouncilInputs, th: Mapping[str, Any]) -> MemberFinding:
    """Break-even cost, stressed costs and adverse perpetual funding."""
    if not trades:
        return MemberFinding("cost_skeptic", "cost_stress", FAIL, "No trades to cost.", {})
    base_cost = _cost_per_trade_bps(inputs.execution)
    gross = np.array([float(t["gross_bps"]) for t in trades])
    interval = int(th["funding_interval_hours"])
    funding_bps = float(th["funding_stress_bps_per_crossing"])
    crossings = np.array([
        _funding_crossings(pd.Timestamp(t["entry"]), pd.Timestamp(t["exit"]), interval) for t in trades
    ], dtype=float)
    funding_drag = crossings * funding_bps
    mult = float(th["cost_stress_multiplier"])
    base_net = gross - base_cost
    base_with_funding = base_net - funding_drag
    stressed = gross - base_cost * mult - funding_drag
    evidence = {
        "cost_per_trade_bps": base_cost,
        "mean_gross_bps": float(gross.mean()),
        "break_even_cost_bps": float(gross.mean()),
        "cost_margin_multiple": float(gross.mean() / base_cost) if base_cost > 0 else None,
        "expectancy_net_bps": float(base_net.mean()),
        "mean_funding_crossings_per_trade": float(crossings.mean()),
        "funding_stress_bps_per_crossing": funding_bps,
        "expectancy_net_after_adverse_funding_bps": float(base_with_funding.mean()),
        "stress_multiplier": mult,
        "expectancy_stressed_bps": float(stressed.mean()),
    }
    if base_with_funding.mean() <= 0:
        return MemberFinding("cost_skeptic", "cost_stress", FAIL,
                             "Expectancy is not positive after base costs and adverse funding.", evidence)
    if stressed.mean() <= 0:
        return MemberFinding("cost_skeptic", "cost_stress", WARN,
                             f"Expectancy turns negative when costs rise {mult:g}x. Edge is thinner than costs can move.",
                             evidence)
    return MemberFinding("cost_skeptic", "cost_stress", PASS,
                         f"Survives {mult:g}x costs plus adverse funding.", evidence)


def null_examiner(inputs: CouncilInputs, th: Mapping[str, Any]) -> MemberFinding:
    """Circular-shift test: same positions, same holding pattern, random timing."""
    rng = np.random.default_rng(int(th["seed"]))
    draws = int(th["null_draws"])
    observed = 0.0
    per_symbol: list[tuple[np.ndarray, np.ndarray]] = []
    for _, frame in sorted(inputs.frames.items()):
        if len(frame) < max(3, int(inputs.strategy.warmup_bars)):
            continue
        target = _target_series(inputs.strategy, frame, inputs.params)
        limit = float(inputs.execution.max_abs_position)
        pos = target.clip(-limit, limit).shift(1).fillna(0.0).to_numpy(dtype=float)
        opens = frame["open"].astype(float)
        ret = (opens.shift(-1) / opens - 1.0).fillna(0.0).to_numpy(dtype=float)
        observed += float(np.sum(pos * ret))
        per_symbol.append((pos, ret))
    if not per_symbol or all(not np.any(p) for p, _ in per_symbol):
        return MemberFinding("null_examiner", "reversed_or_sign_control", FAIL, "Strategy never takes a position.", {})
    null = np.zeros(draws)
    frac = float(th["null_min_shift_fraction"])
    for pos, ret in per_symbol:
        n = len(pos)
        lo = max(1, int(n * frac))
        hi = max(lo + 1, n - lo)
        shifts = rng.integers(lo, hi, size=draws)
        for i, k in enumerate(shifts):
            null[i] += float(np.sum(np.roll(pos, int(k)) * ret))
    p_value = float((1 + np.sum(null >= observed)) / (draws + 1))
    evidence = {
        "observed_gross_return_sum": observed,
        "reversed_sign_gross_sum": -observed,
        "null_mean": float(null.mean()),
        "null_95th": float(np.quantile(null, 0.95)),
        "p_value": p_value,
        "draws": draws,
        "method": "circular_shift_of_executed_position_vs_next_open_returns",
    }
    if p_value > float(th["null_p_fail"]):
        return MemberFinding("null_examiner", "reversed_or_sign_control", FAIL,
                             f"Randomly re-timed copies of the same positions do as well (p={p_value:.3f}). Timing adds nothing measurable.",
                             evidence)
    if p_value > float(th["null_p_warn"]):
        return MemberFinding("null_examiner", "reversed_or_sign_control", WARN,
                             f"Timing beats random re-timing only weakly (p={p_value:.3f}).", evidence)
    return MemberFinding("null_examiner", "reversed_or_sign_control", PASS,
                         f"Timing beats random re-timing (p={p_value:.3f}).", evidence)


def concentration_prosecutor(trades: Sequence[Mapping[str, Any]], th: Mapping[str, Any]) -> MemberFinding:
    """Is the result carried by a handful of trades or a single day?"""
    if not trades:
        return MemberFinding("concentration_prosecutor", "concentration", FAIL, "No trades.", {})
    net = np.array([float(t["net_bps"]) for t in trades])
    total = float(net.sum())
    k = max(1, int(math.ceil(len(net) * float(th["top_trade_fraction"]))))
    order = np.sort(net)[::-1]
    without_top = float(total - order[:k].sum())
    days = pd.Series(net, index=pd.to_datetime([t["exit"] for t in trades], utc=True).normalize())
    by_day = days.groupby(level=0).sum()
    best_day = float(by_day.max())
    without_best_day = float(total - best_day)
    evidence = {
        "total_net_bps": total,
        "top_trades_removed": k,
        "net_without_top_trades_bps": without_top,
        "largest_trade_share": float(order[0] / total) if total > 0 else None,
        "best_day": str(by_day.idxmax().date()),
        "best_day_net_bps": best_day,
        "best_day_share": float(best_day / total) if total > 0 else None,
        "net_without_best_day_bps": without_best_day,
        "active_days": int(len(by_day)),
    }
    if total <= 0:
        return MemberFinding("concentration_prosecutor", "concentration", FAIL, "Net result is not positive.", evidence)
    if without_best_day <= 0:
        return MemberFinding("concentration_prosecutor", "concentration", FAIL,
                             f"Remove the single best day ({evidence['best_day']}) and the result is gone.", evidence)
    share = evidence["best_day_share"] or 0.0
    if without_top <= 0 or share >= float(th["best_day_share_warn"]):
        return MemberFinding("concentration_prosecutor", "concentration", WARN,
                             f"Result leans on the top {k} trades or one day ({share:.0%} of net).", evidence)
    return MemberFinding("concentration_prosecutor", "concentration", PASS,
                         "Result survives removing the best trades and the best day.", evidence)


def fold_examiner(trades: Sequence[Mapping[str, Any]], inputs: CouncilInputs, th: Mapping[str, Any]) -> MemberFinding:
    folds: list[float] = []
    for _, frame in sorted(inputs.frames.items()):
        report = walk_forward_report(frame, inputs.strategy, inputs.params, inputs.execution, fold_days=int(th["fold_days"]))
        for fold in report["folds"]:
            ev = _finite_or_none(fold.get("expectancy_bps"))
            if int(fold.get("trades") or 0) > 0 and ev is not None:
                folds.append(ev)
    net = [float(t["net_bps"]) for t in trades]
    evidence: dict[str, Any] = {"fold_days": int(th["fold_days"]), "folds_with_trades": len(folds)}
    if len(net) >= 2:
        boot = moving_block_bootstrap_mean(
            net,
            block_length=int(th["bootstrap_block_length"]),
            resamples=int(th["bootstrap_resamples"]),
            confidence=float(th["bootstrap_confidence"]),
            seed=int(th["seed"]),
        )
        evidence["expectancy_ci_bps"] = [boot.lower, boot.upper]
    if not folds:
        return MemberFinding("fold_examiner", "time_fold", WARN, "No time folds contain trades.", evidence)
    positive = sum(v > 0 for v in folds) / len(folds)
    evidence["positive_fold_fraction"] = positive
    evidence["worst_fold_expectancy_bps"] = min(folds)
    if positive < float(th["fold_positive_fail"]):
        return MemberFinding("fold_examiner", "time_fold", FAIL,
                             f"Only {positive:.0%} of {th['fold_days']}-day folds are positive.", evidence)
    ci = evidence.get("expectancy_ci_bps")
    if positive < float(th["fold_positive_warn"]) or (ci is not None and ci[0] <= 0):
        return MemberFinding("fold_examiner", "time_fold", WARN,
                             f"{positive:.0%} of folds positive; bootstrap interval includes zero or below." if ci and ci[0] <= 0
                             else f"Only {positive:.0%} of folds positive.", evidence)
    return MemberFinding("fold_examiner", "time_fold", PASS,
                         f"{positive:.0%} of folds positive and the bootstrap interval is above zero.", evidence)


def breadth_examiner(results: Mapping[str, Mapping[str, Any]], th: Mapping[str, Any]) -> MemberFinding:
    evs = {s: _finite_or_none(r.get("expectancy_bps")) for s, r in results.items() if int(r.get("trades") or 0) > 0}
    evs = {s: v for s, v in evs.items() if v is not None}
    evidence = {"per_symbol_expectancy_bps": evs}
    if len(evs) < 2:
        return MemberFinding("breadth_examiner", "symbol_breadth", WARN,
                             "Tested on one symbol only. No evidence it transfers.", evidence)
    positive = sum(v > 0 for v in evs.values()) / len(evs)
    evidence["positive_symbol_fraction"] = positive
    evidence["median_symbol_expectancy_bps"] = float(np.median(list(evs.values())))
    if positive < float(th["breadth_positive_fail"]):
        return MemberFinding("breadth_examiner", "symbol_breadth", FAIL,
                             f"Positive on only {positive:.0%} of symbols.", evidence)
    if positive < float(th["breadth_positive_warn"]):
        return MemberFinding("breadth_examiner", "symbol_breadth", WARN,
                             f"Positive on {positive:.0%} of symbols.", evidence)
    return MemberFinding("breadth_examiner", "symbol_breadth", PASS,
                         f"Positive on {positive:.0%} of symbols.", evidence)


def _variant_trade_sharpes(inputs: CouncilInputs) -> list[dict[str, Any]]:
    rows = []
    for params in parameter_variants(inputs.parameter_grid or {}):
        results = {s: run_backtest(f, inputs.strategy, params, inputs.execution) for s, f in sorted(inputs.frames.items())}
        net = [float(t["net_bps"]) for t in _pooled_trades(results)]
        rows.append({
            "parameters": params,
            "trades": len(net),
            "expectancy_bps": _mean(net),
            "sharpe": sharpe_unannualized(net) if len(net) >= 2 else float("nan"),
        })
    return rows


def multiple_testing_auditor(trades: Sequence[Mapping[str, Any]], inputs: CouncilInputs, th: Mapping[str, Any]) -> MemberFinding:
    """How much of the result is explained by picking the best of many tries?"""
    net = [float(t["net_bps"]) for t in trades]
    if len(net) < 3:
        return MemberFinding("multiple_testing_auditor", "multiple_testing", FAIL, "Too few trades to test.", {})
    if inputs.parameter_grid:
        variants = _variant_trade_sharpes(inputs)
        sharpes = [v["sharpe"] for v in variants if math.isfinite(v["sharpe"])]
        declared = int(inputs.trial_count or 0)
        trials = max(len(variants), declared)
        evidence: dict[str, Any] = {"grid_variants": len(variants), "declared_trial_count": declared or None}
        evs = [v["expectancy_bps"] for v in variants if v["expectancy_bps"] is not None]
        if evs:
            evidence["neighborhood_positive_fraction"] = sum(e > 0 for e in evs) / len(evs)
            evidence["selected_rank_by_expectancy"] = 1 + sum(e > (_mean(net) or 0.0) for e in evs)
        if len(sharpes) >= 2:
            if trials > len(sharpes):
                # Declared trials exceed the grid: widen by repeating the observed spread.
                reps = int(math.ceil(trials / len(sharpes)))
                sharpes = (sharpes * reps)[:trials]
            dsr = deflated_sharpe_probability(net, sharpes)
            evidence["deflated_sharpe"] = dsr
            prob = _finite_or_none(dsr.get("probability"))
            if prob is None or prob < float(th["dsr_probability_fail"]):
                return MemberFinding("multiple_testing_auditor", "multiple_testing", FAIL,
                                     "After accounting for the variants tried, the result is consistent with best-of-N luck.",
                                     evidence)
            neighborhood = evidence.get("neighborhood_positive_fraction", 1.0)
            if prob < float(th["dsr_probability_warn"]) or neighborhood < float(th["neighborhood_positive_warn"]):
                return MemberFinding("multiple_testing_auditor", "multiple_testing", WARN,
                                     f"Deflated Sharpe probability {prob:.2f}; {neighborhood:.0%} of neighboring parameter sets are positive.",
                                     evidence)
            return MemberFinding("multiple_testing_auditor", "multiple_testing", PASS,
                                 f"Deflated Sharpe probability {prob:.2f} with {neighborhood:.0%} of neighbors positive.", evidence)
    if inputs.trial_count:
        arr = np.asarray(net)
        sd = float(arr.std(ddof=1))
        t_stat = float(arr.mean() / (sd / math.sqrt(len(arr)))) if sd > 0 else float("inf")
        p_one = 1.0 - NormalDist().cdf(t_stat) if math.isfinite(t_stat) else 0.0
        adjusted = min(1.0, p_one * int(inputs.trial_count))
        evidence = {"declared_trial_count": int(inputs.trial_count), "t_stat": t_stat,
                    "one_sided_p": p_one, "bonferroni_adjusted_p": adjusted}
        if adjusted > 0.5:
            return MemberFinding("multiple_testing_auditor", "multiple_testing", FAIL,
                                 f"Adjusted for {inputs.trial_count} trials, p={adjusted:.2f}.", evidence)
        if adjusted > float(th["adjusted_p_warn"]):
            return MemberFinding("multiple_testing_auditor", "multiple_testing", WARN,
                                 f"Adjusted for {inputs.trial_count} trials, p={adjusted:.2f}.", evidence)
        return MemberFinding("multiple_testing_auditor", "multiple_testing", PASS,
                             f"Adjusted for {inputs.trial_count} trials, p={adjusted:.3f}.", evidence)
    return MemberFinding("multiple_testing_auditor", "multiple_testing", WARN,
                         "Number of variants tried is unknown. Declare a trial count or grid; best-of-N luck cannot be ruled out.",
                         {})


def risk_path_auditor(trades: Sequence[Mapping[str, Any]], inputs: CouncilInputs, th: Mapping[str, Any]) -> MemberFinding:
    """Would the intended leverage have survived each trade's adverse excursion?"""
    if inputs.leverage is None or inputs.leverage <= 1.0:
        return MemberFinding("risk_path_auditor", "leverage_path", INFO,
                             "No leverage declared; liquidation path not assessed.", {"leverage": inputs.leverage})
    lev = float(inputs.leverage)
    mmr = float(th["maintenance_margin_rate"])
    threshold_bps = (1.0 / lev - mmr) * 10_000.0
    cost = _cost_per_trade_bps(inputs.execution)
    liquidated = [t for t in trades if -float(t["mae_bps"]) >= threshold_bps]
    adjusted = [
        (-(10_000.0 / lev) - cost) if -float(t["mae_bps"]) >= threshold_bps else float(t["net_bps"])
        for t in trades
    ]
    evidence = {
        "leverage": lev,
        "maintenance_margin_rate": mmr,
        "liquidation_distance_bps": threshold_bps,
        "liquidated_trades": len(liquidated),
        "liquidated_fraction": len(liquidated) / len(trades) if trades else None,
        "expectancy_after_liquidations_bps": _mean(adjusted),
        "worst_mae_bps": min((float(t["mae_bps"]) for t in trades), default=None),
        "note": "Bar high/low path; intrabar ordering is unknown, so this is a lower bound on liquidations.",
    }
    if threshold_bps <= 0:
        return MemberFinding("risk_path_auditor", "leverage_path", FAIL,
                             "Leverage leaves no room above maintenance margin.", evidence)
    if adjusted and (_mean(adjusted) or 0.0) <= 0:
        return MemberFinding("risk_path_auditor", "leverage_path", FAIL,
                             f"At {lev:g}x, {len(liquidated)} trades would have been liquidated and expectancy turns negative.",
                             evidence)
    if liquidated:
        return MemberFinding("risk_path_auditor", "leverage_path", WARN,
                             f"At {lev:g}x, {len(liquidated)} trades would have hit liquidation before the strategy exit.",
                             evidence)
    return MemberFinding("risk_path_auditor", "leverage_path", PASS,
                         f"No trade's adverse excursion reached the {threshold_bps:.0f} bps liquidation distance at {lev:g}x.",
                         evidence)


def direction_auditor(trades: Sequence[Mapping[str, Any]]) -> MemberFinding:
    longs = [float(t["net_bps"]) for t in trades if int(t["side"]) > 0]
    shorts = [float(t["net_bps"]) for t in trades if int(t["side"]) < 0]
    evidence = {
        "long_trades": len(longs), "long_expectancy_bps": _mean(longs),
        "short_trades": len(shorts), "short_expectancy_bps": _mean(shorts),
    }
    lm, sm = evidence["long_expectancy_bps"], evidence["short_expectancy_bps"]
    if lm is not None and sm is not None and (lm > 0) != (sm > 0):
        side = "long" if lm > 0 else "short"
        return MemberFinding("direction_auditor", "direction_split", WARN,
                             f"Only the {side} side makes money. Check whether this is market drift rather than timing.",
                             evidence)
    return MemberFinding("direction_auditor", "direction_split", INFO, "Both sides agree in sign.", evidence)


def believer(trades: Sequence[Mapping[str, Any]], results: Mapping[str, Mapping[str, Any]]) -> MemberFinding:
    """States the strongest factual case for the candidate. Never votes."""
    net = [float(t["net_bps"]) for t in trades]
    gains = sum(v for v in net if v > 0)
    losses = -sum(v for v in net if v < 0)
    evidence = {
        "trades": len(net),
        "expectancy_net_bps": _mean(net),
        "win_rate": (sum(v > 0 for v in net) / len(net)) if net else None,
        "profit_factor": (gains / losses) if losses > 0 else None,
        "median_mfe_bps": float(np.median([float(t["mfe_bps"]) for t in trades])) if trades else None,
        "best_symbol": max(results, key=lambda s: _finite_or_none(results[s].get("expectancy_bps")) or -1e18) if results else None,
    }
    summary = "No trades." if not net else (
        f"{len(net)} trades, {evidence['expectancy_net_bps']:.1f} bps net per trade"
        + (f", PF {evidence['profit_factor']:.2f}" if evidence["profit_factor"] else "")
        + "."
    )
    return MemberFinding("believer", "case_for", INFO, summary, evidence)


# ---------------------------------------------------------------------------
# Judge and report
# ---------------------------------------------------------------------------


def judge(findings: Sequence[MemberFinding]) -> dict[str, Any]:
    ranked = sorted(findings, key=lambda f: MEMBER_ORDER.index(f.member))
    fails = [f for f in ranked if f.status == FAIL]
    warns = [f for f in ranked if f.status == WARN]
    if fails:
        verdict, deciding = REJECT, fails[0]
    elif warns:
        verdict, deciding = REVISE_OR_EXTEND, warns[0]
    else:
        verdict, deciding = SHADOW_ELIGIBLE, None
    return {
        "verdict": verdict,
        "deciding_member": deciding.member if deciding else None,
        "deciding_reason": deciding.summary if deciding else "Every mandatory control passed on this data.",
        "failed": [f.member for f in fails],
        "warned": [f.member for f in warns],
        "next_step": {
            REJECT: "Do not trade or re-tune on this data. A fix requires a new hypothesis version and fresh data.",
            REVISE_OR_EXTEND: "Resolve the warnings with more or new data, not by adjusting parameters on this sample.",
            SHADOW_ELIGIBLE: "Freeze parameters and costs, then run a prospective forward shadow. This is not promotion.",
        }[verdict],
    }


def run_council(inputs: CouncilInputs, thresholds: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not inputs.frames:
        raise BacktestCouncilError("council requires at least one market frame")
    if inputs.data_role not in {"development", "validation", "holdout"}:
        raise BacktestCouncilError("data_role must be development, validation or holdout")
    th = dict(DEFAULT_THRESHOLDS)
    th.update(thresholds or {})
    frames = {s: _validate_frame(f) for s, f in inputs.frames.items()}
    inputs = CouncilInputs(**{**inputs.__dict__, "frames": frames})

    results = {s: run_backtest(f, inputs.strategy, inputs.params, inputs.execution) for s, f in sorted(frames.items())}
    trades = _pooled_trades(results)

    findings = [
        lookahead_auditor(inputs, th),
        sample_clerk(trades, th),
        cost_skeptic(trades, inputs, th),
        null_examiner(inputs, th),
        concentration_prosecutor(trades, th),
        fold_examiner(trades, inputs, th),
        breadth_examiner(results, th),
        multiple_testing_auditor(trades, inputs, th),
        risk_path_auditor(trades, inputs, th),
        direction_auditor(trades),
        believer(trades, results),
    ]
    report: dict[str, Any] = {
        "schema_version": 1,
        "council_id": COUNCIL_ID,
        "strategy_id": inputs.strategy.strategy_id,
        "parameters": dict(inputs.params),
        "execution": asdict(inputs.execution),
        "leverage": inputs.leverage,
        "data_role": inputs.data_role,
        "symbols": {
            s: {"bars": len(f), "start": f.index.min().isoformat(), "end": f.index.max().isoformat()}
            for s, f in sorted(frames.items())
        },
        "thresholds": th,
        "members": [asdict(f) for f in findings],
        "judgement": judge(findings),
        "claims": {
            "profitable_edge_established": False,
            "verified_out_of_sample_evidence": False,
            "live_trading_authorized": False,
            "inspected_data_spent": True,
        },
    }
    report["report_sha256"] = sha256_text(canonical_json(report))
    return report


def verify_council_report(report: Mapping[str, Any]) -> bool:
    body = {k: v for k, v in report.items() if k != "report_sha256"}
    claims = body.get("claims", {})
    if claims.get("profitable_edge_established") is not False or claims.get("live_trading_authorized") is not False:
        return False
    return sha256_text(canonical_json(body)) == report.get("report_sha256")


def render_markdown(report: Mapping[str, Any]) -> str:
    j = report["judgement"]
    lines = [
        f"# Backtest council: {report['strategy_id']}",
        "",
        f"**Verdict: {j['verdict']}**. {j['deciding_reason']}",
        "",
        f"Next step: {j['next_step']}",
        "",
        "| Member | Control | Status | Finding |",
        "|---|---|---|---|",
    ]
    for m in report["members"]:
        lines.append(f"| {m['member']} | {m['control']} | {m['status']} | {m['summary']} |")
    lines += [
        "",
        f"Data role: {report['data_role']}. Inspected data is spent for independent validation.",
        "No profitable edge is established by this report. Live trading is not authorized.",
        "",
        f"Report SHA-256: `{report['report_sha256']}`",
    ]
    return "\n".join(lines) + "\n"
