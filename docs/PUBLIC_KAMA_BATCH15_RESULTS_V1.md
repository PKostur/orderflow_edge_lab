# Public KAMA state cash batch15 results

Historical hypothetical development screen. No viable candidate, untouched result or future confirmation. No exchange orders.

Baseline `263f3c8ff0dc96b4cbb9b4899e4a56cadd181149`; design `e7e695b24cdc6ce3d498c82e56eecd5cce36534a`; execution `e1216adb2507c79fc4f52a5cb58d14d36e28b5bf`; exact evaluator SHA256 `8924d2d4f79f6e604c1ffb550bbb90b56f549ae161e584c7bea3cf76bc72779a`.

## Source and scope

[Pinned source](https://github.com/Hulme-Labs/indicatorgo/blob/35bd387db11de8e544ad545c68f198677ce4c6b7/strategy/trend/kama_strategy.go). ER10/fast2/slow30; close9 seed, first output10, compensated rolling denominator, full-history carry. Repeated BUYclose>KAMA/SELLclose<KAMA/HOLDequality-or-NaN. Preserve permanent recursive NaN, no repair. Fullcash source intent, declared fixed signal-close floor8 fee-reserved quantity at next minute OPEN, all-or-reject. No native bot/exchange execution parity. Original AGPL Go/helper/harness/build stays outside Git; independently authored equations and URI/hash/numeric provenance only.

## Data and execution

Binance Spot BTC benchmark and ETH/SOL/LINK sleeves,2023-04-01 through2026-09-30 inclusive;1,841,760 minutes/3837 eight-hour bars per symbol. First eligible2023-06-20T00Z after240 closed bars. Spent development data; no2022 bear. Three10000USDT sleeves, own funded BTC. No protection/timeout/short/borrow/pyramid/resize. Eight-hour-close drawdown is not an intrabar bound.

## Decision

REJECTED_AS_ADAPTED

Failed gates: excess_descriptive_ci, leave_week_positive, net80_positive, net_descriptive_ci, placebo_tail, portfolio_drawdown, positive_year_fraction.

## Baseline returns and funded portfolio

- admitted: `716`
- completed: `715`
- censored_mtm: `1`
- mean_net_bps: `13.07110369190114`
- median_net_bps: `-157.81839189588308`
- mean_completed_only_net_bps: `13.207961564531582`
- per_unit_profit_factor: `1.0666761021464446`
- cash_profit_factor_with_cutoff_marks: `0.9764676211003076`
- completed_cash_profit_factor: `0.9766991182827361`
- win_fraction: `0.25139664804469275`
- mean_gross_bps: `53.20365320569637`
- mean_btc_excess_lower_bps: `27.24144085457513`
- mean_btc_excess_upper_bps: `27.24144085457513`
- mean_mfe_lower_bps: `584.6510081875462`
- mean_mfe_upper_bps: `584.6510081875462`
- mean_mae_lower_bps: `-273.82650250877145`
- mean_mae_upper_bps: `-273.82650250877145`

- roi_pct: `-18.56625152914613`
- drawdown_pct: `-75.0173732008991`
- funded_btc_roi_lower_pct: `-38.36937544150463`
- funded_btc_roi_upper_pct: `-38.36937544150463`
- note: `8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.`

## Cost stress

- 20:conservative_limit: net mean `33.117332220271514` bps; PF `1.1824315748592087`; funded portfolio `{'roi_pct': 31.82325520888254, 'drawdown_pct': -68.53263009205514, 'funded_btc_roi_lower_pct': -0.8343574432549072, 'funded_btc_roi_upper_pct': -0.8343574432549072, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 20:opening_price_improvement: net mean `33.117332220271514` bps; PF `1.1824315748592087`; funded portfolio `{'roi_pct': 31.82325520888254, 'drawdown_pct': -68.53263009205514, 'funded_btc_roi_lower_pct': -0.8343574432549072, 'funded_btc_roi_upper_pct': -0.8343574432549072, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 40:conservative_limit: net mean `13.07110369190114` bps; PF `1.0666761021464446`; funded portfolio `{'roi_pct': -18.56625152914613, 'drawdown_pct': -75.0173732008991, 'funded_btc_roi_lower_pct': -38.36937544150463, 'funded_btc_roi_upper_pct': -38.36937544150463, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 40:opening_price_improvement: net mean `13.07110369190114` bps; PF `1.0666761021464446`; funded portfolio `{'roi_pct': -18.56625152914613, 'drawdown_pct': -75.0173732008991, 'funded_btc_roi_lower_pct': -38.36937544150463, 'funded_btc_roi_upper_pct': -38.36937544150463, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 60:conservative_limit: net mean `-6.935152297028593` bps; PF `0.9670853092420518`; funded portfolio `{'roi_pct': -49.6701034274725, 'drawdown_pct': -81.76709946381936, 'funded_btc_roi_lower_pct': -61.678954986877486, 'funded_btc_roi_upper_pct': -61.678954986877486, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 60:opening_price_improvement: net mean `-6.935152297028593` bps; PF `0.9670853092420518`; funded portfolio `{'roi_pct': -49.6701034274725, 'drawdown_pct': -81.76709946381936, 'funded_btc_roi_lower_pct': -61.678954986877486, 'funded_btc_roi_upper_pct': -61.678954986877486, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 80:conservative_limit: net mean `-26.901555186380946` bps; PF `0.8807233476821851`; funded portfolio `{'roi_pct': -68.87880962593285, 'drawdown_pct': -87.30617824523526, 'funded_btc_roi_lower_pct': -76.16139020039496, 'funded_btc_roi_upper_pct': -76.16139020039496, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 80:opening_price_improvement: net mean `-26.901555186380946` bps; PF `0.8807233476821851`; funded portfolio `{'roi_pct': -68.87880962593285, 'drawdown_pct': -87.30617824523526, 'funded_btc_roi_lower_pct': -76.16139020039496, 'funded_btc_roi_upper_pct': -76.16139020039496, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.

## Baseline diagnostics

Entry weeks: `169`. Positive entry-year fraction: `0.5`. Worst leave-one-entry-week-out mean: `-3.1681155270268455` bps.

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
      -71.30657637652928,
      104.88866559968832
    ],
    "excess_lower_bps": [
      -25.465247129318506,
      84.22016319747799
    ]
  },
  "alpha_policy": "Fixed0.025 conservative carryover from previous two-cell comparator; only1new registered cell; no global search correction",
  "new_registered_cells": 1
}
```

Calendar, month/year, UTC session/hour, weekday, overlapping session, causal BTC-state and symbol groups, plus every leave-week sensitivity are retained in the lossless result and compact result_summary. The intervals are descriptive and do not adjust the global repeated search.

## Controls and lag

500 weekly randomized BUY controls, original SELL exits, own funding and endogenous durations. Tail `0.938`; numerator `469/500`. No original holding duration reuse. All500 means retained in the artifact.

Seven-bar lag control:

```json
{
  "conservative_limit": [
    {
      "admitted": 1180,
      "completed": 1179,
      "censored_mtm": 1,
      "mean_net_bps": -8.684233598063052,
      "median_net_bps": -70.87824536250231,
      "mean_completed_only_net_bps": -8.61968903348222,
      "per_unit_profit_factor": 0.9353548861560795,
      "cash_profit_factor_with_cutoff_marks": 0.9155553194719239,
      "completed_cash_profit_factor": 0.9157192559231395,
      "win_fraction": 0.3347457627118644,
      "mean_gross_bps": 31.361120175091052,
      "mean_btc_excess_lower_bps": 21.00206881839979,
      "mean_btc_excess_upper_bps": 21.00206881839979,
      "mean_mfe_lower_bps": 362.4423023440445,
      "mean_mfe_upper_bps": 362.4423023440445,
      "mean_mae_lower_bps": -220.24029235109668,
      "mean_mae_upper_bps": -220.24029235109668
    }
  ],
  "opening_price_improvement": [
    {
      "admitted": 1180,
      "completed": 1179,
      "censored_mtm": 1,
      "mean_net_bps": -8.684233598063052,
      "median_net_bps": -70.87824536250231,
      "mean_completed_only_net_bps": -8.61968903348222,
      "per_unit_profit_factor": 0.9353548861560795,
      "cash_profit_factor_with_cutoff_marks": 0.9155553194719239,
      "completed_cash_profit_factor": 0.9157192559231395,
      "win_fraction": 0.3347457627118644,
      "mean_gross_bps": 31.361120175091052,
      "mean_btc_excess_lower_bps": 21.00206881839979,
      "mean_btc_excess_upper_bps": 21.00206881839979,
      "mean_mfe_lower_bps": 362.4423023440445,
      "mean_mfe_upper_bps": 362.4423023440445,
      "mean_mae_lower_bps": -220.24029235109668,
      "mean_mae_upper_bps": -220.24029235109668
    }
  ]
}
```

## Per-symbol baseline

| Symbol | Admitted | Completed | Cutoff | Mean net40 bps | Per-unit PF | Cash PF |
|---|---:|---:|---:|---:|---:|---:|
| ETHUSDT | 236 | 236 | 0 | 1.5158301090035478 | 1.0099234398171444 | 0.9290119297019231 |
| SOLUSDT | 253 | 253 | 0 | 29.471797667725976 | 1.1399091144784992 | 1.002209450537679 |
| LINKUSDT | 227 | 226 | 1 | 6.805328316042754 | 1.0302785953812266 | 0.9587056698545712 |

## Verification and limitations

1161 required repository tests and17 new tests passed; Ruff passed. Independent exact reproduction, separate cash/BTC/events/NAV/excursion oracle and diagnostic/gate audit retained.14 frozen lanes and prior paths hash-preserved. Full numeric evidence retained losslessly.500 weekly controls use own funding and endogenous duration; original SELL remains false under invalidKAMA. Fixed descriptivealpha.025 is not global repeated-search correction. Prior trend/adaptive-average overlap remains. No retuning or promotion from historical screening. User completion requires separately frozen adequately powered untouched future confirmation with calibrated costs/quotes/execution, controls and paper reliability. Publication checks pending.
