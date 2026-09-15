# Gold High-Vol Failed-Breakout Reversal v1

## Status

Frozen post-observation state protocol. Economics are disabled.

This hypothesis was generated only after `gold-high-vol-breakout-state-v1` showed negative median continuation for both long and short high-volatility breakouts. It is therefore a new child hypothesis, not a rescue of the rejected continuation protocol and not independent confirmation.

## Evidence boundary

- development only: 2021-01-01 through 2022-12-31;
- warmup: 2020-11-01 onward for same-clock volatility baselines;
- 2023 is locked historical validation and must remain physically absent from the state input;
- no future-OOS claim is permitted;
- no economic scoring is permitted unless this state gate passes and a separate execution protocol is frozen first.

## Source

Pinned `kevingtlin/Market-Data-Lab@922f83a60cc574e7395fb27397077288055a1ef6`, XAUUSD Dukascopy M1 bid/ask UTC data. State prices use synchronized bid/ask midpoint OHLC.

## Anchor grid and volatility state

Use New York weekday anchor times 00:00, 02:00, 04:00, 06:00, 08:00, 10:00, 12:00, 14:00, 16:00, 18:00, 20:00, 22:00.

For each anchor, compute realized volatility over the complete prior 60 minutes and normalize it against the median prior 20 valid observations at that same New York clock slot.

Primary high-volatility state: RV ratio >= 1.25.

Normal-volatility control: 0.75 <= RV ratio < 1.0.

Robustness thresholds: RV ratio >= 1.0 and >= 1.5.

## Breakout confirmation

Define the prior-hour midpoint high, low, and range over `t0-60m` through `t0-1m`.

Within the first 30 minutes after `t0`, the first one-minute midpoint close beyond the prior-hour boundary plus a 5% prior-range buffer confirms the original breakout:

- long breakout: close > prior high + 0.05 * prior range;
- short breakout: close < prior low - 0.05 * prior range.

No confirmed break means no event.

## Failed-breakout confirmation

After the breakout confirmation, inspect the next 15 complete one-minute closes.

A long breakout fails at the first close back at or below the original prior-hour high, provided that close is also within the original prior-hour range.

A short breakout fails at the first close back at or above the original prior-hour low, provided that close is also within the original prior-hour range.

The first such re-entry close is the failure-confirmation price. If no such close occurs within 15 minutes, the breakout is not a failed-breakout event.

No interpolation or intrabar inference is allowed.

## Reversal state score

At 15, 30, and 60 minutes after failed-breakout confirmation:

`reversal_score = (-breakout_direction) * (future_midpoint_close - failure_close) / prior_hour_range`

Positive means price continues in the direction opposite the failed breakout. Negative means the original breakout direction reasserts itself.

Primary horizon: 30 minutes.

This is a state score, not PnL.

## Primary test

For every New York date that has both high-RV and normal-control failed-breakout observations, compute:

`median(high-RV reversal scores) - median(normal-control reversal scores)`

The primary statistic is the median daily contrast at 30 minutes.

Inference uses a two-sided 20,000-epoch sign-flip test on daily contrasts.

## Frozen gate

The candidate passes only if every applicable condition is satisfied:

- at least 150 high-RV failed-breakout events;
- at least 250 normal-control failed-breakout events;
- at least 100 matched daily contrast dates;
- absolute primary median daily contrast >= 0.08 prior-hour ranges and discovered sign positive;
- at least 58% of daily contrasts carry the primary sign;
- high-RV failed-breakout median reversal >= +0.05 prior-hour ranges;
- high-RV positive-reversal fraction >= 55%;
- at least 60 high-RV events from each original breakout direction;
- both original long-breakout and short-breakout groups must have positive median reversal scores;
- both 2021 and 2022 daily contrasts must share the primary sign;
- at least two of 15m, 30m, and 60m daily contrasts must share the primary sign;
- RV >= 1.0 and RV >= 1.5 robustness contrasts must share the primary sign;
- two-sided sign-flip p <= 0.05.

The gate may not be weakened after inspection.

## Prohibited claims and actions

At this stage there are no entries, stops, targets, costs, spread/slippage execution assumptions, leverage, win rate, profit factor, or trade PnL.

A passing result would establish only a development-period failed-breakout reversal state relationship. It would not establish an executable or profitable strategy, independent confirmation, future OOS, leverage suitability, or live-trading readiness.
