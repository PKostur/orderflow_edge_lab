# Time To Eat / Nick Stewart v1 State Protocol

## Purpose

This is a state-only development protocol. It does not score trade PnL, claimed win rate, stops, partials, runners, or leverage.

The source material leaves several chart-reading concepts discretionary. Rather than pretending those concepts are exact machine rules, this protocol freezes conservative research proxies before any state result is seen. A passing proxy is evidence that a source-described setup contains directional state information. It is not yet evidence that Nick Stewart's exact discretionary implementation has positive expectancy.

## Open and sealed periods

Open development period: 2021-01-01 through 2022-12-31.

Locked historical validation: 2023-01-01 through 2023-12-31.

The 2023 period remains sealed unless development state evidence supports a candidate and a separate economic specification is later frozen. Even a successful 2023 test would be locked historical validation, not future OOS.

## Markets

Primary gold development source: XAUUSD cash minute data. This is a development proxy for the native Gold/GC use case, not an independent GC futures replication.

Secondary native market: NQ futures.

Predeclared transfer-only market: ES futures.

The same setup parameters are used across symbols. Same-period cross-symbol success is transfer evidence only.

## Timeframes

Daily and 4-hour bars provide directional context. The execution-timeframe primary test is 30 minutes because Nick explicitly identifies 30 minutes as his preferred Playbook timeframe. Fifteen minutes and 1 hour are robustness checks only.

All bars are built in `America/New_York`. The deterministic 4-hour research anchor is midnight New York time. This anchoring convention is an operationalization, not a sourced claim.

## Directional bias proxy

Long eligibility requires the last fully closed Daily candle and last fully closed 4-hour candle both to have `close > open`.

Short eligibility requires both to have `close < open`.

Otherwise the bar is ineligible for directional Playbook state testing.

This directly follows the source example of a bullish Daily and bullish prior 4-hour candle while avoiding extra indicators or post-hoc trend filters.

## New York activity window

Only confirmations timestamped from 08:30 through 11:30 New York time are eligible.

This is a time-based proxy for Nick's repeated requirement that the plays work best when volume is present around New York, macro releases, and the NYSE open. No volume threshold or economic-news filter is added in state v1 because the source does not provide a deterministic threshold.

## Range proxy

A potential range is the immediately preceding 4, 6, or 8 completed execution bars.

For each predeclared lookback:

- upper boundary is the maximum high;
- lower boundary is the minimum low;
- total width must be no more than 1.5 times ATR(14) on the execution timeframe;
- median candle body fraction, `abs(close-open)/(high-low)`, must be no more than 0.60.

All three lookbacks are frozen before results. They are a finite discovery grid, not parameters to be extended after results. FDR is applied across the full state family.

## Breakout state event

A Breakout confirmation occurs when the current completed execution bar closes strictly beyond the frozen range boundary in the higher-timeframe bias direction.

No entry trigger is modeled at the state stage. The state clock starts at confirmation close.

## Celery / Booby Trap state event

A Celery confirmation requires a valid Breakout confirmation immediately followed by another completed execution bar that still closes beyond the same pre-breakout range boundary.

The confirmation bar's body color is ignored, matching the source rule that the candle may close bullish or bearish as long as it remains outside the range.

## Onion state event

The Onion proxy requires higher-timeframe bias alignment and at least one opposite-direction pullback bar.

For a bullish Onion:

- the immediately preceding bar is bearish;
- the confirmation bar is bullish;
- the confirmation-bar low is less than or equal to the lows of each of the prior two execution bars.

For a bearish Onion the conditions are mirrored.

This is a deterministic proxy for a pullback followed by support/resistance formation. It is not claimed to be Nick's exact visual definition of strong support or resistance.

## Fade state event

Fade direction is opposite the higher-timeframe bias.

A target proxy is present when the current execution close lies within 0.15 execution ATR of the bias-direction rolling 20-bar 4-hour extreme.

A bearish Fade after bullish bias requires the execution bar to fail to extend the prior execution high and close bearish. A bullish Fade after bearish bias is mirrored.

This is intentionally conservative and remains labeled as a target-tapped proxy rather than an exact reconstruction.

## State outcomes

For every event, measure the source-direction forward close return after 1, 2, and 4 execution bars and divide by ATR(14) known at event time.

To avoid confusing generic Daily/4-hour drift with setup information, subtract a same-symbol, same-New-York-date, same-session, same-bias benchmark: the median forward signed ATR-normalized return of all eligible bars for that date and horizon.

The resulting quantity is `event_excess_state_return`.

Dependence is clustered by New York trading date. The date is the unit used for positive-day fractions and sign-flip permutation tests.

The reversed-direction state control is reported for every setup.

## Frozen state gate

A cell requires all of the following:

- at least 25 events;
- at least 15 active New York dates;
- positive median daily excess state return;
- at least 60% of active dates positive;
- at least two of the three forward horizons positive;
- 20,000-cluster sign-flip permutation test;
- Benjamini-Hochberg FDR q <= 0.10 across the complete state family.

For any candidate to justify economic work, the 30-minute version must pass and the same setup/symbol must be directionally positive on at least one adjacent execution timeframe.

No economic parameter may be selected from the state test.

## Prohibited interpretations

A state pass does not establish:

- a 75% win rate;
- profitable expectancy;
- an executable entry edge;
- a valid stop/target model;
- future OOS evidence;
- leverage authorization;
- live-trading authorization.

Those claims require later frozen stages.
