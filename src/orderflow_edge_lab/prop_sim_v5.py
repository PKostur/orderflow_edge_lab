"""prop-firm-v5 simulator: challenge and funded phases where the daily risk scale comes from an approach function.

An approach is f(state) -> scale, with state = {"i", "k", "eq", "floor", "target", "sigma", "ctx", "aux"}; the scale
multiplies that day's book return. Same buffer and loss-limit semantics as prop_sim.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

import numpy as np

from orderflow_edge_lab.prop_sim import BUFFER, headroom_multiplier

Approach = Callable[[dict], float]


def _floor(firm, peak, max_lim):
    return (peak if firm["max_loss_type"] == "trailing_eod" else 1.0) - max_lim


def run_phase(r: np.ndarray, start: int, target: float, firm: Mapping[str, Any], fn: Approach, aux: Mapping[str, np.ndarray],
              *, cap_days: int = 365, buffer: float = BUFFER) -> tuple[str, int, int]:
    eq, peak, best, pos_sum = 1.0, 1.0, 0.0, 0.0
    daily_lim, max_lim = buffer * firm["daily_loss"], buffer * firm["max_loss"]
    ctx: dict[str, Any] = {}
    for k in range(cap_days):
        i = start + k
        if i >= len(r):
            return "data_end", k, i - 1
        state = {"i": i, "k": k, "eq": eq, "floor": _floor(firm, peak, max_lim), "target": target, "firm": firm, "ctx": ctx, "aux": aux}
        s = max(0.0, float(fn(state)))
        pnl = eq * s * r[i]
        ctx["last_pnl"] = pnl
        if -pnl > daily_lim:
            return "breach", k + 1, i
        eq += pnl
        if eq < _floor(firm, peak, max_lim):
            return "breach", k + 1, i
        peak = max(peak, eq)
        if pnl > 0:
            pos_sum += pnl
            best = max(best, pnl)
        if eq >= 1.0 + target and k + 1 >= firm.get("min_days", 0):
            rule = firm.get("best_day_rule")
            if rule is None or pos_sum <= 0 or best <= rule * pos_sum:
                return "pass", k + 1, i
    return "stuck", cap_days, start + cap_days - 1


def run_funded(r: np.ndarray, start: int, firm: Mapping[str, Any], fn: Approach, aux: Mapping[str, np.ndarray], *,
               days: int = 365, cash_every: int = 30, buffer: float = BUFFER) -> dict[str, Any]:
    eq, peak, paid, first = 1.0, 1.0, 0.0, None
    daily_lim, max_lim = buffer * firm["daily_loss"], buffer * firm["max_loss"]
    ctx: dict[str, Any] = {}
    for k in range(days):
        i = start + k
        if i >= len(r):
            return {"complete": False, "survived": True, "paid": paid, "first_paid_day": first}
        state = {"i": i, "k": k, "eq": eq, "floor": _floor(firm, peak, max_lim), "target": None, "firm": firm, "ctx": ctx, "aux": aux}
        pnl = eq * max(0.0, float(fn(state))) * r[i]
        eq += pnl
        if -pnl > daily_lim or eq < _floor(firm, peak, max_lim):
            return {"complete": True, "survived": False, "paid": paid, "first_paid_day": first}
        peak = max(peak, eq)
        if (k + 1) % cash_every == 0 and eq > 1.0:
            paid += firm["split"] * (eq - 1.0)
            first = first or k + 1
            eq, peak = 1.0, 1.0
    return {"complete": True, "survived": True, "paid": paid, "first_paid_day": first}


def evaluate_pair(challenge_r: np.ndarray, funded_r: np.ndarray, firm: Mapping[str, Any], cfn: Approach, ffn: Approach,
                  aux_c: Mapping[str, np.ndarray], aux_f: Mapping[str, np.ndarray], *, every: int = 7) -> dict[str, Any]:
    """Both series share one date index; the funded phase starts the day after the challenge passes."""
    challenge_r = np.nan_to_num(np.asarray(challenge_r, dtype=float))
    funded_r = np.nan_to_num(np.asarray(funded_r, dtype=float))
    outs, adays, fres = [], [], []
    for s0 in range(0, len(challenge_r) - 400, every):
        i, total, why = s0, 0, "pass"
        for target in firm["phases"]:
            why, d, end = run_phase(challenge_r, i, target, firm, cfn, aux_c)
            total += d
            if why != "pass":
                break
            i = end + 1
        if why == "data_end":
            continue
        outs.append(why)
        adays.append(total)
        if why == "pass":
            f = run_funded(funded_r, i, firm, ffn, aux_f)
            if f["complete"]:
                fres.append(f)
    n, nf = len(outs), len(fres)
    p = outs.count("pass") / n if n else 0.0
    D = float(np.mean(adays)) if adays else 0.0
    fees = 100 * firm["fee_pct"] / p if p else None
    pay = 100 * float(np.mean([f["paid"] for f in fres])) if nf else 0.0
    return {"attempts": n, "pass_rate": p, "breach_rate": outs.count("breach") / n if n else 0.0, "mean_attempt_days": D,
            "expected_days_to_funded": D / p if p else None, "expected_fees_per_funded_pct": fees, "funded_samples": nf,
            "funded_survival_12m": sum(f["survived"] for f in fres) / nf if nf else 0.0,
            "p_paid_by_3m": sum(1 for f in fres if f["first_paid_day"] and f["first_paid_day"] <= 90) / nf if nf else 0.0,
            "mean_payout_12m_pct": pay, "net_value_12m_pct": pay - fees if fees is not None else None}


# ---- building blocks for approaches ----

def vol_guard(state: dict, s: float) -> float:
    sig = state["aux"]["sigma"][state["i"]]
    if np.isfinite(sig) and sig > 0:
        return min(s, 0.7 * state["firm"]["daily_loss"] / (2.33 * sig))
    return s


def headroom(state: dict, s: float, floor_override: float | None = None) -> float:
    floor = state["floor"] if floor_override is None else max(state["floor"], floor_override)
    return s * headroom_multiplier(state["eq"] - floor)
