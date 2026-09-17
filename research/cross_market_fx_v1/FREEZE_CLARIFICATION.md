# Cross-market FX v1 — pre-PnL calculation clarification

Frozen before any FX hypothesis PnL is calculated.

- Eligible research days are Monday through Friday UTC within the frozen date windows. Weekend/Sunday partial sessions are excluded from session counts and cannot generate signals.
- FX_H1 requires exactly 420 one-minute bars from 00:00 through 06:59 UTC. It also requires an unbroken one-minute sequence from 07:00 through the selected first breakout signal; otherwise the day is ineligible because an earlier breakout could have occurred in a missing minute.
- FX_H1 entry is the exact next-minute open after the signal. Exit is the exact open 60 minutes after entry (`signal_time + 61 minutes`).
- FX_H2 requires exact bars at 07:00, 11:59, 12:01 and 15:00 UTC. The 07:00 open and 11:59 close define direction; 12:01 open is entry and 15:00 open is exit.
- Arithmetic return, friction, reversed-control construction and equal signal weighting are exactly as defined in FREEZE.json.
- Positive-PnL concentration is the largest positive pair total divided by the sum of positive pair totals. If no pair has positive contribution, the concentration gate fails.
- D0 session-count gates count distinct eligible UTC weekdays with at least one eligible signal across the family.
