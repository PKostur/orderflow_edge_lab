"""FOMC-cycle even-week SPY rule (Cieslak, Morse & Vissing-Jorgensen), candidate R2C2 of strategy-search-v1 round 2.

Registered rule: day 0 = the decision day of a scheduled FOMC meeting (second day of two-day meetings).  Cycle days
count weekdays (holidays count as days) from day -1 of the most recent scheduled meeting and reset at every meeting's
day -1.  Hold SPY on trading days whose cycle day lies in week 0 (-1..3), 2 (9..13), 4 (19..23) or 6 (29..33); cash
otherwise (week 7 days and odd weeks).  The position of day ``d`` is set at the close of the previous trading day.

Window shift (G6 perturbation): all even-week windows move together by ``window_shift_days`` weekdays.  Implemented as
shifting every meeting date (and so the reset at its day -1) by the same number of weekdays and applying the base rule;
for shift ``s`` the windows are ``[-1+s, 3+s]``, ``[9+s, 13+s]`` ... measured from the unshifted meeting day.

Descriptive research code: no promotion, no leverage, no order placement.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "fomc_scheduled_meetings_1994_2026.json"
EVEN_WEEK_WINDOWS: tuple[tuple[int, int], ...] = ((-1, 3), (9, 13), (19, 23), (29, 33))
DEFAULT_PARAMS: dict[str, Any] = {"window_shift_days": 0}
SYMBOL = "SPY"


class FomcCycleError(ValueError):
    pass


def load_scheduled_meetings(path: Path | None = None) -> list[pd.Timestamp]:
    """Sorted decision days of the scheduled meetings in the data file (naive midnight timestamps)."""
    payload = json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))
    dates = [d for year in payload["years"].values() for d in year["meetings"]]
    out = sorted(pd.Timestamp(d) for d in dates)
    if any(t.dayofweek >= 5 for t in out):
        raise FomcCycleError("a scheduled meeting falls on a weekend")
    return out


def _d64(values) -> np.ndarray:
    idx = pd.DatetimeIndex(values)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.values.astype("datetime64[D]")


def cycle_days(dates: Sequence[pd.Timestamp] | pd.DatetimeIndex, meetings: Sequence[pd.Timestamp],
               shift_days: int = 0) -> np.ndarray:
    """Cycle day (weekdays since the decision day) of each weekday in ``dates``; NaN before the first cycle starts.

    The cycle of date ``t`` is that of the latest meeting whose day -1 (after the shift) is on or before ``t``.
    """
    m = _d64(meetings)
    if shift_days:
        m = np.busday_offset(m, int(shift_days), roll="raise")
    resets = np.busday_offset(m, -1)
    d = _d64(dates)
    out = np.full(len(d), np.nan)
    pos = np.searchsorted(resets, d, side="right") - 1
    ok = pos >= 0
    if ok.any():
        out[ok] = np.busday_count(m[pos[ok]], d[ok])
    return out


def in_even_week(cycle_day: np.ndarray) -> np.ndarray:
    """True where the cycle day is in week 0, 2, 4 or 6 (False for NaN)."""
    inside = np.zeros(len(cycle_day), dtype=bool)
    finite = np.isfinite(cycle_day)
    for lo, hi in EVEN_WEEK_WINDOWS:
        inside |= finite & (cycle_day >= lo) & (cycle_day <= hi)
    return inside


def week_of(cycle_day: float) -> int | None:
    """Week label (-1, 0, 1, ...) of a cycle day: week 0 = days -1..3, week k = 5k-1 .. 5k+3."""
    if not np.isfinite(cycle_day):
        return None
    return int(np.floor((cycle_day + 1) / 5))


def weights_R2C2_fomc_cycle(data: Mapping[str, Any], params: Mapping[str, Any]) -> pd.DataFrame:
    """SPY weight row ``t`` = 1 if the next trading day is in an even week (decided at the close of ``t``).

    Rows whose next trading day has no cycle yet (before the first scheduled meeting's day -1) are NaN: no signal.
    The next trading day comes from the public trading calendar (``data['_calendar']`` or the price index; after its
    last date the next weekday).
    """
    merged = {**DEFAULT_PARAMS, **dict(params)}
    index = pd.DatetimeIndex(data["prices"].index)
    cal = data.get("_calendar")
    calendar = pd.DatetimeIndex(cal) if cal is not None else index
    nxt = pd.DatetimeIndex(list(calendar[1:]) + [calendar[-1] + pd.offsets.BDay(1)])
    nxt_by_day = pd.Series(nxt, index=calendar)
    next_day = nxt_by_day.reindex(index)
    meetings = load_scheduled_meetings()
    cd = cycle_days(next_day, meetings, int(merged["window_shift_days"]))
    flag = in_even_week(cd).astype(float)
    flag[~np.isfinite(cd)] = np.nan
    return pd.DataFrame({SYMBOL: flag}, index=index)
