# Gold Scheduled Macro Reaction v1

## Research question

After a scheduled U.S. macro release produces an initial Gold reaction, does price tend to continue or reverse, and do pre-existing trend/volatility states explain that behavior?

This lane is orthogonal to the closed Gold/Silver relative-value lineage. It does not rescue, condition, or retune any rejected Gold/Silver candidate.

## Evidence order

1. Freeze the scheduled event calendar, source, state definitions, controls, hypotheses, and statistical gates.
2. Score only the open 2021-2022 development period.
3. Do not score PnL at the state stage.
4. If and only if a state hypothesis passes the complete frozen gate, freeze a separate economic implementation before any economic result is viewed.
5. Freeze any executable candidate before opening 2023.
6. Treat 2023 as locked historical validation, not future OOS.
7. Require independent replication and later genuinely future shadow evidence before any leverage/live discussion.

## Official event calendar

The committed `EVENT_CALENDAR.csv` contains exactly 64 scheduled events from 2021-2022:

- 24 Consumer Price Index releases;
- 24 Employment Situation releases;
- 16 regular FOMC policy statements.

BLS annual release calendars are the source of the CPI and Employment Situation dates. BLS states that calendar times are Eastern Time; the frozen releases are at 08:30 Eastern.

Sources:

- https://www.bls.gov/schedule/2021/
- https://www.bls.gov/schedule/2022/

The Federal Reserve FOMC calendar is the source of the regular decision dates. Official FOMC statement pages identify the policy statements as released at 2:00 p.m. Eastern.

Sources:

- https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- https://www.federalreserve.gov/newsevents/pressreleases/monetary20210127a.htm
- https://www.federalreserve.gov/newsevents/pressreleases/monetary20220126a.htm

No 2023 event is present in the development calendar.

## Gold data source

Development Gold data are pinned to:

- repository: `simom1/XAUUSD-history`
- commit: `9b1f323866d0150ed2422c0e0cf1b97aa1bfcb22`
- file: `Gold-Cash/XAUUSD/XAUUSD_M1.csv`

The repository documents the bars as MetaTrader 5 exports and the timestamps as UTC. This removes the timestamp ambiguity found in the earlier Time To Eat XAU proxy.

The source remains cash XAUUSD, not exchange-traded GC futures. A favorable result would therefore still require independent source/instrument replication before promotion.

## Event clock

Let `t0` be the scheduled release time converted from `America/New_York` to UTC.

The source timestamp is treated as the one-minute bar open time.

For each event:

- pre-event price = close of bar opening at `t0 - 1 minute`;
- initial reaction end = close of bar opening at `t0 + 14 minutes`;
- the first 15 minutes therefore include bars opening `t0` through `t0 + 14m`;
- continuation horizons are 30, 60, and 120 minutes after the end of that initial 15-minute reaction;
- the primary statistical horizon is 60 minutes after the initial reaction.

Events with any required missing price bar are dropped. No interpolation is allowed.

## Pre-event scale

The scale is the high-low range across the 120 complete one-minute bars ending at `t0 - 1 minute`.

The event is unscorable if that range is below 0.01% of the pre-event price.

This scale is known before the event and normalizes different Gold volatility levels without using later information.

## Continuation state

Initial reaction:

`initial = initial_reaction_end_price - pre_event_price`

Continuation score at horizon `h`:

`sign(initial) * (future_close_h - initial_reaction_end_price) / pre_event_120m_range`

Interpretation:

- positive score: continuation in the direction of the initial macro shock;
- negative score: reversal after the initial shock.

A zero initial reaction is dropped from directional scoring.

## Matched placebo control

Every scheduled event receives up to two same-clock-time placebo observations:

- 7 calendar days before;
- 7 calendar days after.

A placebo date is excluded if any CPI, Employment Situation, or FOMC event in the frozen calendar occurs on that date. At least one valid placebo is required for an event-type base hypothesis.

The placebo uses exactly the same initial-reaction and continuation definitions.

Event excess continuation is:

`event continuation score - median(valid placebo continuation scores)`

This asks whether event-time continuation/reversal differs from ordinary behavior at the same local clock time and weekday vicinity.

## Pre-existing trend state

Pre-event four-hour return:

`close(t0-1m) / close(t0-241m) - 1`

Trend alignment is:

`sign(initial reaction) * sign(pre-event 4h return)`

Thus:

- `+1`: event shock points in the same direction as the pre-existing four-hour move;
- `-1`: event shock points against the pre-existing four-hour move.

The frozen state question is whether median continuation differs between aligned and opposed shocks.

## Pre-existing compression state

For each event, calculate the 120-minute pre-event range described above.

Normalize it by the median full-day high-low range of the prior 20 completed New York trading dates. The current event date is excluded.

The resulting continuous compression/expansion ratio is strictly pre-event.

The frozen state question is the Spearman relationship between this ratio and subsequent continuation score.

## Initial shock-size state

Shock size is:

`abs(initial reaction) / pre-event 120m range`

This is not pre-existing. It is an explicitly labeled reaction-state variable measured after the first 15 event minutes.

The frozen state question is the Spearman relationship between shock size and later continuation score.

## Six primary hypotheses

Only the 60-minute post-initial horizon enters the multiple-testing family:

1. CPI event excess continuation/reversal.
2. Employment Situation event excess continuation/reversal.
3. FOMC event excess continuation/reversal.
4. Four-hour trend-alignment effect.
5. Pre-event compression effect.
6. Initial shock-size effect.

Tests are two-sided because development is allowed to discover whether the effect is continuation or reversal. Any discovered sign must be frozen before later validation.

Benjamini-Hochberg FDR is applied across all six primary p-values. Required q-value is <= 0.10.

The 30-minute and 120-minute outcomes are robustness horizons only and cannot replace a failed primary test.

## Frozen statistical gates

### Event-type hypotheses

Each event-type candidate requires:

- at least 16 scorable events;
- valid matched placebo control for at least 80% of scheduled/scorable events;
- absolute median primary-horizon event excess >= 0.10 pre-event ranges;
- at least 60% of event excess observations with the discovered sign;
- same discovered sign at at least two of the three horizons;
- BH FDR q <= 0.10.

### Trend-alignment hypothesis

Requires:

- at least 15 aligned and 15 opposed events;
- absolute primary-horizon median difference >= 0.10 pre-event ranges;
- same effect sign at at least two horizons;
- primary effect sign agrees within at least two of CPI, Employment, FOMC when each subtype has at least eight scorable observations in both relevant groups;
- BH FDR q <= 0.10.

### Continuous feature hypotheses

Compression and shock-size hypotheses each require:

- at least 45 scorable events;
- absolute primary-horizon Spearman rho >= 0.25;
- same rho sign at at least two horizons;
- primary rho sign agrees within at least two of CPI, Employment, FOMC when the subtype has at least eight scorable events;
- BH FDR q <= 0.10.

Permutation inference uses 20,000 epochs. Event dates are the observation units.

## Controls

Every report must retain:

- matched placebo event-time controls;
- sign-reversed continuation scores;
- event-type decomposition;
- all predeclared hypotheses, including failures;
- complete trial-family FDR rather than reporting only the best cell.

## Prohibited at this stage

State v1 does not define or score:

- entries;
- stops;
- targets;
- partials;
- commission;
- spread/slippage;
- leverage;
- win rate;
- profit factor;
- PnL.

Engineering success is not edge evidence.

No economic study is authorized unless at least one state hypothesis passes every applicable frozen gate.
