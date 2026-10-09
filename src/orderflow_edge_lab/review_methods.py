"""Small helpers used at pre-registered review time (descriptive only)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.research import benjamini_hochberg


def action_matched_null_p(
    observed: float, null_draws: Sequence[float], *, alternative: str = "greater"
) -> dict:
    draws = np.asarray(list(null_draws), dtype=float)
    draws = draws[np.isfinite(draws)]
    n = int(draws.size)
    if n < 99:
        raise ValueError("need at least 99 finite null draws")
    if alternative not in ("greater", "less", "two-sided"):
        raise ValueError("alternative must be greater, less or two-sided")
    p_greater = (1 + int((draws >= observed).sum())) / (1 + n)
    p_less = (1 + int((draws <= observed).sum())) / (1 + n)
    if alternative == "greater":
        p = p_greater
    elif alternative == "less":
        p = p_less
    else:
        p = min(1.0, 2 * min(p_greater, p_less, 0.5))
    return {
        "p": float(p),
        "n_null": n,
        "null_mean": float(draws.mean()),
        "null_p95": float(np.percentile(draws, 95)),
    }


def matched_random_selection_returns(
    returns: pd.DataFrame, selected: pd.DataFrame, rng: np.random.Generator
) -> pd.Series:
    """Reassign the real book's long/short weights to random available assets per date.

    Dates where the book needs more names than are available return NaN.
    """
    sel = selected.reindex(index=returns.index, columns=returns.columns)
    out = pd.Series(np.nan, index=returns.index, dtype=float)
    ret_vals = returns.to_numpy(dtype=float)
    w_vals = np.nan_to_num(sel.to_numpy(dtype=float), nan=0.0)
    for i in range(len(returns.index)):
        w = w_vals[i]
        longs = w[w > 0]
        shorts = w[w < 0]
        avail = np.flatnonzero(~np.isnan(ret_vals[i]))
        need = longs.size + shorts.size
        if need == 0:
            out.iloc[i] = 0.0 if avail.size else np.nan
            continue
        if need > avail.size:
            continue
        perm = rng.permutation(avail)
        chosen = perm[:need]
        new_w = np.concatenate([longs, shorts])
        out.iloc[i] = float(np.sum(new_w * ret_vals[i][chosen]))
    return out


def random_event_null(
    values: pd.Series,
    n_events: int | None = None,
    rng: np.random.Generator | None = None,
    *,
    block: pd.Series | None = None,
    block_counts: Mapping | None = None,
) -> float:
    if rng is None:
        raise ValueError("rng is required")
    vals = np.asarray(values, dtype=float)
    if block is not None and block_counts is not None:
        labels = np.asarray(block)
        if labels.size != vals.size:
            raise ValueError("block must align with values")
        picks = []
        for label, k in block_counts.items():
            pos = np.flatnonzero(labels == label)
            if k > pos.size:
                raise ValueError(f"block {label!r} has {pos.size} positions, need {k}")
            picks.append(rng.choice(pos, size=int(k), replace=False))
        idx = np.concatenate(picks) if picks else np.array([], dtype=int)
    else:
        if n_events is None:
            raise ValueError("n_events or block_counts required")
        if n_events > vals.size:
            raise ValueError("n_events exceeds number of values")
        idx = rng.choice(vals.size, size=int(n_events), replace=False)
    if idx.size == 0:
        raise ValueError("no events drawn")
    return float(vals[idx].mean())


def bh_family(p_values: Mapping[str, float], q: float = 0.10) -> dict:
    names = list(p_values)
    ps = [float(p_values[n]) for n in names]
    qs = benjamini_hochberg(ps)
    return {
        n: {"p": p, "q_value": qv, "reject": bool(qv <= q)}
        for n, p, qv in zip(names, ps, qs, strict=True)
    }


_DEFAULT_ALIASES = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
    "XRP": "Ripple",
    "DOGE": "Dogecoin",
    "ADA": "Cardano",
    "BNB": "Binance Coin",
}
_MONTHS = (
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?"
)
_DAY = r"\d{1,2}(?:st|nd|rd|th)?"
_DATE_PATTERNS = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(rf"\b{_MONTHS}\s+{_DAY}(?:,?\s+(?:19|20)\d{{2}})?\b", re.IGNORECASE),
    re.compile(rf"\b{_DAY}\s+{_MONTHS}(?:,?\s+(?:19|20)\d{{2}})?(?!\w)", re.IGNORECASE),
    re.compile(
        r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday"
        r"|Mon|Tues|Tue|Wed|Thurs|Thu|Fri|Sat|Sun)\b",
        re.IGNORECASE,
    ),
]
_YEAR = re.compile(r"\b20\d{2}\b")


def mask_headline(
    text: str, tickers: Iterable[str], aliases: Mapping[str, str] | None = None
) -> str:
    merged = {k.upper(): v for k, v in _DEFAULT_ALIASES.items()}
    if aliases:
        merged.update({k.upper(): v for k, v in aliases.items()})
    names: set[str] = set()
    for t in tickers:
        t_up = str(t).upper()
        names.add(t_up)
        if t_up in merged:
            names.add(merged[t_up])
    out = text
    if names:
        alt = "|".join(re.escape(n) for n in sorted(names, key=lambda s: (-len(s), s)))
        out = re.sub(rf"\$?(?<![\w])(?:{alt})(?![\w])", "<ASSET>", out, flags=re.IGNORECASE)
    for pat in _DATE_PATTERNS:
        out = pat.sub("<DATE>", out)
    return _YEAR.sub("<YEAR>", out)


def assert_single_look(review_date_utc: str, now_utc: pd.Timestamp | None = None) -> None:
    review = pd.Timestamp(review_date_utc)
    review = review.tz_localize("UTC") if review.tzinfo is None else review.tz_convert("UTC")
    now = pd.Timestamp.now(tz="UTC") if now_utc is None else pd.Timestamp(now_utc)
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    if now < review:
        raise PermissionError(f"hypothesis statistics are locked until {review_date_utc}")


def scale_invariance_flag(returns_a: pd.Series, returns_b: pd.Series, tol: float = 1e-6) -> dict:
    a, b = returns_a.align(returns_b, join="inner")
    a = a.astype(float).to_numpy()
    b = b.astype(float).to_numpy()
    if a.size < 3 or a.std() < tol or b.std() < tol:
        return {"flag": False, "corr": None, "slope": None, "std_ratio": None}
    corr = float(np.corrcoef(a, b)[0, 1])
    slope = float(np.cov(a, b, ddof=0)[0, 1] / a.var())
    std_ratio = float(b.std() / a.std())
    flag = bool(corr > 0.999 and slope > 0 and abs(std_ratio - slope) <= 0.01 * std_ratio)
    return {"flag": flag, "corr": corr, "slope": slope, "std_ratio": std_ratio}


def concentration_flag(returns: pd.Series, top_share: float = 0.5) -> dict:
    r = returns.dropna().astype(float)
    total = float(r.sum()) if len(r) else 0.0
    if total <= 0:
        return {"flag": False, "best_day_share": None, "total": total}
    share = float(r.max() / total)
    return {"flag": bool(share > top_share), "best_day_share": share, "total": total}


def boundary_flag(chosen: Mapping[str, float], grid: Mapping[str, Sequence[float]]) -> dict:
    at_boundary = {}
    for name, value in chosen.items():
        g = grid.get(name)
        if not g:
            continue
        if value == min(g) or value == max(g):
            at_boundary[name] = value
    return {"flag": bool(at_boundary), "at_boundary": at_boundary}


def cost_wall_bps(gross_returns: pd.Series, turnover: pd.Series) -> float | None:
    g, t = gross_returns.align(turnover, join="inner")
    if len(g) == 0:
        return None
    gm, tm = float(g.mean()), float(t.mean())
    if gm <= 0 or tm == 0:
        return None
    return float(gm / (tm / 2 / 1e4))
