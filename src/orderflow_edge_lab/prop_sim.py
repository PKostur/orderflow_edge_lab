"""Prop-firm challenge simulator for prop-firm-v1 (config/prop_firm_v1.json). Daily equity, rules relative to the
initial account size; a 0.8 buffer approximates intraday excursions that daily data cannot see."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

BUFFER = 0.8


@dataclass
class PhaseResult:
    passed: bool
    days: int
    end: int  # index of the last day used
    reason: str = ""  # "pass", "breach", "stuck" or "data_end"


def run_phase(r: np.ndarray, start: int, target: float, firm: Mapping[str, Any], *, cap_days: int = 120,
              buffer: float = BUFFER) -> PhaseResult:
    eq, peak, best, pos_sum = 1.0, 1.0, 0.0, 0.0
    daily_lim = buffer * firm["daily_loss"]
    max_lim = buffer * firm["max_loss"]
    for k in range(cap_days):
        i = start + k
        if i >= len(r):
            return PhaseResult(False, k, i - 1, "data_end")
        pnl = eq * r[i]  # as a fraction of the initial account
        if -pnl > daily_lim:
            return PhaseResult(False, k + 1, i, "breach")
        eq += pnl
        floor = (peak if firm["max_loss_type"] == "trailing_eod" else 1.0) - max_lim
        if eq < floor:
            return PhaseResult(False, k + 1, i, "breach")
        peak = max(peak, eq)
        if pnl > 0:
            pos_sum += pnl
            best = max(best, pnl)
        days = k + 1
        if eq >= 1.0 + target and days >= firm.get("min_days", 0):
            rule = firm.get("best_day_rule")
            if rule is None or pos_sum <= 0 or best <= rule * pos_sum:
                return PhaseResult(True, days, i, "pass")
    return PhaseResult(False, cap_days, start + cap_days - 1, "stuck")


def run_challenge(r: np.ndarray, start: int, firm: Mapping[str, Any]) -> tuple[bool, int, int]:
    i, total = start, 0
    for target in firm["phases"]:
        res = run_phase(r, i, target, firm)
        total += res.days
        if not res.passed:
            return False, total, res.end
        i = res.end + 1
    return True, total, i - 1


def run_funded(r: np.ndarray, start: int, firm: Mapping[str, Any], *, days: int = 180, cash_every: int = 30,
               buffer: float = BUFFER) -> float:
    """Total payout (fraction of the account) over the funded period; profits are withdrawn every `cash_every` days."""
    eq, peak, paid = 1.0, 1.0, 0.0
    daily_lim, max_lim = buffer * firm["daily_loss"], buffer * firm["max_loss"]
    for k in range(days):
        i = start + k
        if i >= len(r):
            break
        pnl = eq * r[i]
        if -pnl > daily_lim:
            break
        eq += pnl
        floor = (peak if firm["max_loss_type"] == "trailing_eod" else 1.0) - max_lim
        if eq < floor:
            break
        peak = max(peak, eq)
        if (k + 1) % cash_every == 0 and eq > 1.0:
            paid += firm["split"] * (eq - 1.0)
            eq, peak = 1.0, 1.0
    return paid


def evaluate(r: np.ndarray, firm: Mapping[str, Any], *, every: int = 7) -> dict[str, Any]:
    r = np.nan_to_num(np.asarray(r, dtype=float))
    passes, days, payouts, n = 0, [], [], 0
    for s in range(0, len(r) - 240, every):
        n += 1
        ok, d, end = run_challenge(r, s, firm)
        if ok:
            passes += 1
            days.append(d)
            payouts.append(run_funded(r, end + 1, firm))
    p = passes / n if n else 0.0
    pay = float(np.mean(payouts)) if payouts else 0.0
    return {"attempts": n, "pass_rate": p, "median_days_to_pass": float(np.median(days)) if days else None,
            "mean_funded_payout_pct": 100 * pay, "ev_per_100": 100 * (p * pay - firm["fee_pct"]),
            "ev_per_fee": (p * pay - firm["fee_pct"]) / firm["fee_pct"]}


def run_challenge_detail(r: np.ndarray, start: int, firm: Mapping[str, Any], *, cap_days: int) -> tuple[str, int, int]:
    i, total = start, 0
    for target in firm["phases"]:
        res = run_phase(r, i, target, firm, cap_days=cap_days)
        total += res.days
        if not res.passed:
            return res.reason, total, res.end
        i = res.end + 1
    return "pass", total, i - 1


def run_funded_detail(r: np.ndarray, start: int, firm: Mapping[str, Any], *, days: int = 365, cash_every: int = 30,
                      buffer: float = BUFFER) -> dict[str, Any]:
    eq, peak, paid, first_paid = 1.0, 1.0, 0.0, None
    daily_lim, max_lim = buffer * firm["daily_loss"], buffer * firm["max_loss"]
    survived = True
    for k in range(days):
        i = start + k
        if i >= len(r):
            return {"complete": False, "survived": survived, "paid": paid, "first_paid_day": first_paid}
        pnl = eq * r[i]
        eq += pnl
        floor = (peak if firm["max_loss_type"] == "trailing_eod" else 1.0) - max_lim
        if -pnl > daily_lim or eq < floor:
            survived = False
            break
        peak = max(peak, eq)
        if (k + 1) % cash_every == 0 and eq > 1.0:
            paid += firm["split"] * (eq - 1.0)
            first_paid = first_paid or k + 1
            eq, peak = 1.0, 1.0
    return {"complete": True, "survived": survived, "paid": paid, "first_paid_day": first_paid}


def evaluate_survival(r: np.ndarray, firm: Mapping[str, Any], *, every: int = 7, cap_days: int = 365) -> dict[str, Any]:
    r = np.nan_to_num(np.asarray(r, dtype=float))
    outcomes, days, funded = [], [], []
    for s in range(0, len(r) - 400, every):
        why, d, end = run_challenge_detail(r, s, firm, cap_days=cap_days)
        if why == "data_end":
            continue
        outcomes.append(why)
        if why == "pass":
            days.append(d)
            f = run_funded_detail(r, end + 1, firm)
            if f["complete"]:
                funded.append(f)
    n = len(outcomes)
    p_pass = outcomes.count("pass") / n if n else 0.0
    nf = len(funded)
    mean_paid = float(np.mean([f["paid"] for f in funded])) if nf else 0.0
    return {
        "attempts": n, "pass_rate": p_pass, "breach_rate": outcomes.count("breach") / n if n else 0.0,
        "stuck_rate": outcomes.count("stuck") / n if n else 0.0,
        "median_days_to_pass": float(np.median(days)) if days else None, "funded_samples": nf,
        "funded_survival_12m": sum(f["survived"] for f in funded) / nf if nf else 0.0,
        "p_paid_by_3m": sum(1 for f in funded if f["first_paid_day"] and f["first_paid_day"] <= 90) / nf if nf else 0.0,
        "p_paid_by_12m": sum(1 for f in funded if f["paid"] > 0) / nf if nf else 0.0,
        "mean_payout_12m_pct": 100 * mean_paid,
        "ev_per_fee": (p_pass * mean_paid - firm["fee_pct"]) / firm["fee_pct"],
    }
