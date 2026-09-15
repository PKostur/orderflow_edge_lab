# Gold RV Persistence — Locked 2023 State Validation Freeze

## Candidate identity

Only one development candidate is admitted:

`rv_persistence`

Parent development result:

- parent protocol: `gold-volatility-liquidity-v1`
- parent result commit: `66bf7193d5c377b3a137680d96e67d8e7ddf4004`
- parent canonical workflow run: `34986544522`
- parent artifact: `10403373273`
- development median daily Spearman: `+0.287121`
- development daily positive fraction: `77.04%`
- development secondary future-range effect: `+0.140909`

No other development hypothesis is admitted to validation.

## Frozen state definition

At each weekday New York anchor time 00:00, 02:00, 04:00, 06:00, 08:00, 10:00, 12:00, 14:00, 16:00, 18:00, 20:00, 22:00:

1. compute realized volatility from one-minute midpoint log returns over the previous 60 minutes;
2. divide by the median of the prior 20 valid observations at the same New York clock slot to obtain `pre_rv_ratio`;
3. compute realized volatility over the next 60 minutes and divide it by its prior-20 same-clock median to obtain `future_rv_ratio`;
4. compute next-hour range ratio analogously for the secondary target.

Daily primary effect: Spearman correlation between `pre_rv_ratio` and `future_rv_ratio` across valid anchors on that New York date. At least eight anchors are required for a daily effect.

Frozen sign: positive.

No feature, target, clock slot, lookback, window, or transformation may be changed after this freeze.

## Locked validation boundary

- warmup may use only 2022-11-01 through 2022-12-31 to seed same-clock baselines;
- locked validation scoring uses only 2023-01-01 through 2023-12-31;
- 2021-2022 development results are not recomputed for selection;
- 2024+ data are not used;
- this is retrospective locked historical validation, not genuine future OOS.

## Frozen validation inference

Exactly one candidate is tested, so there is no multiple-testing family.

Primary inference is a one-sided positive 20,000-epoch sign-flip test on daily Spearman effects.

The candidate passes only if all conditions hold:

- at least 175 scorable New York dates;
- median daily Spearman >= +0.15;
- at least 58% of daily effects are positive;
- at least eight clock slots have positive full-year Spearman with at least 100 observations each;
- first-half 2023 median daily Spearman is positive;
- second-half 2023 median daily Spearman is positive;
- secondary future-range median daily Spearman is positive;
- one-sided sign-flip p <= 0.05.

The gate may not be weakened after validation is opened.

## Claims

A validation pass would mean only that the same Gold volatility-state relationship survives a locked later historical year on the same pinned Dukascopy source.

It would not establish price direction, executable trade edge, profitability, independent-source replication, future OOS, leverage suitability, or live readiness.
