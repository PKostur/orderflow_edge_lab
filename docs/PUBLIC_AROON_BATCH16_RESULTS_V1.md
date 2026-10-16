# Public Aroon state cash batch16 results

Historical hypothetical development screen. No viable candidate, untouched result or future confirmation. No exchange orders.

Baseline `c159c20c1b6a5ba17b7ac12c3ba81f9bfba3b56c`; design `eaeb569101dbcb67551fca84d49a41d8f4c713a7`; execution `e4387b97854ba9aaae98693bdb5d968ca6afae41`; exact evaluator SHA256 `9e5f74bf15faed31f5acd6ed92d448b320aa22581e47630371ef5b1b21197889`.

## Source and scope

[Pinned source](https://github.com/Hulme-Labs/indicatorgo/blob/35bd387db11de8e544ad545c68f198677ce4c6b7/strategy/trend/aroon_strategy.go). Period25 rolling raw extrema, then trailing up-to25 extrema plateau ages, partial prefixes, nearest-away zero-digit rounding. First output24. Repeated BUYroundedUp>roundedDown/SELLreverse/HOLDequality. Preserve native plateau semantics and exclude phantom short-input HOLD padding. Fullcash source intent, declared fixed signal-close floor8 fee-reserved quantity at next minute OPEN, all-or-reject. No native bot/exchange execution parity. Original AGPL Go/helper/harness/build stays outside Git; independently authored equations and URI/hash/numeric provenance only.

## Data and execution

Binance Spot BTC benchmark and ETH/SOL/LINK sleeves,2023-04-01 through2026-09-30 inclusive;1,841,760 minutes/3837 eight-hour bars per symbol. First eligible2023-06-20T00Z after240 closed bars. Spent development data; no2022 bear. Three10000USDT sleeves, own funded BTC. No protection/timeout/short/borrow/pyramid/resize. Eight-hour-close drawdown is not an intrabar bound.

## Decision

REJECTED_AS_ADAPTED

Failed gates: excess_descriptive_ci, net_descriptive_ci, portfolio_drawdown.

## Baseline returns and funded portfolio

- admitted: `110`
- completed: `107`
- censored_mtm: `3`
- mean_net_bps: `463.36376435194836`
- median_net_bps: `-248.1158962410318`
- mean_completed_only_net_bps: `453.63216181782144`
- per_unit_profit_factor: `1.9339611791630766`
- cash_profit_factor_with_cutoff_marks: `1.314426297138412`
- completed_cash_profit_factor: `1.2795478940902363`
- win_fraction: `0.42727272727272725`
- mean_gross_bps: `505.3010940687898`
- mean_btc_excess_lower_bps: `227.4527124854825`
- mean_btc_excess_upper_bps: `227.4527124854825`
- mean_mfe_lower_bps: `2068.608328681076`
- mean_mfe_upper_bps: `2068.608328681076`
- mean_mae_lower_bps: `-866.0878384193118`
- mean_mae_upper_bps: `-866.0878384193118`

- roi_pct: `160.32455917552664`
- drawdown_pct: `-59.37335081168911`
- funded_btc_roi_lower_pct: `91.2389394210856`
- funded_btc_roi_upper_pct: `91.2389394210856`
- note: `8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.`

## Cost stress

- 20:conservative_limit: net mean `484.311481493229` bps; PF `1.9972343117795361`; funded portfolio `{'roi_pct': 178.81497707038437, 'drawdown_pct': -57.75170737485775, 'funded_btc_roi_lower_pct': 105.76726396394935, 'funded_btc_roi_upper_pct': 105.76726396394935, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 20:opening_price_improvement: net mean `484.311481493229` bps; PF `1.9972343117795361`; funded portfolio `{'roi_pct': 178.81497707038437, 'drawdown_pct': -57.75170737485775, 'funded_btc_roi_lower_pct': 105.76726396394935, 'funded_btc_roi_upper_pct': 105.76726396394935, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 40:conservative_limit: net mean `463.36376435194836` bps; PF `1.9339611791630766`; funded portfolio `{'roi_pct': 160.32455917552664, 'drawdown_pct': -59.37335081168911, 'funded_btc_roi_lower_pct': 91.2389394210856, 'funded_btc_roi_upper_pct': 91.2389394210856, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 40:opening_price_improvement: net mean `463.36376435194836` bps; PF `1.9339611791630766`; funded portfolio `{'roi_pct': 160.32455917552664, 'drawdown_pct': -59.37335081168911, 'funded_btc_roi_lower_pct': 91.2389394210856, 'funded_btc_roi_upper_pct': 91.2389394210856, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 60:conservative_limit: net mean `442.45781733458085` bps; PF `1.8734225528207982`; funded portfolio `{'roi_pct': 143.07058411536008, 'drawdown_pct': -61.050635487124396, 'funded_btc_roi_lower_pct': 77.74469696373878, 'funded_btc_roi_upper_pct': 77.74469696373878, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 60:opening_price_improvement: net mean `442.45781733458085` bps; PF `1.8734225528207982`; funded portfolio `{'roi_pct': 143.07058411536008, 'drawdown_pct': -61.050635487124396, 'funded_btc_roi_lower_pct': 77.74469696373878, 'funded_btc_roi_upper_pct': 77.74469696373878, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 80:conservative_limit: net mean `421.59351562999467` bps; PF `1.8152619902303964`; funded portfolio `{'roi_pct': 126.9696231524256, 'drawdown_pct': -62.65794830893753, 'funded_btc_roi_lower_pct': 65.21035510632498, 'funded_btc_roi_upper_pct': 65.21035510632498, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 80:opening_price_improvement: net mean `421.59351562999467` bps; PF `1.8152619902303964`; funded portfolio `{'roi_pct': 126.9696231524256, 'drawdown_pct': -62.65794830893753, 'funded_btc_roi_lower_pct': 65.21035510632498, 'funded_btc_roi_upper_pct': 65.21035510632498, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.

## Baseline diagnostics

Entry weeks: `60`. Positive entry-year fraction: `0.75`. Worst leave-one-entry-week-out mean: `152.55600702797867` bps.

97.5% descriptive intervals from2000 moving4-calendar-week blocks including zero-event weeks:

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
      -290.54583374960635,
      1481.704130239664
    ],
    "excess_lower_bps": [
      -301.2012220346322,
      906.2989177213691
    ]
  },
  "alpha_policy": "Fixed0.025 conservative carryover from previous two-cell comparator; only1new registered cell; no global search correction",
  "new_registered_cells": 1
}
```

Calendar, month/year, UTC session/hour, weekday, overlapping session, causal BTC-state and symbol groups, plus every leave-week sensitivity are retained in the lossless result and compact result_summary. The intervals are descriptive and do not adjust the global repeated search.

## Controls and lag

500 weekly randomized BUY controls, original SELL exits, own funding and endogenous durations. Tail `0.0`; numerator `0/500`. No original holding duration reuse. All500 means retained in the artifact.

Seven-bar lag control:

```json
{
  "conservative_limit": [
    {
      "admitted": 260,
      "completed": 257,
      "censored_mtm": 3,
      "mean_net_bps": 191.48728761242637,
      "median_net_bps": -41.33582987278561,
      "mean_completed_only_net_bps": 189.34655591876054,
      "per_unit_profit_factor": 1.9001771242175107,
      "cash_profit_factor_with_cutoff_marks": 1.538096190125733,
      "completed_cash_profit_factor": 1.5029036536430582,
      "win_fraction": 0.4423076923076923,
      "mean_gross_bps": 232.33493205175472,
      "mean_btc_excess_lower_bps": 104.48552919012907,
      "mean_btc_excess_upper_bps": 104.48552919012907,
      "mean_mfe_lower_bps": 891.9383794334989,
      "mean_mfe_upper_bps": 891.9383794334989,
      "mean_mae_lower_bps": -406.1110861500611,
      "mean_mae_upper_bps": -406.1110861500611
    }
  ],
  "opening_price_improvement": [
    {
      "admitted": 260,
      "completed": 257,
      "censored_mtm": 3,
      "mean_net_bps": 191.48728761242637,
      "median_net_bps": -41.33582987278561,
      "mean_completed_only_net_bps": 189.34655591876054,
      "per_unit_profit_factor": 1.9001771242175107,
      "cash_profit_factor_with_cutoff_marks": 1.538096190125733,
      "completed_cash_profit_factor": 1.5029036536430582,
      "win_fraction": 0.4423076923076923,
      "mean_gross_bps": 232.33493205175472,
      "mean_btc_excess_lower_bps": 104.48552919012907,
      "mean_btc_excess_upper_bps": 104.48552919012907,
      "mean_mfe_lower_bps": 891.9383794334989,
      "mean_mfe_upper_bps": 891.9383794334989,
      "mean_mae_lower_bps": -406.1110861500611,
      "mean_mae_upper_bps": -406.1110861500611
    }
  ]
}
```

## Per-symbol baseline

| Symbol | Admitted | Completed | Cutoff | Mean net40 bps | Per-unit PF | Cash PF |
|---|---:|---:|---:|---:|---:|---:|
| ETHUSDT | 40 | 39 | 1 | 87.57106831051208 | 1.1912540463300667 | 0.9993816144693793 |
| SOLUSDT | 32 | 31 | 1 | 1099.297714538332 | 3.259977058736854 | 1.4194252760182506 |
| LINKUSDT | 38 | 37 | 1 | 323.4116968701897 | 1.593890484044477 | 1.1890003328087178 |

## Verification and limitations

1192 required repository tests and17 new tests passed; Ruff passed. Independent exact reproduction, separate cash/BTC/events/NAV/excursion oracle and diagnostic/gate audit retained.14 frozen lanes and prior paths hash-preserved. Full numeric evidence retained losslessly.500 weekly controls use own funding and endogenous duration; original SELL remains false under equalityHOLD. Fixed descriptivealpha.025 is not global repeated-search correction. Prior trend/range-extreme overlap remains. No retuning or promotion from historical screening. User completion requires separately frozen adequately powered untouched future confirmation with calibrated costs/quotes/execution, controls and paper reliability. Publication checks pending.

## Additional frozen descriptive reporting

Method retained in registration before any Aroon outcomes. Independent110path first-maximum oracle and all/completed populations checked; zero residuals. Full supplement is retained losslessly with exact source/method/test/review/input/runtime bindings. No change to original rules/gates/verdict.

| Metric | All110 admissions | Completed107 |
|---|---:|---:|
| median_mfe_bps_bounds | [974.0554849806005, 974.0554849806005] | [969.7235629662115, 969.7235629662115] |
| median_mae_bps_bounds | [-755.4961882793243, -755.4961882793243] | [-770.9011943539634, -770.9011943539634] |
| correct_direction_endpoint_fraction | 0.42727272727272725 | 0.411214953271028 |
| positive_active_week_fraction | 0.38333333333333336 | 0.3620689655172414 |
| positive_calendar_week_fraction_including_zeros | 0.13372093023255813 | 0.12209302325581395 |
| pre_first_mfe_mae_bps_bounds median | [-189.48752563262005, -189.48752563262005] | [-189.08181283107672, -189.08181283107672] |
| hypothetical_peak_net_after_cost_bps_bounds median | [930.2468802501396, 930.2468802501396] | [925.9322513376045, 925.9322513376045] |
| mfe_giveback_to_endpoint_bps_bounds median | [1371.410584906146, 1371.410584906146] | [1375.7446330223665, 1375.7446330223665] |

Best/worst per-unit net trades, weekly means, positive active/calendar-week fractions, coin/month/week cash-PnL concentration, matched-event BTC OLS sensitivities, raw BUY availability clocks, exact10/20/30/40/60/80 conditional reference-return cost curves and all110pathdetails are in descriptive-supplement-summary.json and descriptive-supplement.json.gz. Cutoff marks retained separately, original funded NAV retained in full result. Extra10/30 cost rows are price arithmetic conditional on original40 admissions, not funded simulations or gates. Peak-after-friction is retrospective movement, never executable peak fills; pre-first-MFE bounds preserve unknown minute OHLC order. BTC endpoint-scenario fits are descriptive, dependent and noncausal, not confidence intervals. UTC sessions are fixed availability labels including final-unexecuted flags, not session filters.

Application provenance snapshot is retained. Rerun with the layout and production runtime described in the KAMA descriptive supplement document, using its immutable Aroon result SHA argument. Method/source/test hashes are identical to the registered shared module/test and retained method. Do not overwrite the original supplemental output or replace its recorded execution commit.
