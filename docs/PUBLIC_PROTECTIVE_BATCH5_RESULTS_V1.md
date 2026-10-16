# Public protective bot batch5 results

Two new source adaptations were registered and their evaluator committed before inspecting outcomes. Historical screening remains spent development evidence. No candidate is viable without a separate untouched future confirmation pass.

Design: `d586630a0ec845c5977976340d000f24a894b4af`. Evaluator: `68e5664065e419c95f829b972aea7dc62ac58e64`.

## Data and mechanics

Retained Binance Spot BTCUSDT, ETHUSDT, SOLUSDT and LINKUSDT minute archives, 2023-04-01 through 2026-09-30 inclusive. Each has 1,841,760 minutes and 3,837 aligned eight-hour candles. First entry eligibility: 2023-06-20 00:00 UTC after 240 closed candles. The longest shared complete segment was selected by the prior quality inventory before PnL; it does not cover the 2022 bear market or repair old readiness failures.

Fixed source rules and declared Spot adaptations are in `PUBLIC_PROTECTIVE_BATCH5_DESIGN_V1.md`. Minute touch references are hypothetical. Whole-history gap models and both-touch branches are retained. Pending positions are cutoff marks, not fictitious completed trades. Fees/friction are assumed 20/40/60/80 round-trip bps charged on actual notional. Drawdown is sampled at eight-hour closes, not an intraminute bound.

## Results

| Candidate | Completed / pending | Mean net40 bps | Mean net80 bps | Unit PF40 | Portfolio ROI40 | Drawdown40 | Placebo tail | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| MAGenSpot8hNativeKernel | 353 / 1 | -12.210274 | -52.082008 | 0.973974 | -10.378050% | -46.548521% | 0.670000 | REJECTED_AS_ADAPTED |
| IchimokuSpot8hATR | 248 / 3 | 126.619273 | 86.193324 | 1.381401 | 176.374635% | -46.000880% | 0.170000 | REJECTED_AS_ADAPTED |

Table uses the first conservative-limit full history. Complete branch/gap/cost metrics, events, account paths and funded BTC bounds are retained losslessly in `results.json.gz`; survival requires every supported baseline history. `result_index.json` binds compressed and decompressed bytes; `result_summary.json` is the readable GitHub summary.

### MAGenSpot8hNativeKernel

Failed gates: all_symbols_positive, excess_descriptive_ci, leave_week_positive, net40_mean, net80_positive, net_descriptive_ci, placebo_tail, portfolio_drawdown, positive_year_fraction.

Observed entry weeks: 141; calendar weeks including zeros: 172. Net and conservative BTC-excess descriptive 97.5% intervals: `{'net_bps': [-192.6939155246919, 147.32220918248558], 'excess_lower_bps': [-161.15190075720116, 51.6174548016888]}`. Worst leave-entry-week mean: -28.188511 bps. Positive years: 50.00%, all four years retained in the denominator.

Funded BTC ROI reference bounds: 3.506488% to 20.739981%.

| Seven-bar lag model | Completed / pending | Mean net40 bps | Unit PF40 |
|---|---:|---:|---:|
| conservative_limit | 328 / 1 | 33.651916 | 1.077380 |
| opening_price_improvement | 328 / 1 | 33.651916 | 1.077380 |

| Symbol | Admitted / completed / pending | Net40 mean bps | Accepted-entry accounting |
|---|---:|---:|---|
| ETHUSDT | 111 / 111 / 0 | -60.161089 | `{'raw_entry_flags': 235, 'accepted_entries': 111, 'held_entry_ignored': 122, 'cash_rejected': 1, 'unexecuted_final_entry': 1}` |
| SOLUSDT | 120 / 119 / 1 | 55.717302 | `{'raw_entry_flags': 234, 'accepted_entries': 120, 'held_entry_ignored': 114}` |
| LINKUSDT | 123 / 123 / 0 | -35.208392 | `{'raw_entry_flags': 249, 'accepted_entries': 123, 'held_entry_ignored': 126}` |

Supported joint histories by case: `{'20:conservative_limit': 1, '20:opening_price_improvement': 1, '40:conservative_limit': 1, '40:opening_price_improvement': 1, '60:conservative_limit': 1, '60:opening_price_improvement': 1, '80:conservative_limit': 1, '80:opening_price_improvement': 1}`.

### IchimokuSpot8hATR

Failed gates: excess_descriptive_ci, net_descriptive_ci, placebo_tail, portfolio_drawdown.

Observed entry weeks: 96; calendar weeks including zeros: 172. Net and conservative BTC-excess descriptive 97.5% intervals: `{'net_bps': [-93.30021240319056, 317.59719805059], 'excess_lower_bps': [-64.31645400757203, 206.8756323180167]}`. Worst leave-entry-week mean: 98.042187 bps. Positive years: 75.00%, all four years retained in the denominator.

Funded BTC ROI reference bounds: 9.798129% to 32.858219%.

| Seven-bar lag model | Completed / pending | Mean net40 bps | Unit PF40 |
|---|---:|---:|---:|
| conservative_limit | 318 / 3 | 31.692762 | 1.118489 |
| opening_price_improvement | 318 / 3 | 31.700686 | 1.118518 |

| Symbol | Admitted / completed / pending | Net40 mean bps | Accepted-entry accounting |
|---|---:|---:|---|
| ETHUSDT | 83 / 82 / 1 | 29.162863 | `{'raw_entry_flags': 1157, 'accepted_entries': 83, 'held_entry_ignored': 1037, 'bracket_replacements': 1037, 'cash_rejected': 37}` |
| SOLUSDT | 80 / 79 / 1 | 284.074355 | `{'raw_entry_flags': 1217, 'accepted_entries': 80, 'held_entry_ignored': 1111, 'bracket_replacements': 1111, 'cash_rejected': 26}` |
| LINKUSDT | 88 / 87 / 1 | 75.397403 | `{'raw_entry_flags': 1156, 'accepted_entries': 88, 'held_entry_ignored': 1027, 'bracket_replacements': 1026, 'cash_rejected': 41}` |

Supported joint histories by case: `{'20:conservative_limit': 1, '20:opening_price_improvement': 1, '40:conservative_limit': 1, '40:opening_price_improvement': 1, '60:conservative_limit': 1, '60:opening_price_improvement': 1, '80:conservative_limit': 1, '80:opening_price_improvement': 1}`.

## Controls, verification and next step

Each candidate receives 500 fixed-seed randomized-entry controls preserving raw flag counts within eligible calendar weeks. Controls recompute their own source exits, ATR brackets, sizing and holding periods; they never reuse observed durations. The seven-bar causal lag excludes pre-warmup flags. Moving four-calendar-week bootstrap draws include empty weeks. All estimates and placebo tails are descriptive; they are not adjusted for the entire cumulative search.

The mandatory suite passed 1,004 tests, including 14 new simulator tests. Ruff passed. Both sources passed 24 exact synthetic prefix checks with the pinned native wheel. Read-only adversarial review resolved the implementation findings before outcomes. Release CI and deterministic specialist review evidence are reported separately after publication.

Minimum cumulative attempted trading cells: 17; signal/model cells: 18. Keep the broader source, forecasting and feasibility history separately disclosed. Related costs, gap models and controls are not independent new experiments.

Frozen definitions, prior rejected outcomes, DON8, EMA8, VOL8, DV2, D4, payoff geometry, session watches and prospective protocols remain unchanged; their hashes are in verification.json. Bollinger is excluded and no order client is added.

An eventual historical survivor requires a separately registered and adequately powered future-only study with calibrated costs and approval-bound paper reliability, frozen before new observations begin. Historical re-screening cannot satisfy the requested endpoint. Rejected versions remain closed; any subsequent strategy requires new source/default and trial registration before outcomes.

## Rerun

On the exact registered Windows Python 3.13.14 / NumPy 2.2.4 runtime, retain the pinned jesse-rust 1.3.0 wheel and extracted runtime, and run from the repository root with `PYTHONPATH=src`. The program verifies committed evaluator source, frozen configuration, raw/checksum/receipt hashes and minute alignment; use a fresh output filename for each attempt.

```powershell
$env:PYTHONPATH='src'
python -m orderflow_edge_lab.public_protective_batch5 --raw ../../outputs/Minute-continuous-source-data --cache ../protective_batch5_cache --native-runtime ../magen_native_runtime --native-wheel ../magen_native_wheels/jesse_rust-1.3.0-cp313-cp313-win_amd64.whl --output ../protective_batch5_replication.json
```
