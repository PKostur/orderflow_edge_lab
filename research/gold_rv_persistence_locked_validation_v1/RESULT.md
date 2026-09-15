# Gold RV Persistence — Locked 2023 State Validation Result

## Evidence identity

- candidate: `rv_persistence`
- parent development result commit: `66bf7193d5c377b3a137680d96e67d8e7ddf4004`
- validation freeze commit: `05d9fa3d32e2d48f86b25f378c9bcb2f9ba34b6e`
- canonical workflow run: `34990471146`
- canonical scored head: `a07d0bea7502731532b9ec21f3f11dcda2b9cb73`
- artifact: `gold-rv-persistence-locked-validation-v1` (`10405281894`)
- artifact digest: `sha256:3c8efce6658c4292de2b4804f7781321ec4df0a0a46d8f9e275078a934bf1a4e`
- source: pinned Dukascopy XAUUSD M1 bid/ask via `kevingtlin/Market-Data-Lab@922f83a60cc574e7395fb27397077288055a1ef6`
- warmup data: 2022-11 through 2022-12
- locked validation data: 2023-01 through 2023-12
- post-2023 data materialized: **no**
- development period reused for selection: **no**

This is locked later historical validation on the same source, not genuine future OOS and not independent-source replication.

## Frozen candidate

At each frozen weekday New York two-hour anchor, correlate prior-hour relative realized volatility with next-hour relative realized volatility, each normalized by the trailing 20 valid observations at that same clock slot.

Frozen sign: positive.

No feature, lookback, horizon, clock slot, baseline, or threshold was retuned after the 2021-2022 development result.

## Validation result

- validation observations: **2,716**
- scorable New York dates: **256**
- median daily Spearman: **+0.281818**
- positive daily effects: **81.64%**
- one-sided 20,000-epoch sign-flip p-value: **0.000050**
- positive eligible anchor slots: **11 / 11**
- first-half 2023 median daily Spearman: **+0.304545** across 128 dates
- second-half 2023 median daily Spearman: **+0.259091** across 128 dates
- secondary future-range median daily Spearman: **+0.159091**
- locked validation pass: **true**

## Clock-slot breadth

All 11 actually scorable clock slots remained positive:

- 00:00 New York: `+0.4423`
- 02:00: `+0.4989`
- 04:00: `+0.6558`
- 06:00: `+0.5655`
- 08:00: `+0.2153`
- 10:00: `+0.4137`
- 12:00: `+0.6434`
- 14:00: `+0.6252`
- 16:00: `+0.6371`
- 20:00: `+0.5233`
- 22:00: `+0.5285`

The 18:00 New York slot remained unavailable under the exact-bar requirement and was not interpolated.

## Comparison with development

Development 2021-2022 median daily Spearman: `+0.287121`.

Locked 2023 median daily Spearman: `+0.281818`.

The effect therefore retained nearly the same magnitude in the locked later year and broadened from a 77.04% positive-day fraction in development to 81.64% in validation.

This strengthens the evidence that Gold intraday realized volatility clusters persistently at the frozen one-hour horizon under same-clock normalization.

## Gate decision

**PASS: same-source locked historical state validation.**

Every frozen validation requirement passed:

- date count >= 175;
- median daily effect >= +0.15;
- positive-day fraction >= 58%;
- at least eight positive clock slots with >=100 observations;
- positive first-half and second-half effects;
- positive secondary range effect;
- one-sided p <= 0.05.

## What this does not establish

This result does not establish:

- price direction;
- an executable strategy;
- positive trading expectancy;
- independent-source or independent-instrument replication;
- genuine future OOS;
- leverage suitability;
- live-trading readiness.

The previously tested high-volatility breakout-continuation and failed-breakout-reversal monetization ideas both failed and remain rejected. Their failure does not invalidate the volatility-state relationship, but it means the state currently has no validated directional monetization mechanism.

## Next required gate

Replicate the exact `rv_persistence` state on an independent source or instrument without parameter retuning. Same-period cross-source replication is robustness evidence, not future OOS.

Only after independent replication should a new monetization mechanism or future shadow process be considered.
