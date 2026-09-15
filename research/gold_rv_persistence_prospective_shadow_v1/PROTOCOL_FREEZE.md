# Gold RV Persistence — Prospective Shadow v1

## Purpose

Observe the exact surviving Gold intraday volatility-persistence state prospectively, beginning strictly after the protocol freeze.

The shadow begins at **2026-09-16 00:00 America/New_York** (`2026-09-16T04:00:00Z`). No anchor dated on or before 2026-09-15 New York time may enter prospective inference.

This is state-only monitoring. It does not trade and cannot authorize trading.

## Parent evidence

The candidate is `rv_persistence`:

`pre_rv_ratio -> future_rv_ratio`, frozen positive sign.

Before this prospective freeze it had:

- passed 2021–2022 development state gates;
- passed locked 2023 XAUUSD historical validation;
- shown strong but breadth-limited robustness on 2023 CME MGC / Databento;
- shown strong but breadth-limited robustness on 2023 HistData XAUUSD;
- passed every frozen gate on separately preregistered 2024 HistData XAUUSD later-historical replication.

The 2023 breadth failures remain failures. They are not pooled or retroactively upgraded.

## Prospective evidence boundary

Only observations whose anchor time is on or after `2026-09-16T04:00:00Z` may enter the prospective daily-effect sample.

Historical data from before the start may be downloaded only to construct the causal trailing 20-valid-observation same-clock baselines. It cannot contribute a prospective daily effect.

Every scoring run must use only fully completed New York dates. An incomplete current New York date is never scored. The acquisition client may return bars from the current partial day; the scorer hard-truncates inference at the current New York midnight recorded by the run's UTC as-of timestamp.

## Forward source

Provider: Dukascopy public datafeed.

Acquisition client: `dukascopy-node@1.50.0`.

Frozen acquisition arguments:

- instrument `xauusd`;
- timeframe `m1`;
- price type `bid`;
- UTC offset `0`;
- CSV output;
- no interpolation of missing source minutes.

The readiness run completed before the prospective start and verified the client output schema as:

`timestamp,open,high,low,close`

The raw `timestamp` is Unix milliseconds in UTC. This adapter clarification was completed before any post-start state observation existed and did not change the candidate, windows, baselines, inference family, or gates.

Warmup acquisition may begin at `2026-08-01T00:00:00Z`, but inference begins only at the prospective start.

Each run must record and preserve:

- acquisition client and exact version;
- requested/acquired UTC interval;
- raw downloaded CSV itself;
- raw file SHA256;
- raw byte size;
- scorer commit SHA;
- first and last source timestamps;
- first and last scored prospective anchors;
- result, daily-effect and anchor-effect files.

Every workflow run uses a run-specific artifact name. A later source snapshot must not overwrite an earlier run's evidence. If a later cumulative source download differs for overlapping historical rows, the prior artifact remains the record of what that earlier shadow run actually used.

## Frozen state definition

New York weekday anchors remain:

`00:00, 02:00, 04:00, 06:00, 08:00, 10:00, 12:00, 14:00, 16:00, 18:00, 20:00, 22:00`.

For every valid anchor:

1. require exact one-minute bars for the full prior 60 minutes and next 60 minutes;
2. calculate realized volatility as the square root of summed squared one-minute log close returns;
3. divide prior-hour RV by the median of the preceding 20 valid same-clock prior-hour RV observations;
4. divide next-hour RV by the median of the preceding 20 valid same-clock next-hour RV observations;
5. divide next-hour high-low range by the preceding 20 valid same-clock future-range observations for the secondary target;
6. drop an anchor if an exact required minute is missing.

No interpolation or imputation is allowed.

## Daily effect

A New York date enters inference only if it has at least eight valid frozen anchors.

Primary daily effect:

`Spearman(pre_rv_ratio, future_rv_ratio)`.

Secondary daily effect:

`Spearman(pre_rv_ratio, future_range_ratio)`.

Frozen candidate sign: positive.

## Statistical inference

Exactly one candidate is monitored.

The primary test is a one-sided positive 20,000-epoch sign-flip test over completed prospective daily primary effects.

There is no multiple-testing adjustment because no additional feature or candidate is admitted to this shadow.

## Informational checkpoints

Checkpoints at 20, 60 and 120 scorable prospective dates are descriptive only.

A checkpoint:

- cannot promote the candidate;
- cannot authorize economics;
- cannot authorize leverage;
- cannot authorize live trading;
- cannot be used to change any frozen parameter or gate.

There is no early-failure or early-success rule.

## Full prospective shadow gate

No full decision is made before 160 scorable prospective New York dates.

All conditions are required:

- at least 160 scorable prospective dates;
- median daily primary Spearman >= +0.15;
- at least 58% of daily primary effects positive;
- at least eight eligible clock slots with positive full-shadow Spearman;
- at least 80 prospective observations in every counted clock slot;
- median daily primary effect positive in the first chronological half of the shadow sample;
- median daily primary effect positive in the second chronological half;
- median secondary future-range daily effect positive;
- one-sided sign-flip p <= 0.05.

The numerical effect, breadth and significance thresholds are retained from the frozen historical replication gate. The previous calendar-half audit is expressed as first versus second chronological shadow halves only because this prospective window has no fixed calendar-year endpoint.

## Claims boundary

A future shadow pass would support a prospective claim about the **volatility-state relationship only**.

It would still not establish:

- future price direction;
- a trade entry or exit rule;
- executable expectancy after spread, slippage and fees;
- profitability;
- leverage suitability;
- live readiness.

The previously rejected high-volatility breakout continuation and failed-breakout reversal mechanisms remain rejected.

## Next stage after a full pass

If and only if the prospective state shadow later passes, any monetization mechanism must be specified and frozen separately before its results are observed. Economic development, locked economic validation, independent economic replication, leverage and live approval remain separate later gates.
