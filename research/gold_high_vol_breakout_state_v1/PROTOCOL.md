# Gold High-Volatility Breakout State v1

## Status

This is a post-observation mechanism-generation study. The parent `gold-volatility-liquidity-v1` development study found a robust next-hour realized-volatility persistence state in 2021-2022. This child hypothesis is generated from that observation and is therefore not independent confirmation.

The locked 2023 historical validation remains unopened.

## Question

When the previous hour's realized volatility is already elevated relative to its own same-clock history, does a confirmed break of the previous hour's price range tend to continue afterward rather than reverse?

The purpose is to test direction before execution economics. No fill model, commission, slippage, stop, target, position sizing, leverage, win rate, profit factor, or PnL is used here.

## Parent state

The parent state variable is retained exactly:

`pre_rv_ratio = pre60_realized_volatility / trailing_20_same_clock_median_pre60_realized_volatility`

Primary high-volatility activation:

`pre_rv_ratio >= 1.25`

Normal-state control:

`0.75 <= pre_rv_ratio < 1.00`

The primary threshold is fixed before breakout results are inspected. Thresholds `1.00` and `1.50` are robustness checks only and cannot replace a failed primary threshold.

## Observation grid and source

Use the parent source and grid unchanged:

- pinned Dukascopy XAUUSD M1 bid/ask data from `kevingtlin/Market-Data-Lab@922f83a60cc574e7395fb27397077288055a1ef6`
- midpoint OHLC for state measurement
- New York weekday anchors every two hours from 00:00 through 22:00
- 2020-11 and 2020-12 warmup for same-clock baselines
- 2021-2022 development scoring
- no 2023 source file in development

Missing exact bars are not interpolated.

## Breakout definition

For anchor `t0`, freeze the previous hour's midpoint boundaries:

- `pre_high`: highest midpoint high from `t0-60m` through `t0-1m`
- `pre_low`: lowest midpoint low from the same window
- `pre_range = pre_high - pre_low`

Define a buffer equal to `0.05 * pre_range`.

Search only the first 30 one-minute bars beginning at `t0`.

The first one-minute midpoint close satisfying either condition confirms the event:

- long breakout: `close > pre_high + buffer`
- short breakout: `close < pre_low - buffer`

If no close qualifies, there is no breakout event for that anchor.

The first qualifying close fixes direction permanently. No later reversal changes the event label.

## State score

Let `tb` be the timestamp of the breakout confirmation bar and `Pb` its midpoint close.

For horizon `h` in 15, 30, 60 minutes, use the midpoint close of the bar opening at `tb + h minutes`.

Breakout continuation score:

`direction * (future_close_h - Pb) / pre_range`

Positive means continuation after the confirmed break. Negative means reversal.

Primary horizon: 30 minutes after confirmation.

This is a normalized state response, not a simulated trade return.

## Primary comparison

On each New York date with at least one primary high-RV breakout and at least one normal-control breakout, calculate:

`daily_contrast = median(high_RV_30m_scores) - median(normal_RV_30m_scores)`

The primary effect is the median daily contrast across development dates.

Inference uses a two-sided 20,000-epoch sign-flip test on daily contrasts. Required p-value is at most 0.05.

## Breadth controls

A state promotion also requires all of the following:

- at least 250 high-RV breakout events
- at least 250 normal-control breakout events
- at least 150 New York dates with a high-minus-normal contrast
- absolute median daily contrast at least 0.10 prior-hour ranges
- at least 58% of daily contrasts share the discovered primary sign
- high-RV breakout events themselves have median continuation at least +0.05 prior-hour ranges
- at least 55% of high-RV breakout events have positive 30-minute continuation
- at least 100 high-RV long breakout events and 100 high-RV short breakout events
- high-RV long and short breakout median scores are both positive
- 2021 and 2022 median daily contrasts share the primary sign
- at least two of the 15, 30, and 60-minute high-minus-normal effects share the primary sign
- robustness activation thresholds 1.00 and 1.50 both produce the primary sign

These gates are deliberately stricter than statistical significance alone. In particular, the long/short breadth gate is intended to reject a result that is merely long-Gold beta.

## Decision boundary

If this state test fails, do not open PnL and do not retune the threshold, breakout buffer, confirmation window, or horizons inside v1.

If it passes, freeze one execution specification using bid/ask prices and realistic costs before development economics are run.
