"""Truncation-invariance (lookahead) check, after freqtrade's lookahead-analysis.

A signal/feature function is causal if its output at row t is identical whether it is
computed on the full data or on data truncated at t.  Descriptive tooling only.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd


def _truncate(obj: Any, date: pd.Timestamp) -> Any:
    if isinstance(obj, Mapping):
        return {k: _truncate(v, date) for k, v in obj.items()}
    if isinstance(obj, (pd.Series, pd.DataFrame)):
        return obj.loc[obj.index <= date]
    return obj


def _row(obj: Any, date: pd.Timestamp) -> Any:
    if isinstance(obj, Mapping):
        return {k: _row(v, date) for k, v in obj.items()}
    if date not in obj.index:
        return None
    return obj.loc[date]


def _equal(a: Any, b: Any, atol: float) -> bool:
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_equal(a[k], b[k], atol) for k in a)
    if a is None or b is None:
        return a is None and b is None
    x = np.atleast_1d(np.asarray(a, dtype=float))
    y = np.atleast_1d(np.asarray(b, dtype=float))
    if x.shape != y.shape:
        return False
    if not np.array_equal(np.isnan(x), np.isnan(y)):
        return False
    m = ~np.isnan(x)
    return bool(np.allclose(x[m], y[m], rtol=0.0, atol=atol)) if atol > 0 else bool(np.array_equal(x[m], y[m]))


def check_truncation(fn: Callable[[Any], Any], data: Mapping[str, Any], dates, *, compare: str = "row",
                     atol: float = 0.0) -> dict[str, Any]:
    """Compare fn(data) at each probe date with fn(data truncated to index <= date) at that date.

    ``data`` may nest dicts of Series/DataFrames.  ``compare="row"`` compares the row at the date;
    ``compare="history"`` compares every row up to and including the date.
    """
    if compare not in ("row", "history"):
        raise ValueError("compare must be 'row' or 'history'")
    full = fn(data)
    mismatches = []
    dates = list(dates)
    for d in dates:
        d = pd.Timestamp(d)
        part = fn(_truncate(data, d))
        if compare == "row":
            ok = _equal(_row(full, d), _row(part, d), atol)
        else:
            ok = _equal(_truncate(full, d), part, atol) if not _both_frames(full, part) else _hist_equal(full, part, d, atol)
        if not ok:
            mismatches.append(d)
    return {"n_dates": len(dates), "mismatches": mismatches, "pass": not mismatches}


def _both_frames(a: Any, b: Any) -> bool:
    return isinstance(a, (pd.Series, pd.DataFrame)) and isinstance(b, (pd.Series, pd.DataFrame))


def _hist_equal(full: Any, part: Any, d: pd.Timestamp, atol: float) -> bool:
    f = full.loc[full.index <= d]
    if not f.index.equals(part.index):
        return False
    return _equal(f.to_numpy(dtype=float), part.to_numpy(dtype=float), atol)


def random_probe_dates(index: pd.Index, n: int, seed: int) -> list[pd.Timestamp]:
    """n sorted dates drawn without replacement from index (fixed seed)."""
    rng = np.random.default_rng(seed)
    n = min(n, len(index))
    pick = np.sort(rng.choice(len(index), size=n, replace=False))
    return [pd.Timestamp(index[i]) for i in pick]
