# FX Asian-range breakout v1 — pre-PnL calculation clarification

Frozen before any FX strategy PnL is calculated.

- Hourly bar timestamps are interpreted from their Unix timestamps in UTC.
- A bar stamped 06:00 UTC represents the 06:00-06:59 hour. Its close becomes known at 07:00; therefore a signal on that bar enters at the exact 07:00 bar open.
- The six Asian-range bars 00:00 through 05:00 UTC are all mandatory.
- Search proceeds chronologically through bars stamped 06:00, 07:00, 08:00, and 09:00 UTC. The first qualifying close fixes the direction and ends the search.
- If an earlier search bar is missing before a later possible breakout, the pair-day is ineligible because signal chronology cannot be reconstructed exactly.
- Once a signal occurs, later search bars are irrelevant. The exact next-hour entry bar and the exact 16:00 UTC exit bar remain mandatory.
- If no qualifying close occurs by the 09:00 bar, the pair-day has no signal.
- Gross and net returns are arithmetic bps exactly as in FREEZE.json. The reversed control flips direction only and pays identical friction.
- Distinct signal days count unique UTC dates with at least one eligible signal across the four pairs.
- Pair contribution for the concentration gate is the sum of primary-friction net bps for that pair across D0. Among pairs with positive totals, concentration = largest positive pair total / sum of positive pair totals. If no pair total is positive, the gate fails.
- D0 half gates use the fixed UTC date ranges in FREEZE.json.
- D3 remains sealed unless every D0 gate passes.
