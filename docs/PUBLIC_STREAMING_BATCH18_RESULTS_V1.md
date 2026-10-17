# Public streaming reversal batch18 results

Historical hypothetical development screen; no viable candidate, untouched-future pass or exchange orders.

Baseline `de9ea155060eeb9390c118dce61f301e5cde6a6a`; design `10340a52195b2f6b46169d5b668b5c2345daf572`; execution `ef19474515a79c949294f026d5a38f5414b492f8`; exact evaluator `c88ca0b8ac93c73cec3adea572378e8d999ad9fac974f8b3108eff56219066db`.

## Source and execution scope

Two separate fixed public source adaptations. Quickstart06: two strict falling closes, quantity1, actual filled OPEN E → closeE+5 decision → OPEN E+6 exit. UpDown40:40bar return <-1% enters, >=+1% exits, quantity10; source strength unused, flat shorts explicitly refused. No direction/size/pair/date/cost/gate rescue.

Original default-preloaded startup failures retained. Explicit streaming/cash-origin adaptation uses closed feature239 after240bars, earliest OPEN240, no startup positions. Original cash100000 and source friction unset/0.1% differ from research10000cash sleeves and nominal20/40/60/80bps.

Literal two-stage created-close and nextOPEN funding, separate float64 debit/credit operations; no tolerance/clamp/resize. Any negative/nonfinite BTC debit aborts the complete evaluation. Own BTC cash/notional-fraction/fees/NAV is a reference benchmark, not a native executable hedge. Atomic full nextOPEN only; partial/delayed/asynchronous/externalRejected/exchange lot/depth cases unmodeled failclosed. GPL source/framework/native harness outside Git; own equations, URI/hash and numeric receipts only.

## Data and evidence

Binance Spot2023-04-01 through2026-09-30,1,841,760minutes/3837eight-hourbars each for BTCbenchmark/ETH/SOL/LINK. Firsteligible2023-06-20T00Z. Quality-only common continuous segment, no repairs or2022bear. Spent development data, not OOS. Three10000USDT sleeves per candidate; candidates are not pooled. Eight-hour-close DD is not an intrabar bound.

## Quickstart06TwoDown8hOneUnitLongCash

[Pinned source](https://github.com/backtrader/backtrader-docs/blob/e20cea18b88e1693b65e408f8778cc076ab21a67/docs/quickstart/quickstart06.py). **REJECTED_AS_ADAPTED**.

Failed gates: all_symbols_positive, excess_descriptive_ci, leave_week_positive, net40_mean, net80_positive, net_descriptive_ci, positive_year_fraction.

### Baseline returns and funded wealth

- admitted: `964`
- completed: `963`
- censored_mtm: `1`
- mean_net_bps: `-11.729226628360461`
- median_net_bps: `-33.637358753979555`
- mean_completed_only_net_bps: `-11.745509011842113`
- per_unit_profit_factor: `0.9426762856289774`
- cash_profit_factor_with_cutoff_marks: `0.7643174714275711`
- completed_cash_profit_factor: `0.7643171506277248`
- win_fraction: `0.46887966804979253`
- mean_gross_bps: `28.303922763910684`
- mean_btc_excess_lower_bps: `5.418850072160457`
- mean_btc_excess_upper_bps: `5.418850072160457`
- mean_mfe_lower_bps: `437.65581948599083`
- mean_mfe_upper_bps: `437.65581948599083`
- mean_mae_lower_bps: `-449.5860114851992`
- mean_mae_upper_bps: `-449.5860114851992`

- roi_pct: `-13.865701533333363`
- drawdown_pct: `-15.775193256245522`
- funded_btc_roi_lower_pct: `-8.489625644094723`
- funded_btc_roi_upper_pct: `-8.489625644094723`
- note: `8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.`

### Cost stress

- 20:conservative_limit: mean net `8.267351489658225`bps; PF `1.042488081717384`; ROI `-7.984930766666654`%; DD `-10.566836768692012`%.
- 20:opening_price_improvement: mean net `8.267351489658225`bps; PF `1.042488081717384`; ROI `-7.984930766666654`%; DD `-10.566836768692012`%.
- 40:conservative_limit: mean net `-11.729226628360461`bps; PF `0.9426762856289774`; ROI `-13.865701533333363`%; DD `-15.775193256245522`%.
- 40:opening_price_improvement: mean net `-11.729226628360461`bps; PF `0.9426762856289774`; ROI `-13.865701533333363`%; DD `-15.775193256245522`%.
- 60:conservative_limit: mean net `-31.68593121074774`bps; PF `0.8526332366878933`; ROI `-19.746472299999994`%; DD `-21.135991312153514`%.
- 60:opening_price_improvement: mean net `-31.68593121074774`bps; PF `0.8526332366878933`; ROI `-19.746472299999994`%; DD `-21.135991312153514`%.
- 80:conservative_limit: mean net `-51.6028814015389`bps; PF `0.7713900030271009`; ROI `-25.627243066666704`%; DD `-26.568867993248226`%.
- 80:opening_price_improvement: mean net `-51.6028814015389`bps; PF `0.7713900030271009`; ROI `-25.627243066666704`%; DD `-26.568867993248226`%.

### Dependence and controls

```json
{
  "descriptive_only": true,
  "replicates": 2000,
  "moving_calendar_block_weeks": 4,
  "alpha_per_candidate": 0.025,
  "two_sided_interval_coverage": 0.975,
  "quantiles": [
    0.0125,
    0.9875
  ],
  "defined_ratio_replicates": 2000,
  "intervals": {
    "net_bps": [
      -66.17687556273647,
      40.35081175684766
    ],
    "excess_lower_bps": [
      -30.690143342959864,
      39.67121297096335
    ]
  },
  "alpha_policy": "Two conditional fixed candidates alpha0.025 each; descriptive, no global search correction",
  "new_registered_cells": 2
}
```

500within-entryweek whole qualifier replacements; original exits, own source funding/units/admission/duration. Quick controls use own actualE+6 clock. Tail `0.002`. All500means retained. Sevenbarlag owncash/clocks retained.

Entry weeks `172`; positive entry-year fraction `0.25`; worst leave-week mean `-18.95785754092356`bps.

```json
{
  "conservative_limit": [
    {
      "admitted": 963,
      "completed": 961,
      "censored_mtm": 2,
      "mean_net_bps": -25.629371353002437,
      "median_net_bps": -46.10841904196472,
      "mean_completed_only_net_bps": -25.68844515158577,
      "per_unit_profit_factor": 0.8827235824796017,
      "cash_profit_factor_with_cutoff_marks": 0.7363187846717145,
      "completed_cash_profit_factor": 0.7362959986153245,
      "win_fraction": 0.46002076843198336,
      "mean_gross_bps": 14.348066036364324,
      "mean_btc_excess_lower_bps": 0.7102876506036206,
      "mean_btc_excess_upper_bps": 0.7102876506036206,
      "mean_mfe_lower_bps": 422.4653779858818,
      "mean_mfe_upper_bps": 422.4653779858818,
      "mean_mae_lower_bps": -444.99563573353583,
      "mean_mae_upper_bps": -444.99563573353583
    }
  ],
  "opening_price_improvement": [
    {
      "admitted": 963,
      "completed": 961,
      "censored_mtm": 2,
      "mean_net_bps": -25.629371353002437,
      "median_net_bps": -46.10841904196472,
      "mean_completed_only_net_bps": -25.68844515158577,
      "per_unit_profit_factor": 0.8827235824796017,
      "cash_profit_factor_with_cutoff_marks": 0.7363187846717145,
      "completed_cash_profit_factor": 0.7362959986153245,
      "win_fraction": 0.46002076843198336,
      "mean_gross_bps": 14.348066036364324,
      "mean_btc_excess_lower_bps": 0.7102876506036206,
      "mean_btc_excess_upper_bps": 0.7102876506036206,
      "mean_mfe_lower_bps": 422.4653779858818,
      "mean_mfe_upper_bps": 422.4653779858818,
      "mean_mae_lower_bps": -444.99563573353583,
      "mean_mae_upper_bps": -444.99563573353583
    }
  ]
}
```

### Per-symbol baseline

| Symbol | Admitted | Completed | Cutoff | Mean net40 bps | Per-unit PF | Funding/order counts |
|---|---:|---:|---:|---:|---:|---|
| ETHUSDT | 319 | 319 | 0 | -30.14917971254616 | 0.8372596284462349 | {'raw_entry_flags': 818, 'created_entry_orders': 319, 'accepted_entries': 319, 'held_entry_ignored': 499, 'created_exit_orders': 319, 'filled_exits': 319} |
| SOLUSDT | 319 | 319 | 0 | -7.450053692964648 | 0.9648184126330346 | {'raw_entry_flags': 845, 'created_entry_orders': 319, 'accepted_entries': 319, 'created_exit_orders': 319, 'filled_exits': 319, 'held_entry_ignored': 526} |
| LINKUSDT | 326 | 325 | 1 | 2.107917136866457 | 1.0097336380731021 | {'raw_entry_flags': 858, 'created_entry_orders': 326, 'accepted_entries': 326, 'created_exit_orders': 325, 'filled_exits': 325, 'held_entry_ignored': 532} |

## UpDown40Return8hTenUnitLongCash

[Pinned source](https://github.com/cloudQuant/backtrader/blob/b418caf7364e1134983a4c4b394768686e1916aa/tests/strategies/test_85_up_down_candles_strategy.py). **REJECTED_AS_ADAPTED**.

Failed gates: all_symbols_positive, excess_descriptive_ci, leave_week_positive, net40_mean, net80_positive, net_descriptive_ci, positive_year_fraction.

### Baseline returns and funded wealth

- admitted: `167`
- completed: `167`
- censored_mtm: `0`
- mean_net_bps: `1.7897100857796457`
- median_net_bps: `167.34161734334617`
- mean_completed_only_net_bps: `1.7897100857796457`
- per_unit_profit_factor: `1.0061596827909896`
- cash_profit_factor_with_cutoff_marks: `0.8224442993619668`
- completed_cash_profit_factor: `0.8224442993619668`
- win_fraction: `0.6407185628742516`
- mean_gross_bps: `41.877043593137564`
- mean_btc_excess_lower_bps: `-38.134789910282336`
- mean_btc_excess_upper_bps: `-38.134789910282336`
- mean_mfe_lower_bps: `516.216960192263`
- mean_mfe_upper_bps: `516.216960192263`
- mean_mae_lower_bps: `-801.3150563210813`
- mean_mae_upper_bps: `-801.3150563210813`

- roi_pct: `-2.5926979333333433`
- drawdown_pct: `-5.652170229232178`
- funded_btc_roi_lower_pct: `-0.7193896332238325`
- funded_btc_roi_upper_pct: `-0.7193896332238325`
- note: `8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.`

### Cost stress

- 20:conservative_limit: mean net `21.813353196349095`bps; PF `1.076783160731677`; ROI `-1.840565633333302`%; DD `-5.254567929054376`%.
- 20:opening_price_improvement: mean net `21.813353196349095`bps; PF `1.076783160731677`; ROI `-1.840565633333302`%; DD `-5.254567929054376`%.
- 40:conservative_limit: mean net `1.7897100857796457`bps; PF `1.0061596827909896`; ROI `-2.5926979333333433`%; DD `-5.652170229232178`%.
- 40:opening_price_improvement: mean net `1.7897100857796457`bps; PF `1.0061596827909896`; ROI `-2.5926979333333433`%; DD `-5.652170229232178`%.
- 60:conservative_limit: mean net `-18.19400552107763`bps; PF `0.9388152683642847`; ROI `-3.3448302333332847`%; DD `-6.0523446462595665`%.
- 60:opening_price_improvement: mean net `-18.19400552107763`bps; PF `0.9388152683642847`; ROI `-3.3448302333332847`%; DD `-6.0523446462595665`%.
- 80:conservative_limit: mean net `-38.137912929517015`bps; PF `0.8748008960041705`; ROI `-4.096962533333304`%; DD `-6.455116219932144`%.
- 80:opening_price_improvement: mean net `-38.137912929517015`bps; PF `0.8748008960041705`; ROI `-4.096962533333304`%; DD `-6.455116219932144`%.

### Dependence and controls

```json
{
  "descriptive_only": true,
  "replicates": 2000,
  "moving_calendar_block_weeks": 4,
  "alpha_per_candidate": 0.025,
  "two_sided_interval_coverage": 0.975,
  "quantiles": [
    0.0125,
    0.9875
  ],
  "defined_ratio_replicates": 2000,
  "intervals": {
    "net_bps": [
      -228.12553707191165,
      178.26592098719436
    ],
    "excess_lower_bps": [
      -145.08476484438444,
      63.6124156519699
    ]
  },
  "alpha_policy": "Two conditional fixed candidates alpha0.025 each; descriptive, no global search correction",
  "new_registered_cells": 2
}
```

500within-entryweek whole qualifier replacements; original exits, own source funding/units/admission/duration. Quick controls use own actualE+6 clock. Tail `0.0`. All500means retained. Sevenbarlag owncash/clocks retained.

Entry weeks `89`; positive entry-year fraction `0.5`; worst leave-week mean `-15.89184001619352`bps.

```json
{
  "conservative_limit": [
    {
      "admitted": 348,
      "completed": 348,
      "censored_mtm": 0,
      "mean_net_bps": 3.6308625215257515,
      "median_net_bps": 19.398695248075136,
      "mean_completed_only_net_bps": 3.6308625215257515,
      "per_unit_profit_factor": 1.0213030273709875,
      "cash_profit_factor_with_cutoff_marks": 0.9538832508324098,
      "completed_cash_profit_factor": 0.9538832508324098,
      "win_fraction": 0.5316091954022989,
      "mean_gross_bps": 43.725575397363535,
      "mean_btc_excess_lower_bps": 11.01505493323892,
      "mean_btc_excess_upper_bps": 11.01505493323892,
      "mean_mfe_lower_bps": 346.742982836026,
      "mean_mfe_upper_bps": 346.742982836026,
      "mean_mae_lower_bps": -404.7564134539629,
      "mean_mae_upper_bps": -404.7564134539629
    }
  ],
  "opening_price_improvement": [
    {
      "admitted": 348,
      "completed": 348,
      "censored_mtm": 0,
      "mean_net_bps": 3.6308625215257515,
      "median_net_bps": 19.398695248075136,
      "mean_completed_only_net_bps": 3.6308625215257515,
      "per_unit_profit_factor": 1.0213030273709875,
      "cash_profit_factor_with_cutoff_marks": 0.9538832508324098,
      "completed_cash_profit_factor": 0.9538832508324098,
      "win_fraction": 0.5316091954022989,
      "mean_gross_bps": 43.725575397363535,
      "mean_btc_excess_lower_bps": 11.01505493323892,
      "mean_btc_excess_upper_bps": 11.01505493323892,
      "mean_mfe_lower_bps": 346.742982836026,
      "mean_mfe_upper_bps": 346.742982836026,
      "mean_mae_lower_bps": -404.7564134539629,
      "mean_mae_upper_bps": -404.7564134539629
    }
  ]
}
```

### Per-symbol baseline

| Symbol | Admitted | Completed | Cutoff | Mean net40 bps | Per-unit PF | Funding/order counts |
|---|---:|---:|---:|---:|---:|---|
| ETHUSDT | 0 | 0 | 0 | None | None | {'raw_entry_flags': 1617, 'created_entry_orders': 1617, 'submission_margin': 1617, 'upstream_flat_short_refused': 1641} |
| SOLUSDT | 80 | 80 | 0 | 7.802804418975279 | 1.024893064402544 | {'raw_entry_flags': 1591, 'created_entry_orders': 80, 'accepted_entries': 80, 'held_entry_ignored': 1511, 'created_exit_orders': 80, 'filled_exits': 80, 'upstream_flat_short_refused': 1723} |
| LINKUSDT | 87 | 87 | 0 | -3.739572059687603 | 0.9861237412877146 | {'raw_entry_flags': 1671, 'created_entry_orders': 87, 'accepted_entries': 87, 'held_entry_ignored': 1584, 'created_exit_orders': 87, 'filled_exits': 87, 'upstream_flat_short_refused': 1623} |

## Verification and next step

1226repository tests PASS;17newtests (15draft mechanics plus2registration/CLI checks),14descriptive tests retained; RuffPASS. Independent actual pre-outcome approval committed before firstrawload, final reproduction/accounting/diagnostic/controlmean/gate review retained.14frozen/370prior paths exact. Full results lossless; all group/session/clock/leave-out diagnostics retained.

Fixed descriptivealpha.025 per candidate with2000moving4calendarweekblocks including zero-event weeks is not a global repeated-search correction. No pooling/ranking or publisher performance validation. Cutoff marks are not completed trades; raw extrema are not fills. No frozen session watches or prospective protocols changed. Bollinger excluded.

Rejected versions stay closed. A historical survivor only permits a separate immutable adequately powered future-only protocol, calibrated costs/quotes/execution/control and approval-bound paper reliability. User viability criterion remains unmet until its untouched-future pass. Publication checks pending.

## Additional descriptive paths and outcomes

The method was frozen before batch18 outcomes. All admissions and completed-only populations remain separate for each candidate. Retrospective maxima are not executable fills; 10/30bps reference curves are conditional arithmetic on unchanged40bps admissions, not funded resimulations, new trials or gates. First-maximum minute LOW ordering remains bounded. UTC clocks are fixed windows, not DST/session filters; matched-event beta is descriptive, not causal alpha.

### Quickstart06TwoDown8hOneUnitLongCash

#### all admissions

n=964; completed=963; median MFE bounds=[307.5810278367719, 307.5810278367719]bps; median MAE bounds=[-336.69953201593046, -336.69953201593046]bps.

Best per-unit net trade: `{'symbol': 'SOLUSDT', 'entry_time': '2023-07-12T08:00:00Z', 'status': 'COMPLETED', 'net_bps': 2986.098647391864, 'gross_bps': 3038.1471389645776, 'net_cash_profit_or_cutoff_mark': 6.588539999998829}`. Worst: `{'symbol': 'SOLUSDT', 'entry_time': '2026-02-04T00:00:00Z', 'status': 'COMPLETED', 'net_bps': -2029.087192863227, 'gross_bps': -1997.1396465420366, 'net_cash_profit_or_cutoff_mark': -19.902459999999337}`.

Correct-direction fraction=0.5062240663900415; positive active-entry-week fraction=0.436046511627907; positive calendar-week fraction including zeros=0.436046511627907.

Path means/medians: `{'pre_first_mfe_mae_bps_bounds': {'mean': [-177.65554407175114, -177.5471126846579], 'median': [-118.46003256990367, -118.46003256990367]}, 'mae_through_endpoint_bps_bounds': {'mean': [-449.5860114851992, -449.5860114851992], 'median': [-336.69953201593046, -336.69953201593046]}, 'hypothetical_peak_net_after_cost_bps_bounds': {'mean': [395.98853078544795, 395.98853078544795], 'median': [266.43299978153624, 266.43299978153624]}, 'mfe_giveback_to_endpoint_bps_bounds': {'mean': [409.3518967220802, 409.3518967220802], 'median': [324.07793258807, 324.07793258807]}}`.

Hypothetical peak after baseline cost clears zero fraction bounds: `[0.9398340248962656, 0.9398340248962656]`.

#### completed only

n=963; completed=963; median MFE bounds=[307.55902100931377, 307.55902100931377]bps; median MAE bounds=[-336.86060249339954, -336.86060249339954]bps.

Best per-unit net trade: `{'symbol': 'SOLUSDT', 'entry_time': '2023-07-12T08:00:00Z', 'status': 'COMPLETED', 'net_bps': 2986.098647391864, 'gross_bps': 3038.1471389645776, 'net_cash_profit_or_cutoff_mark': 6.588539999998829}`. Worst: `{'symbol': 'SOLUSDT', 'entry_time': '2026-02-04T00:00:00Z', 'status': 'COMPLETED', 'net_bps': -2029.087192863227, 'gross_bps': -1997.1396465420366, 'net_cash_profit_or_cutoff_mark': -19.902459999999337}`.

Correct-direction fraction=0.505711318795431; positive active-entry-week fraction=0.436046511627907; positive calendar-week fraction including zeros=0.436046511627907.

Path means/medians: `{'pre_first_mfe_mae_bps_bounds': {'mean': [-177.75943757896678, -177.65089359437914], 'median': [-118.49901250822859, -118.49901250822859]}, 'mae_through_endpoint_bps_bounds': {'mean': [-449.86991511711, -449.86991511711], 'median': [-336.86060249339954, -336.86060249339954]}, 'hypothetical_peak_net_after_cost_bps_bounds': {'mean': [396.07167429819765, 396.07167429819765], 'median': [266.4110808056841, 266.4110808056841]}, 'mfe_giveback_to_endpoint_bps_bounds': {'mean': [409.45172111889764, 409.45172111889764], 'median': [325.13181019332205, 325.13181019332205]}}`.

Hypothetical peak after baseline cost clears zero fraction bounds: `[0.9397715472481828, 0.9397715472481828]`.

Raw completed-candle BUY availability counts (includes held/rejected/final-unexecuted): {'ETHUSDT': 818, 'SOLUSDT': 845, 'LINKUSDT': 858}

Full concentration shares/HHI by symbol/month/week, matched-event BTC beta endpoint scenarios, conditional cost curves, raw/entry session overlaps and every path record are retained in the lossless supplement.

### UpDown40Return8hTenUnitLongCash

#### all admissions

n=167; completed=167; median MFE bounds=[411.71088746569274, 411.71088746569274]bps; median MAE bounds=[-337.3978927429833, -337.3978927429833]bps.

Best per-unit net trade: `{'symbol': 'LINKUSDT', 'entry_time': '2023-06-20T00:00:00Z', 'status': 'COMPLETED', 'net_bps': 1651.7801949665145, 'gross_bps': 1698.4807167900274, 'net_cash_profit_or_cutoff_mark': 8.497199999999793}`. Worst: `{'symbol': 'SOLUSDT', 'entry_time': '2025-02-01T00:00:00Z', 'status': 'COMPLETED', 'net_bps': -4363.962242490899, 'gross_bps': -4341.372912801485, 'net_cash_profit_or_cutoff_mark': -1013.4583999999995}`.

Correct-direction fraction=0.6706586826347305; positive active-entry-week fraction=0.6741573033707865; positive calendar-week fraction including zeros=0.3488372093023256.

Path means/medians: `{'pre_first_mfe_mae_bps_bounds': {'mean': [-307.3284919990751, -305.5945916232269], 'median': [-176.38588912887053, -171.3859910581228]}, 'mae_through_endpoint_bps_bounds': {'mean': [-801.3150563210813, -801.3150563210813], 'median': [-337.3978927429833, -337.3978927429833]}, 'hypothetical_peak_net_after_cost_bps_bounds': {'mean': [474.2360541635513, 474.2360541635513], 'median': [370.1471713480653, 370.1471713480653]}, 'mfe_giveback_to_endpoint_bps_bounds': {'mean': [474.33991659912533, 474.33991659912533], 'median': [176.43250242797004, 176.43250242797004]}}`.

Hypothetical peak after baseline cost clears zero fraction bounds: `[0.9461077844311377, 0.9461077844311377]`.

#### completed only

n=167; completed=167; median MFE bounds=[411.71088746569274, 411.71088746569274]bps; median MAE bounds=[-337.3978927429833, -337.3978927429833]bps.

Best per-unit net trade: `{'symbol': 'LINKUSDT', 'entry_time': '2023-06-20T00:00:00Z', 'status': 'COMPLETED', 'net_bps': 1651.7801949665145, 'gross_bps': 1698.4807167900274, 'net_cash_profit_or_cutoff_mark': 8.497199999999793}`. Worst: `{'symbol': 'SOLUSDT', 'entry_time': '2025-02-01T00:00:00Z', 'status': 'COMPLETED', 'net_bps': -4363.962242490899, 'gross_bps': -4341.372912801485, 'net_cash_profit_or_cutoff_mark': -1013.4583999999995}`.

Correct-direction fraction=0.6706586826347305; positive active-entry-week fraction=0.6741573033707865; positive calendar-week fraction including zeros=0.3488372093023256.

Path means/medians: `{'pre_first_mfe_mae_bps_bounds': {'mean': [-307.3284919990751, -305.5945916232269], 'median': [-176.38588912887053, -171.3859910581228]}, 'mae_through_endpoint_bps_bounds': {'mean': [-801.3150563210813, -801.3150563210813], 'median': [-337.3978927429833, -337.3978927429833]}, 'hypothetical_peak_net_after_cost_bps_bounds': {'mean': [474.2360541635513, 474.2360541635513], 'median': [370.1471713480653, 370.1471713480653]}, 'mfe_giveback_to_endpoint_bps_bounds': {'mean': [474.33991659912533, 474.33991659912533], 'median': [176.43250242797004, 176.43250242797004]}}`.

Hypothetical peak after baseline cost clears zero fraction bounds: `[0.9461077844311377, 0.9461077844311377]`.

Raw completed-candle BUY availability counts (includes held/rejected/final-unexecuted): {'ETHUSDT': 1617, 'SOLUSDT': 1591, 'LINKUSDT': 1671}

Full concentration shares/HHI by symbol/month/week, matched-event BTC beta endpoint scenarios, conditional cost curves, raw/entry session overlaps and every path record are retained in the lossless supplement.

