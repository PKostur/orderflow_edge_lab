# Gold Scheduled Macro Reaction v1: pre-score source amendment

## Status

This is a data-implementation amendment only. It occurred before any development state hypothesis was scored.

The first workflow attempt used the pinned `simom1/XAUUSD-history` MT5 M1 file. That file downloaded successfully, but its current intraday coverage began in 2026, so the requested 2021-2022 development slice contained zero rows. The run stopped at materialization and produced no state result.

No event return, continuation score, placebo score, hypothesis statistic, p-value, q-value, or gate result was observed from that source.

## Replacement source

The development source is replaced with the pinned public dataset:

- repository: `kevingtlin/Market-Data-Lab`
- commit: `922f83a60cc574e7395fb27397077288055a1ef6`
- dataset ID: `XAUUSD-DUKASCOPY-M1-BID-ASK`
- provider: Dukascopy
- instrument: XAUUSD spot gold
- resolution: one minute
- timestamp unit: Unix epoch milliseconds
- timezone: UTC
- monthly coverage used: 2020-11 through 2022-12 only

The repository documentation states that bid and ask are stored separately with schema `timestamp,open,high,low,close` and that timestamps are UTC.

For state inference, corresponding bid and ask bars are inner-joined on timestamp and midpoint OHLC is calculated as `(bid + ask) / 2` for each OHLC field. This avoids selecting one executable side of the spread at a stage that explicitly does not model execution or PnL.

## What did not change

The following remain frozen exactly as before the failed materialization attempt:

- 64-event 2021-2022 calendar
- CPI, Employment Situation, and FOMC event families
- scheduled Eastern release clocks
- 15-minute initial reaction window
- 30, 60, and 120-minute continuation horizons
- 60-minute primary horizon
- 120-minute pre-event normalization range
- matched placebo offsets of minus 7 and plus 7 calendar days
- six primary hypotheses
- 20,000 permutation epochs
- two-sided inference
- Benjamini-Hochberg FDR across all six primary hypotheses
- every event-count, effect-size, consistency, robustness, and q-value gate
- economic scoring disabled
- 2023 locked and unopened

This amendment therefore does not use observed state evidence to improve the hypothesis family. Any later change after state results are observed must be versioned as a new research iteration rather than silently folded into v1.
