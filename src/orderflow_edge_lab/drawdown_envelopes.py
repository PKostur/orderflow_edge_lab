"""Descriptive forward drawdown envelopes from pre-start backtest returns (stationary block bootstrap).

No verdicts and no thresholds: the functions only describe where a forward track sits relative to the
bootstrap distribution.  See config/forward_drawdown_envelopes_v1.json.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PCTS = (5, 50, 95)
COLUMNS = [f"{k}_p{p}" for k in ("cum", "mdd") for p in PCTS]


def bootstrap_envelopes(returns, horizon: int = 365, paths: int = 5000, block: float = 20.0,
                        seed: int = 20261012, demean: bool = False) -> pd.DataFrame:
    x = np.asarray(returns, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2:
        raise ValueError("need at least 2 returns")
    if demean:
        x = x - x.mean()
    rng = np.random.default_rng(seed)
    idx = np.empty((paths, horizon), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, paths)
    new_block = rng.random((paths, horizon)) < 1.0 / block
    jumps = rng.integers(0, n, (paths, horizon))
    for t in range(1, horizon):
        idx[:, t] = np.where(new_block[:, t], jumps[:, t], (idx[:, t - 1] + 1) % n)
    eq = np.cumprod(1.0 + x[idx], axis=1)
    peak = np.maximum.accumulate(np.maximum(eq, 1.0), axis=1)
    cum = eq - 1.0
    mdd = np.minimum.accumulate(eq / peak - 1.0, axis=1)
    out = {}
    for name, arr in (("cum", cum), ("mdd", mdd)):
        q = np.percentile(arr, PCTS, axis=0)
        for p, row in zip(PCTS, q):
            out[f"{name}_p{p}"] = row
    return pd.DataFrame(out, index=pd.RangeIndex(1, horizon + 1, name="day"))[COLUMNS]


def _band(v: float, p5: float, p50: float, p95: float) -> str:
    if v < p5:
        return "below_p5"
    if v < p50:
        return "p5_p50"
    if v <= p95:
        return "p50_p95"
    return "above_p95"


def position_in_envelope(forward_returns, envelope) -> dict | None:
    """Latest forward day: cumulative return, running max drawdown and the band each falls in."""
    r = np.asarray(forward_returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) == 0:
        return None
    env = envelope if isinstance(envelope, pd.DataFrame) else pd.DataFrame(envelope)
    n = len(r)
    if n > len(env):
        return {"day": n, "beyond_horizon": True}
    eq = np.cumprod(1.0 + r)
    cum = float(eq[-1] - 1.0)
    mdd = float((eq / np.maximum.accumulate(np.maximum(eq, 1.0))).min() - 1.0)
    row = env.iloc[n - 1]
    return {"day": n, "cum": cum, "mdd": mdd,
            "cum_band": _band(cum, row["cum_p5"], row["cum_p50"], row["cum_p95"]),
            "mdd_band": _band(mdd, row["mdd_p5"], row["mdd_p50"], row["mdd_p95"]),
            "cum_p5": float(row["cum_p5"]), "cum_p50": float(row["cum_p50"]), "cum_p95": float(row["cum_p95"]),
            "mdd_p5": float(row["mdd_p5"]), "mdd_p50": float(row["mdd_p50"]), "mdd_p95": float(row["mdd_p95"])}
