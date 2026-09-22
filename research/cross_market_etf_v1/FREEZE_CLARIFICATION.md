# Cross-market ETF v1 — pre-PnL calculation clarification

Frozen before any ETF hypothesis PnL is calculated.

- Returns are arithmetic executable returns: `direction * (exit_open / entry_open - 1) * 10,000` bps.
- Net return subtracts the frozen all-in round-trip friction once: 2 bps primary, 4 bps stress.
- Reversed control uses the exact same decision timestamp, entry and exit with `direction = -original_direction`, and pays the same friction.
- Signal weighting is one signal = one observation; pooled expectancy is the unweighted mean across eligible signals.
- D0 calendar halves are fixed as 2026-07-06..2026-07-17 and 2026-07-20..2026-07-31.
- Any required exact minute missing => that observation is ineligible. No interpolation, forward fill, substitute bar or alternate exit is allowed.
- H1 requires every opening-range minute 09:30..09:44 ET, the signal minute, next-minute entry, and the open exactly 15 minutes after entry.
- H2's 20-return volatility window ends at the signal minute: it contains the 20 exact one-minute close-to-close log returns from signal_time-20m through signal_time. It requires all 21 closes. Sample standard deviation uses denominator n-1. A zero sigma is ineligible. Cumulative VWAP uses minute VWAP weighted by minute volume from 09:30 through the signal minute.
- H3 daily sigma excludes the signal day and uses exactly the prior 20 valid regular-session close-to-close log returns. A valid daily close is the exact 15:59 ET minute close. Gap uses the exact 09:30 ET minute open. Entry is exact 09:31 open; exit exact 10:30 open.
- Positive-PnL concentration is computed from positive ticker contributions only: the largest positive ticker total / sum of positive ticker totals. If no ticker has positive contribution, concentration gate fails.
- A D0 family that fails any frozen D0 survival gate is terminally falsified under that family ID and its August holdout is not inspected.
