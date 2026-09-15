# Gold RV Persistence — MGC Independent Instrument Replication v1

## Purpose

Replicate the exact surviving Gold volatility-state relationship on a different instrument and data source without retuning it.

Parent state candidate: `rv_persistence`.

Parent locked 2023 XAUUSD validation result: PASS at commit `549d8f5928b26bd6ea2de55779047875fb463448`.

This study asks only whether the same prior-hour to next-hour relative realized-volatility persistence exists in CME Micro Gold futures (MGC).

## Evidence classification

This is independent source/instrument replication because:

- parent instrument: spot XAUUSD;
- replication instrument: CME Micro Gold Futures MGC;
- parent provider: Dukascopy;
- replication provider: Databento, distributed through `domzack/mgc-ohlcv-data`.

The replication overlaps the same 2023 historical period used for the locked XAU validation. Therefore it is **not** genuine future OOS.

## Pinned replication source

Repository: `domzack/mgc-ohlcv-data`

Commit: `bf75ac4587e7995ceae64c3d696e076c37be12cc`

The repository documents:

- CME MGC Micro Gold futures;
- Databento API as data source;
- one-minute OHLCV daily CSVs;
- data beginning 2023-01-02;
- a continuous-contract policy based on a 10-day moving average of volume, switching to the more liquid contract.

Databento's OHLCV convention treats the timestamp as the inclusive start of the bar interval. Timestamps are interpreted as UTC under Databento's timestamp conventions.

## Frozen state definition

No parameter from the parent candidate may change.

Frozen New York weekday anchors:

`00:00, 02:00, 04:00, 06:00, 08:00, 10:00, 12:00, 14:00, 16:00, 18:00, 20:00, 22:00`.

For each anchor:

1. require exact one-minute closes for the complete prior 60 minutes and next 60 minutes;
2. compute prior-hour realized volatility as the square root of the sum of squared one-minute log returns;
3. compute next-hour realized volatility identically;
4. divide prior RV by the median of the prior 20 valid MGC observations at the same New York clock slot;
5. divide future RV by the median of the prior 20 valid MGC future-RV observations at that same clock slot;
6. compute next-hour range ratio against the prior-20 same-clock future-range median for the secondary target.

No interpolation is permitted. No spot-XAU baseline is imported.

Because the independent MGC source begins on 2023-01-02, early observations are used causally to accumulate each slot's own 20-observation baseline. A slot becomes scorable only after that history exists.

## Daily effect

For every New York date with at least eight valid frozen anchors:

`daily_effect = Spearman(pre_rv_ratio, future_rv_ratio)`

Secondary daily effect:

`Spearman(pre_rv_ratio, future_range_ratio)`

Frozen candidate sign: positive.

## Statistical test

Exactly one candidate is tested.

Primary inference is a one-sided positive 20,000-epoch sign-flip test on the daily primary effects.

No multiple-testing adjustment is needed because no other feature or candidate is admitted.

## Frozen replication gate

The exact candidate passes independent source/instrument replication only if all requirements hold:

- at least 160 scorable New York dates;
- median daily primary Spearman >= +0.15;
- at least 58% of daily primary effects are positive;
- at least eight eligible clock slots have positive full-period Spearman;
- each counted clock slot has at least 80 observations;
- first-half 2023 median daily effect is positive;
- second-half 2023 median daily effect is positive;
- median secondary future-range daily effect is positive;
- one-sided sign-flip p <= 0.05.

The gate may not be weakened after inspection.

## Continuous-contract and roll diagnostic

The primary candidate is not altered for roll events after observation.

For audit only, report:

- maximum absolute one-minute log return;
- timestamps of the five largest absolute one-minute returns;
- daily primary effects on dates containing those returns when such dates are scorable.

These diagnostics cannot be used to delete observations or rescue a failed result post hoc.

## Prohibited claims

Even a full replication pass establishes only that the volatility-state relationship survives a different Gold instrument and data source in overlapping historical time.

It does not establish:

- price direction;
- a profitable trading strategy;
- executable expectancy after costs;
- genuine future OOS;
- leverage suitability;
- live-trading readiness.

The previously rejected breakout-continuation and failed-breakout-reversal mechanisms remain rejected regardless of this replication result.
