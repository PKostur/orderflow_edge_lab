# Volatility-state D4 forward replication v1

## Purpose

This watch prospectively tests the strongest PnL-independent state signal carried forward from the self-improvement research:

- causal feature: `local_range_to_spread_15s`;
- primary future-state target: `volatility_expansion_ratio_60s`;
- historical frozen model: one-feature Ridge with median imputation and standard scaling trained only on 12 pre-transfer ENA dependence batches.

The watch does **not** test a trading strategy, direction, session filter, leverage rule, or PnL condition.

## Clean prospective boundary

A provisional 21:00 UTC boundary was drafted, but its commit landed at 21:03:10 UTC. It was therefore superseded before any eligible capture or scoring occurred.

The clean boundary is:

`2026-09-24T21:30:00Z`

The boundary-fix commit `78dd280a48cdad1b37e2433e696f9eb6426e2f97` landed at `2026-09-24T21:03:51Z`.

No observation before 21:30 UTC is eligible for D4 evidence.

## Dependence structure

Each capture records these transfer symbols simultaneously:

- ARB_USDT
- ETH_USDT
- FIL_USDT
- NEAR_USDT
- SOL_USDT
- UNI_USDT

BTC_USDT is recorded only as the existing causal context stream used by the market-state scanner.

All six transfer symbols from one simultaneous capture count as **one dependence cluster**, never six independent trials.

## What is frozen

The primary relation is fixed before D4 collection:

`local_range_to_spread_15s -> volatility_expansion_ratio_60s`

No retraining, feature redefinition, target redefinition, symbol reselection from forward outcomes, threshold tuning, or PnL conditioning is permitted.

The historical Ridge model used only one feature. For a positive one-feature coefficient, rank ordering is invariant to positive affine scaling, so this watch directly measures the feature-to-target rank relationship rather than reconstructing numeric model coefficients. This validates the rank-information mechanism only; it is not an exact numerical-model calibration claim.

## Per-cluster reporting

Every eligible later capture reports:

- per-symbol Spearman correlation for the primary 60-second target;
- median primary Spearman across eligible symbols;
- positive-symbol fraction;
- pooled within-symbol rank correlation;
- target behavior across feature-rank quartiles;
- secondary 30-second and 300-second horizon correlations.

The pooled metric rank-normalizes within symbol before combining observations so symbol-level scale differences do not masquerade as transfer information.

## Review gate

Formal interpretation remains withheld until both are satisfied:

- at least 5 eligible independent later capture clusters;
- at least 3 distinct UTC dates.

An eligible cluster requires at least 20 valid observations for at least 4 of the 6 transfer symbols.

There is no early pass/fail.

## Evidence boundary

This lane is state prediction only.

It cannot establish:

- directional alpha;
- profitable trading edge;
- strategy promotion;
- live-trading authorization;
- leverage authorization.

If the rank relationship survives genuine future clusters, a later strategy family may be designed around a volatility-expansion payoff mechanism. That strategy would require its own new specification, economics, freeze, and future validation.
