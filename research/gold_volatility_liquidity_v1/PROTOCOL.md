# Gold Volatility and Liquidity v1

## Research question

Can strictly pre-existing intraday XAUUSD volatility and bid-ask liquidity state predict the magnitude of the next hour's Gold movement after controlling for time-of-day seasonality and ordinary volatility persistence?

This is a volatility-state study, not a directional trading strategy. A positive result would not itself establish profitability. It would only authorize freezing a separate executable mechanism, such as a breakout or volatility-positioning rule, before any PnL is inspected.

## Why this lane is orthogonal

Earlier Gold work already tested and rejected social-media technical strategies, multiple Gold/Silver relative-value lineages, the ratio-momentum candidate at independent-source promotion, Time To Eat mechanical proxies, and scheduled CPI/Employment/FOMC reaction states.

This lane does not reuse those entry rules or their attractive observations. It asks a different question: whether Gold's next-hour realized volatility is conditionally predictable from its own immediately observable volatility and quote-liquidity state.

Published intraday Gold research provides a mechanism-level reason to test this without implying that our exact rules will work. Gold volatility has been shown to exhibit intraday predictability from earlier realized-volatility information, Gold market liquidity and volatility exhibit intraday seasonality, and commodity bid-ask spreads are related to volatility and market quality. These are rationale only. They are not evidence for this frozen implementation.

## Evidence order

1. Freeze source, observation grid, features, target, inference method, and state gates.
2. Score only 2021-2022 development data.
3. Keep 2023 physically absent and logically sealed.
4. Do not score direction, entries, stops, targets, spread costs, leverage, win rate, profit factor, or PnL.
5. If no state hypothesis passes every gate, reject v1.
6. If a state hypothesis passes, freeze a separate executable volatility mechanism before any economic result is viewed.
7. Only a later frozen candidate may open 2023 historical validation.
8. Independent replication and genuine future shadow evidence remain required before leverage or live use.

## Source

Pinned development data:

- repository: `kevingtlin/Market-Data-Lab`
- commit: `922f83a60cc574e7395fb27397077288055a1ef6`
- dataset ID: `XAUUSD-DUKASCOPY-M1-BID-ASK`
- provider: Dukascopy
- instrument: XAUUSD spot Gold
- frequency: one minute
- timestamp: Unix milliseconds in UTC
- bid and ask OHLC stored separately

Only 2020-11 through 2022-12 monthly files may be materialized. No 2023 source file is requested in development.

For each timestamp:

`midpoint OHLC = (bid OHLC + ask OHLC) / 2`

Relative spread in basis points:

`10000 * (ask_close - bid_close) / midpoint_close`

The midpoint is used only for state measurement. It is not an execution assumption.

## Observation grid

Convert UTC timestamps to `America/New_York`.

Eligible anchors are local Monday through Friday at exactly:

`00:00, 02:00, 04:00, 06:00, 08:00, 10:00, 12:00, 14:00, 16:00, 18:00, 20:00, 22:00`

The two-hour spacing ensures adjacent 60-minute forward windows do not overlap.

An anchor is scorable only when all exact bars required by its pre-window and forward window exist. No interpolation is permitted.

## Pre-window and forward window

For anchor `t0`:

- pre-window bars: `t0-60m` through `t0-1m`
- forward-window bars: `t0` through `t0+59m`
- pre realized volatility uses 60 one-minute midpoint log returns ending at `t0-1m`, requiring the additional close at `t0-61m`
- forward realized volatility uses 60 one-minute midpoint log returns beginning with the return from close `t0-1m` to close `t0`

Realized volatility is:

`sqrt(sum(one_minute_log_return^2))`

Pre-range is the midpoint high-low range over the 60 pre-window bars. Future-range is the midpoint high-low range over the 60 forward bars.

## Same-clock causal baselines

Gold volatility, liquidity, and spread have strong intraday seasonality. Raw levels are therefore not compared across clock times without normalization.

For each of the 12 local anchor slots, maintain a trailing median using the prior 20 scorable weekday observations in that same slot. The current observation is always excluded with an explicit one-observation shift.

The baseline is computed separately for:

- pre-60m realized volatility
- future-60m realized volatility
- pre-60m range
- future-60m range
- pre-15m median relative spread

Because a current day's future target is not used in its own baseline, all normalization available at `t0` is causal.

## Frozen state variables

### 1. Pre-RV ratio

`pre_rv_ratio = pre60_rv / trailing_same_clock_median_pre60_rv`

This is the benchmark volatility-persistence state.

### 2. Spread-level ratio

Take the median relative spread over `t0-15m` through `t0-1m`.

`spread_level_ratio = pre15_spread / trailing_same_clock_median_pre15_spread`

### 3. Spread deterioration ratio

`spread_deterioration_ratio = median_spread(t0-15m:t0-1m) / median_spread(t0-60m:t0-16m)`

This asks whether recent quote liquidity has deteriorated relative to the preceding part of the same hour.

### 4. Pre-range ratio

`pre_range_ratio = pre60_high_low / trailing_same_clock_median_pre60_range`

The sign is not assumed. A positive effect would indicate volatility clustering. A negative effect would indicate compression followed by expansion.

### 5. Negative-semivariance share

Using the 60 pre-window one-minute midpoint log returns:

`negative_semivariance_share = sum(r^2 where r<0) / sum(r^2)`

The denominator must be positive.

## Frozen targets

Primary target:

`future_rv_ratio = future60_rv / trailing_same_clock_median_future60_rv`

Secondary robustness target:

`future_range_ratio = future60_high_low / trailing_same_clock_median_future60_range`

No target contains a signed return.

## Frozen hypotheses

Five primary hypotheses form one multiple-testing family.

1. `rv_persistence`: daily Spearman relationship between `pre_rv_ratio` and `future_rv_ratio`.
2. `spread_level_incremental`: daily partial Spearman between `spread_level_ratio` and `future_rv_ratio`, controlling for `pre_rv_ratio`.
3. `spread_deterioration_incremental`: daily partial Spearman between `spread_deterioration_ratio` and `future_rv_ratio`, controlling for `pre_rv_ratio`.
4. `range_state_incremental`: daily partial Spearman between `pre_range_ratio` and `future_rv_ratio`, controlling for `pre_rv_ratio`.
5. `negative_semivariance_incremental`: daily partial Spearman between `negative_semivariance_share` and `future_rv_ratio`, controlling for `pre_rv_ratio`.

For a partial Spearman statistic, rank feature, target, and control within the day's scorable anchors. Regress ranked feature on ranked control and ranked target on ranked control using an intercept. The statistic is the Pearson correlation of the two residual vectors.

A New York date needs at least eight scorable anchors to contribute a daily statistic.

The primary effect for each hypothesis is the median of its daily effects.

## Inference

The New York date is the dependence unit.

For each hypothesis, perform a two-sided 20,000-epoch sign-flip test on the vector of daily effects. This preserves all within-date construction and tests whether the median daily effect is distinguishable from zero.

Apply Benjamini-Hochberg FDR across the five primary p-values. Required q-value is at most 0.10.

No best-cell selection is allowed outside this five-hypothesis family.

## Frozen breadth and robustness checks

For each hypothesis also report:

- number of scorable New York dates
- fraction of daily effects having the discovered primary sign
- 2021 median daily effect
- 2022 median daily effect
- per-anchor-slot effect across development dates
- number of the 12 anchor slots having the primary sign, counting a slot only when it has at least 100 observations
- median daily effect using `future_range_ratio` as the secondary target

For incremental hypotheses, the same partial-correlation construction controlling for `pre_rv_ratio` is used for year, anchor, and secondary-target checks.

## Frozen state gate

A hypothesis is a state candidate only if all applicable conditions pass:

- at least 350 scorable New York dates
- absolute median daily primary effect at least 0.15
- at least 58% of daily effects share the discovered primary sign
- at least 8 of 12 eligible anchor slots share the primary sign
- both 2021 and 2022 median daily effects share the primary sign
- secondary future-range median daily effect shares the primary sign
- BH FDR q at most 0.10

No threshold may be weakened after results are observed.

## Interpretation boundary

A passing result means only that future Gold volatility state contains repeatable conditional information under this frozen spot-data implementation.

It does not mean:

- price direction is predictable
- a breakout strategy is profitable
- options are mispriced
- spread and slippage are covered
- leverage is justified
- live trading is authorized

If state passes, the next stage must specify one executable mechanism before economic scoring. If state fails, economics remains blocked and v1 closes.
