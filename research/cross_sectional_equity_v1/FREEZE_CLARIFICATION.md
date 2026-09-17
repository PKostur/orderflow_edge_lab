# Cross-sectional equity v1 — pre-PnL calculation clarification

Frozen before any strategy PnL is calculated.

- All dates/times are America/New_York; July 2026 timestamps are evaluated at UTC-4.
- Feature ranks use raw frozen feature values with no winsorization, clipping, volatility scaling, sector adjustment, or market-beta adjustment.
- Rank ties are broken deterministically by ticker ascending. For ascending ranks, the first two are the bottom pair and the last two are the top pair.
- Each selected leg gross return is `direction * (exit_open / entry_open - 1) * 10,000` bps.
- Primary net leg return subtracts 3.0 bps once; stress net leg return subtracts 6.0 bps once.
- A daily portfolio return is the arithmetic mean of the four selected leg net returns. The reversed control uses the same four names, entry/exit timestamps and rankings with every direction multiplied by -1, and pays identical friction.
- Each leg contributes one quarter of its net bps to portfolio PnL. Name contribution is the sum of those quarter-weighted contributions across eligible D0 days. Positive-contribution concentration is the largest positive name contribution divided by the sum of positive name contributions; if none are positive the gate fails.
- `minimum_distinct_names_selected` counts unique tickers appearing in any of the four portfolio legs during the D0 window.
- H1 requires exact 09:30, 10:00, 10:01 and 11:00 bars for all eight names on the same date.
- H2 requires exact 09:30, 10:30, 10:31 and 15:30 bars for all eight names on the same date.
- H3 uses the immediately preceding common valid US regular session date for which all eight names have an exact 15:59 close. The current date requires exact 09:30, 09:31 and 10:30 bars for all eight names. It never skips backward past a common valid prior session to rescue a missing current/prior timestamp.
- D0 halves remain 2026-07-06..2026-07-17 and 2026-07-20..2026-07-31.
- A family failing any D0 gate is terminally falsified under that ID and its August strategy performance is not computed.