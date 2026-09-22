# Cross-market ETF v1: frozen July D0 result

Protocol sources:

* Freeze: `f3156a7460399d38f0dc3c7b6f5d7109858eb0d2`
* Arithmetic and timing clarification: `98b77ae7027efd9edc71aff78204abbda0855cd5`

No parameters, thresholds, ticker rules, execution timing, or family definitions were changed after observing July results.

## Data

Massive adjusted one-minute stock aggregates were reacquired for 2026-06-01 through 2026-07-31 only.

August was not fetched or inspected during this D0 run.

D0 is 2026-07-06 through 2026-07-31, 20 US regular sessions and 80 ticker-sessions across SPY, QQQ, GLD, and USO.

| Ticker | D0 sessions | Full 390-minute sessions | Incomplete sessions | Minimum minutes | Average minutes |
|---|---:|---:|---:|---:|---:|
| SPY | 20 | 20 | 0 | 390 | 390.00 |
| QQQ | 20 | 20 | 0 | 390 | 390.00 |
| GLD | 20 | 20 | 0 | 390 | 390.00 |
| USO | 20 | 15 | 5 | 372 | 388.75 |

No missing minute was interpolated, forward-filled, substituted, or repaired.

## ETF_H1_ORB15_CONTINUATION

Eligibility:

* 80 total ticker-sessions.
* 80 had all 09:30 through 09:44 opening-range minutes.
* 76 produced a frozen-rule breakout.
* 76 had the required exact entry and exact exit and therefore became executable observations.

D0 metrics at frozen 2 bps round-trip friction:

* 76 signals across 20 dates and 4 tickers.
* Pooled net mean: +1.265032 bps/signal.
* Reversed control: -5.265032 bps/signal.
* Positive tickers: 4.
* Positive-PnL concentration: 0.566297.
* First calendar half: -5.159065 bps/signal.
* Second calendar half: +7.689130 bps/signal.

Ticker results:

| Ticker | Signals | Mean net bps | Total net bps |
|---|---:|---:|---:|
| GLD | 18 | +3.721047 | +66.978851 |
| QQQ | 19 | +4.809615 | +91.382684 |
| SPY | 19 | +0.158272 | +3.007174 |
| USO | 20 | -3.261313 | -65.226263 |

Gate result:

| D0 gate | Result |
|---|---|
| >= 30 total signals | PASS |
| >= 10 sessions with signals | PASS |
| >= 3 tickers with signals | PASS |
| pooled net mean > 0 | PASS |
| original beats reversed | PASS |
| >= 3 positive tickers | PASS |
| max positive-PnL share <= 0.60 | PASS |
| both frozen calendar halves positive | **FAIL** |

Status: `FALSIFIED_D0`.

The family ID is terminal under the frozen protocol. August must not be inspected for this family.

## ETF_H2_VWAP_VOL_REVERSION

Eligibility:

* 80 total ticker-sessions.
* 80 had at least one mathematically valid frozen H2 evaluation point with all required exact minutes.
* 75 crossed the frozen z threshold.
* 75 had the required exact entry and exact exit and therefore became executable observations.

D0 metrics at frozen 2 bps round-trip friction:

* 75 signals across 20 dates and 4 tickers.
* Pooled net mean: +1.836739 bps/signal.
* Reversed control: -5.836739 bps/signal.
* Positive tickers: 2.
* Positive-PnL concentration: 0.918878.
* First calendar half: +0.729645 bps/signal.
* Second calendar half: +2.805445 bps/signal.

Ticker results:

| Ticker | Signals | Mean net bps | Total net bps |
|---|---:|---:|---:|
| GLD | 18 | -1.376429 | -24.775715 |
| QQQ | 19 | +0.857277 | +16.288261 |
| SPY | 19 | -2.013530 | -38.257067 |
| USO | 19 | +9.710522 | +184.499911 |

Gate result:

| D0 gate | Result |
|---|---|
| >= 30 total signals | PASS |
| >= 10 sessions with signals | PASS |
| >= 3 tickers with signals | PASS |
| pooled net mean > 0 | PASS |
| original beats reversed | PASS |
| >= 3 positive tickers | **FAIL** |
| max positive-PnL share <= 0.60 | **FAIL** |
| both frozen calendar halves positive | PASS |

Status: `FALSIFIED_D0`.

The pooled positive result is too narrow under the frozen breadth and concentration gates. The family ID is terminal. August must not be inspected for this family.

## ETF_H3_GAP_REVERSION

Eligibility:

* 80 total ticker-sessions.
* 80 had valid frozen prior-return sigma plus exact 09:30, 09:31, and 10:30 inputs.
* 42 crossed the frozen gap threshold.
* 42 became executable observations.

D0 metrics at frozen 2 bps round-trip friction:

* 42 signals across 16 dates and 4 tickers.
* Pooled net mean: -16.391733 bps/signal.
* Reversed control: +12.391733 bps/signal.
* Positive tickers: 2.
* Positive-PnL concentration: 0.885284.
* First calendar half: -28.011860 bps/signal.
* Second calendar half: -8.490046 bps/signal.

Ticker results:

| Ticker | Signals | Mean net bps | Total net bps |
|---|---:|---:|---:|
| GLD | 11 | -28.108490 | -309.193387 |
| QQQ | 12 | +1.731319 | +20.775829 |
| SPY | 8 | +20.041308 | +160.330466 |
| USO | 11 | -50.942334 | -560.365675 |

Gate result:

| D0 gate | Result |
|---|---|
| >= 30 total signals | PASS |
| >= 10 sessions with signals | PASS |
| >= 3 tickers with signals | PASS |
| pooled net mean > 0 | **FAIL** |
| original beats reversed | **FAIL** |
| >= 3 positive tickers | **FAIL** |
| max positive-PnL share <= 0.60 | **FAIL** |
| both frozen calendar halves positive | **FAIL** |

Status: `FALSIFIED_D0`.

The reversed control strongly dominates the frozen original direction. Under the research doctrine this does not authorize adopting the reversed strategy post hoc.

## Decision

All three frozen ETF family IDs fail at least one D0 survival gate.

Therefore:

* August 2026 remains `LOCKED_NOT_INSPECTED`.
* No D3 historical holdout evaluation is permitted for these IDs.
* No parameter rescue, ticker-specific tuning, reversed-control adoption, leverage, or live testing is permitted.
* Any future ETF investigation must begin with a new pre-PnL hypothesis and a new frozen candidate or family ID.
