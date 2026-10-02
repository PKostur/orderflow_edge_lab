# VOL8 Payoff-Amplitude Forward Watch v1

## Purpose

This is a new prospective observational lane generated from the already-inspected Payoff Geometry v1 historical diagnostic.

The historical diagnostic suggested a specific mechanism worth testing prospectively: for VOL8, LOW and HIGH causal pre-entry volatility had almost identical historical win rates, while HIGH volatility exhibited larger favorable and adverse excursions.

This watch does **not** ask whether HIGH volatility should filter or size VOL8 trades. It asks whether causal volatility rank predicts subsequent excursion amplitude when every original VOL8 trade is retained unchanged.

## Clean boundary

Hypothesis freeze commit:

`75592efc6549b7994c6cf8a683710df2fb825712`

Prospective start:

`2026-09-26T00:00:00Z`

The historical source is Payoff Geometry v1 artifact:

`sha256:f5be7e3aa0fda6ba9d630e5bbe1fc67cc9d91d8d9700bfb2d6d3738e6025b4be`

That historical artifact is hypothesis-generating only and is not independent validation.

## Unchanged trading process

VOL8 remains exactly:

- family: `vol_scaled_momentum`;
- lookback: 24;
- volatility window: 96;
- threshold: 0.5;
- MEXC public Futures 8h;
- same frozen ten-symbol universe;
- canonical accounting v2;
- 20 bps round-trip costs;
- max absolute position 1.

The volatility observation never gates or resizes a position.

## Causal volatility rank

At each canonical trade entry:

1. use the final completed bar strictly before entry;
2. compute 20-bar population standard deviation of close-to-close returns;
3. compare that value with up to the preceding 90 realized-volatility observations;
4. require at least 30 prior values;
5. compute the midrank empirical percentile:
   `(count(history < current) + 0.5 * count(history == current)) / count(history)`.

LOW/MID/HIGH terciles are also retained for interpretation, using the same causal history.

## Frozen relationships

Primary mechanism relationships:

- volatility percentile vs canonical MFE;
- volatility percentile vs absolute canonical MAE.

Separation diagnostic:

- volatility percentile vs correct-direction indicator.

The separation diagnostic is reported rather than assigned a desired sign. Its purpose is to distinguish an amplitude mechanism from a directional-accuracy mechanism.

## Dependence and uncertainty

Trades across symbols and nearby times are not treated as independent observations.

Bootstrap uncertainty resamples seven-day calendar entry blocks, using the same resamples for every reported relationship.

## Review gate

No early pass/fail.

The watch becomes `READY_FOR_REVIEW` only after all of these are true:

- at least 30 calendar days;
- at least 60 completed post-start VOL8 trades;
- at least 6 observed symbols;
- at least 4 distinct seven-day entry blocks.

Even then, the watch only supports review of a payoff-amplitude mechanism. It cannot itself authorize a strategy filter, strategy promotion, live trading, leverage, or volatility-based sizing.
