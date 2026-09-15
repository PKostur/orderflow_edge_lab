# Gold RV Persistence — HistData 2024 Later-Period Replication v2

## Purpose

Test the exact frozen `rv_persistence` state in calendar 2024 on the independent HistData XAUUSD feed, after the candidate survived 2021–2022 development, locked Dukascopy 2023 validation, and showed strong but breadth-limited robustness on MGC/Databento and HistData 2023.

No parent state parameter or replication threshold is changed.

## Evidence classification

This is:

- independent-source replication because the parent locked source was Dukascopy and this source is HistData;
- same-instrument replication because both are spot XAUUSD;
- later historical OOS because calendar 2024 is later than every 2021–2023 parent development/validation period;
- not prospective future OOS, because 2024 is already historical at protocol freeze time.

A pass cannot be described as live, profitable, directional, or prospective evidence.

## Pinned source

Repository: `blackmoon87/forex-histdata-m1`

Commit: `208e67d7bda5cd5536df27531704e07fe4d54641`

Warmup archive:

- `HISTDATA_COM_ASCII_XAUUSD_M12023.zip`
- SHA256 `89a4f3f7ec2a52b29fbce8d4ca2ab650971817ae371b332f5fe471a488bcffc2`
- 3,629,564 bytes.

Replication archive:

- `HISTDATA_COM_ASCII_XAUUSD_M12024.zip`
- SHA256 `6d47f5cb269e0c4f35c63c7532713aae7dcf98901f605458b00dd6a69e7105de`
- 4,358,732 bytes.

HistData Generic ASCII M1 bars are bid OHLCV with timestamps in fixed EST UTC-05:00 without daylight-saving adjustments. Parse the raw clock in fixed UTC-05:00, convert the instant to UTC, then convert to `America/New_York` for the frozen anchor grid.

## Frozen state definition

Weekday New York anchors remain:

`00:00, 02:00, 04:00, 06:00, 08:00, 10:00, 12:00, 14:00, 16:00, 18:00, 20:00, 22:00`.

For each valid anchor:

1. require exact one-minute bars for the complete prior and next 60-minute windows, with no interpolation;
2. compute prior and next realized volatility as square root of summed squared one-minute log close returns;
3. normalize prior RV by its preceding 20-valid-observation same-clock median;
4. normalize future RV by its preceding 20-valid-observation same-clock median;
5. normalize future high-low range by its preceding 20-valid-observation same-clock median for the secondary target.

The candidate is the positive relationship `pre_rv_ratio -> future_rv_ratio`.

Only anchors in calendar 2024 New York time enter inference. November–December 2023 may only provide causal baseline warmup.

## Frozen inference

For each New York date with at least eight valid anchors:

`daily_effect = Spearman(pre_rv_ratio, future_rv_ratio)`.

Secondary effect:

`Spearman(pre_rv_ratio, future_range_ratio)`.

Primary inference is a one-sided positive 20,000-epoch sign-flip test on daily primary effects. Exactly one candidate is tested.

The year is split at 2024-07-01 for the unchanged first-half/second-half sign audit.

## Frozen replication gate

All conditions are required:

- at least 160 scorable New York dates;
- median daily primary Spearman >= +0.15;
- at least 58% of daily primary effects positive;
- at least eight eligible New York clock slots with positive full-period Spearman;
- at least 80 observations in every counted clock slot;
- first-half 2024 median daily effect positive;
- second-half 2024 median daily effect positive;
- median secondary future-range daily effect positive;
- one-sided sign-flip p <= 0.05.

These are exactly the thresholds used before the MGC 2023 and HistData 2023 results. They may not be weakened after 2024 inspection.

## Claims boundary

Even a full pass establishes only independent-source later-historical replication of the Gold volatility-persistence state.

It does not establish price direction, a trade entry, executable expectancy, profitability after costs, leverage suitability, prospective future OOS, or live readiness.

The rejected breakout continuation and failed-breakout reversal children remain rejected regardless of this result.
