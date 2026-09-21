# Equities relative-reversal replication v2 — terminal status

**Status:** FALSIFIED_D3

The exact original afternoon-relative-reversal family had already failed its August holdout. This independent replication used a disjoint universe (MSFT, AMD, BAC, CVX) and non-overlapping May -> June windows with the original rule and costs unchanged.

- May D0: +21.8554 bps/session at 2 bps cost; all D0 gates passed.
- June D3: -2.3614 bps/session at 2 bps cost and -4.3614 bps/session at 4 bps.
- June reversed control: -1.6386 bps/session.
- Leave-one-name-out June means: AMD omitted -13.4857, BAC omitted -8.9658, CVX omitted +1.2654, MSFT omitted -2.9672 bps/session.

No candidate or future shadow is created. The family may not be rescued by changing names, dates, costs, timestamps or direction under the same ID.
