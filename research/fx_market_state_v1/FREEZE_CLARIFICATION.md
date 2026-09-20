# FX market-state v1 — pre-result calculation clarification

Frozen after data-integrity inspection only and before any hypothesis effect/result is calculated.

- A decision timestamp is eligible only when every exact one-minute close/return required by that family's lookback and 15-minute target exists.
- Decision timestamps are exactly 12:00, 12:15, ..., 15:45 UTC on Monday-Friday sessions.
- D0 calendar halves are fixed as 2026-07-06..2026-07-17 and 2026-07-20..2026-07-31.
- H1 positive-pair means that pair's triggered mean signed future target is > 0 bps. H1 half-positive means the pooled triggered mean signed future target is > 0 bps in that half.
- H2 control is computed on all H2-eligible grid timestamps for the same pair and same evaluation slice (full D0, each pair, or each D0 calendar half as applicable), regardless of whether the 1.50 trigger fired.
- H2 pair effect = that pair's triggered mean future-volatility ratio minus that pair's all-eligible control mean. A positive pair has effect > 0.
- H2 pooled D0 survival requires triggered-minus-control mean ratio > 0.10. The generic both-calendar-halves-positive gate means H2 effect > 0 in each frozen D0 half; it does not require > 0.10 in each half.
- H3 positive-pair means that pair's triggered mean signed reversion target is > 0 bps. H3 half-positive means the pooled triggered mean signed reversion target is > 0 bps in that half.
- H1 and H3 secondary accuracy metrics count target > 0 as success; target = 0 is not a success.
- "Minimum positive pairs" applies independently to every family and requires at least 3 of the 4 frozen pairs.
- No p-value or bootstrap threshold is being added after seeing results. This version is a state-screening protocol, not a candidate promotion test.
