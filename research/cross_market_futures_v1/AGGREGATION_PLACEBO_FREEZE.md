# Cross-market futures v1 — aggregation and placebo clarification

Frozen before any real non-crypto futures tick PnL is inspected.

## Primary D0 family statistic

The four frozen horizons (1s, 5s, 15s, 30s) are **not selectable after results**.

For each unique signal identified by capture session, market root, family, signal timestamp, and signal side:

1. Use the frozen **one-extra-round-trip-tick** economics.
2. Require complete original and reversed-control outcomes at **all four** frozen horizons.
3. Compute the signal-level original composite as the equal-weight arithmetic mean of its 1s, 5s, 15s, and 30s net-bps outcomes.
4. Compute the signal-level reversed composite the same way.
5. If any frozen horizon is missing for either control, that signal is ineligible for the primary family statistic. It may remain in horizon-level diagnostics.

All D0 family gates apply to these signal-level composites. The minimum-total-signals gate counts unique eligible composite signals, not horizon rows.

Market-level expectancy, pooled expectancy, and positive-PnL concentration are computed from the same composite signals. Individual horizons are diagnostic and cannot independently create a survivor in v1.

## Dependence identity and duplicates

The primary dependence cluster is the already-frozen tuple:

`(market_root, native_contract, capture_session)`.

Aggregation requires an explicit manifest binding each replay report to a capture-session ID and native contract. Duplicate source SHA-256 values are rejected. A report whose root or native contract disagrees with the manifest is rejected.

## Deterministic time-shift placebo

A D0 survivor cannot create a new candidate ID until the following time-shift diagnostic is complete.

Frozen placebo shifts: **-300s, -60s, +60s, +300s**.

For each original signal and each shift:

- Preserve family and signal side.
- Shift only the decision timestamp within the same capture session; no circular wrapping across session boundaries.
- Entry state is the most recent causal valid BBO at or before the shifted timestamp, no older than the frozen **1.0-second** quote-age bound.
- Exit is the first valid quote at or after each shifted target horizon, matching the original exit convention.
- Require all four frozen horizons and the one-extra-round-trip-tick economics; otherwise that signal is ineligible for that shift.
- A shift is interpretable only when at least **80%** of the family’s eligible original composite-signal count remains eligible under that shift.

Candidate-freeze placebo rule: all four shifts must be interpretable and the original pooled composite mean must be **strictly greater than the maximum pooled composite mean across the four shifts**. If coverage is insufficient, the placebo is inconclusive and candidate freeze is blocked. This placebo rule does not retroactively rescue a D0 failure.

## Session-block bootstrap diagnostic

For every family with at least five independent capture sessions, report a session-cluster bootstrap of the original composite mean using **10,000** resamples with replacement and deterministic seed **20260917**. Report the 2.5%, 50%, and 97.5% percentiles. This remains diagnostic, as frozen in the original protocol.

## Economics boundary

Commission/exchange fees and market impact remain unresolved in v1. No result may be promoted by assuming these are zero. A transfer survivor can only create a separately frozen candidate ID; it is not live or leverage evidence.
