# Validation priority freeze - 2026-09-23

Status: **VALIDATION PHASE**

The development phase has produced enough hypotheses. Effective immediately, the project priority is prospective validation rather than additional post-hoc session slicing.

## Priority 1 - Evidence-v2 DON8 session forward watch

Watch: `evidence_v2_cross_strategy_session_forward_v1`

Primary strategy:

* family: Donchian breakout
* interval: 8h
* lookback: 55
* universe: frozen ten-symbol MEXC futures universe
* cost: 20 bps round trip
* primary session: 08:00-16:00 UTC
* control session: 00:00-08:00 UTC
* prospective start: 2026-09-23 00:00 UTC
* review: 30 calendar days
* no early pass/fail

Reason for priority:

The development audit spans 2024-01-01 through 2026-09-12, ten symbols and multiple years. DON8 08-16 was the cleanest session-state hypothesis: positive yearly EV in 2024, 2025 and 2026, positive majority of 120-day folds, positive symbol breadth, PF above 1, and evidence on both long and short sides.

No development return is counted prospectively.

## Priority 2 - W1/W2 ENA microstructure watches

W1: `SESSION_W1_ALIGNED_SHORT_ASIA_OPENING`

W2: `SESSION_W2_ALIGNED_BTC_SHORT_ASIA_OPENING`

Prospective boundary: 2026-09-22 15:39:58 UTC.

First eligible forward window: 2026-09-23 00:00-03:00 UTC.

Only two independent Continuous Order-Flow Discovery captures occurred inside that first eligible window. Both are valid prospective evidence, but the frozen review gate requires at least 10 new independent batches and 5 new calendar days.

Therefore W1/W2 remain `ACCUMULATING`. No early promotion or rejection is allowed from Day 1.

## Priority 3 - W3 CVD London/New-York state watch

Watch: `SESSION_W3_CVD_LNY_WIDE_RANGE_BTC_AGAINST`

Prospective boundary: 2026-09-22 18:10 UTC.

The first eligible London/New-York overlap after the freeze occurs on 2026-09-23.

Requirements:

* at least 20 new signals
* at least 8 new independent batches
* at least 7 new calendar days

W3 remains secondary because its development sample was only 14 observations across four batches and highly concentrated in one September 19 batch.

## Research stop rule

Until one of the three prospective watches reaches its predeclared review target:

* do not create additional session filters from the same inspected datasets;
* do not alter session boundaries;
* do not change costs, sides, symbols or strategy parameters;
* do not use leverage to rescue expectancy;
* do not promote based on an attractive partial-period endpoint.

Engineering fixes, data-integrity work and reporting improvements remain allowed if they do not change strategy definitions.

## Current decision

The project has moved from session discovery to **prospective validation**.

Primary research attention goes to DON8 because it has the broadest and most independent development basis. W1/W2 and W3 continue automatically as secondary independent watches.

No live or leverage authorization follows from this freeze.
