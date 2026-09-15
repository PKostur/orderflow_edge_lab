# Gold/Silver Macro-Conditioned Relative Value v4 — Implementation Freeze

This file is committed before any v4 development score is produced. It clarifies mechanics left implicit by `config/gold_silver_macro_conditioned_relative_value_v4.json` without changing the research hypothesis.

## Fold mechanics

- Development dependence folds are 126 calendar days anchored at `2010-01-01 UTC`.
- For fold `k`, the state model may train only on qualifying events from folds `< k`.
- At least 8 distinct prior folds and at least 80 prior events are required before scoring a test fold.
- A test fold requires at least 6 qualifying events.
- AUC is computed only if the test fold contains both target classes; no synthetic class or fallback AUC is inserted.
- Training also requires both classes; otherwise that test fold is not scored.

## Macro alignment

- Each FRED series is parsed on its observation date.
- For each XAU/XAG common trading date, only the latest macro observation dated on or before that date may be joined.
- The resulting joined macro state is then lagged by one common XAU/XAG trading bar before feature construction.
- If the lagged source observation is more than 7 calendar days old at the trading date, that feature is treated as missing.
- No future macro observation, interpolation, or backfill is allowed.

## Feature construction

- `vix_percentile_252` is the percentile rank of the lagged VIX observation within the trailing 252 available aligned common-bar observations, including the current lagged value.
- `dfii10_change_20` is lagged DFII10 minus its value 20 common bars earlier.
- `dtwexbgs_log_return_20` is log(lagged dollar index / lagged dollar index 20 common bars earlier).
- Interaction features multiply the frozen innovation side (`sign(z)`) by the corresponding macro feature.
- Feature standardization is fit on training events only and applied unchanged to the test fold.

## State target and model

- Base relative state uses the frozen v3 RLS mechanics with lambda `0.995` and entry `|z| >= 1.5`.
- For each frozen horizon (21 and 42 bars), the target is 1 if the frozen mean-reversion side earns a positive uncosted beta-hedged spread return from next common open to horizon common open, otherwise 0.
- Logistic regression is fit separately for each horizon with frozen `C=1.0`, L2 penalty, `lbfgs`, and no class weighting.
- The constant-rate Brier control predicts the training-set target prevalence for every event in the test fold.
- Fold AUC sign-flip tests operate on `AUC - 0.5`; BH-FDR is applied across the two horizon hypotheses only.

## Economic translation

- Only prequential out-of-fold probabilities are eligible for trading.
- Entry requires predicted success probability `>= 0.60`.
- Trade direction remains the symmetric frozen mean-reversion side `-sign(z)`; v4 is not allowed to suppress one direction by rule.
- Entry is next common open; exit is the common open after the horizon matching the model target.
- A trade is discarded if its exit would leave the signal's 126-calendar-day dependence fold.
- Eligible events are processed chronologically with one active position; a new signal is ignored until the prior trade exits.
- Beta hedge weights are frozen from the signal-time pre-update RLS beta.
- Primary cost is 10 bps on total gross two-leg notional; high-cost stress is 20 bps.
- Long-spread and short-spread subsets must independently satisfy the frozen directional economics gate.

## Controls

- Unfiltered adaptive-reversion control uses all otherwise-admissible `|z|>=1.5` events at the same horizon, subject to identical one-active and fold-boundary rules.
- Reversed-direction control flips the filtered strategy side and pays the same cost.
- Unhedged-gold and equal-dollar gold-minus-silver controls use the same filtered signal timestamps and side.

No development result existed when this implementation freeze was committed.