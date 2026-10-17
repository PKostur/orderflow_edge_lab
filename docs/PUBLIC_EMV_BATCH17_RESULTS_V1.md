# Public EMV state cash batch17 results

Historical hypothetical development screen. No viable candidate, untouched result or future confirmation. No exchange orders.

Baseline `6d873b0f2e1f11e5cf65ee1833a3a199a3c695be`; design `8aa49ae9286dc83378a944184a4406ae733d8c96`; execution `076e74010406b40f9fb36e58e38dfba2f84bc68e`; exact evaluator SHA256 `6f5f402f45af45be1d37596096f3bb842fc9fe51288eb4113b6a1b5acb796961`.

## Source and scope

[Pinned source](https://github.com/Hulme-Labs/indicatorgo/blob/35bd387db11de8e544ad545c68f198677ce4c6b7/strategy/volume/ease_of_movement_strategy.go). Midpoint change divided by previous-bar boxratio=(basevolume/1e8)/(high-low), not currentbox. Compensated14period SMA, incoming-before-outgoing and physicalring nonfinite recovery. First output14. Repeated BUYlevel>0/SELLlevel<0/HOLDequality-orunordered, notcrossings. Preserve zero-range/zero-volume arithmetic and recovery, clip phantom short-input HOLD padding. Fullcash source intent, declared fixed signal-close floor8 fee-reserved quantity at next minute OPEN, all-or-reject. No native bot/exchange execution parity. Original AGPL Go/helper/harness/build stays outside Git; independently authored equations and URI/hash/numeric provenance only.

## Data and execution

Binance Spot BTC benchmark and ETH/SOL/LINK sleeves,2023-04-01 through2026-09-30 inclusive;1,841,760 minutes/3837 eight-hour bars per symbol. First eligible2023-06-20T00Z after240 closed bars. Spent development data; no2022 bear. Three10000USDT sleeves, own funded BTC. No protection/timeout/short/borrow/pyramid/resize. Eight-hour-close drawdown is not an intrabar bound.

## Decision

REJECTED_AS_ADAPTED

Failed gates: excess_descriptive_ci, net80_positive, net_descriptive_ci, portfolio_drawdown.

## Baseline returns and funded portfolio

- admitted: `514`
- completed: `513`
- censored_mtm: `1`
- mean_net_bps: `34.56910283101746`
- median_net_bps: `-129.64908906443307`
- mean_completed_only_net_bps: `31.315903399706762`
- per_unit_profit_factor: `1.1511916445428259`
- cash_profit_factor_with_cutoff_marks: `1.0275101458429237`
- completed_cash_profit_factor: `1.0233870266675533`
- win_fraction: `0.30739299610894943`
- mean_gross_bps: `74.78781667001951`
- mean_btc_excess_lower_bps: `27.976147224894564`
- mean_btc_excess_upper_bps: `27.976147224894564`
- mean_mfe_lower_bps: `671.0373025461726`
- mean_mfe_upper_bps: `671.0373025461726`
- mean_mae_lower_bps: `-364.48926587462864`
- mean_mae_upper_bps: `-364.48926587462864`

- roi_pct: `18.54556602515325`
- drawdown_pct: `-70.8076104478419`
- funded_btc_roi_lower_pct: `-8.654578363591714`
- funded_btc_roi_upper_pct: `-8.654578363591714`
- note: `8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.`

## Cost stress

- 20:conservative_limit: net mean `54.65837048286771` bps; PF `1.2536771006741214`; funded portfolio `{'roi_pct': 67.1720303824771, 'drawdown_pct': -62.736613116979214, 'funded_btc_roi_lower_pct': 28.708284918620475, 'funded_btc_roi_upper_pct': 28.708284918620475, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 20:opening_price_improvement: net mean `54.65837048286771` bps; PF `1.2536771006741214`; funded portfolio `{'roi_pct': 67.1720303824771, 'drawdown_pct': -62.736613116979214, 'funded_btc_roi_lower_pct': 28.708284918620475, 'funded_btc_roi_upper_pct': 28.708284918620475, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 40:conservative_limit: net mean `34.56910283101746` bps; PF `1.1511916445428259`; funded portfolio `{'roi_pct': 18.54556602515325, 'drawdown_pct': -70.8076104478419, 'funded_btc_roi_lower_pct': -8.654578363591714, 'funded_btc_roi_upper_pct': -8.654578363591714, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 40:opening_price_improvement: net mean `34.56910283101746` bps; PF `1.1511916445428259`; funded portfolio `{'roi_pct': 18.54556602515325, 'drawdown_pct': -70.8076104478419, 'funded_btc_roi_lower_pct': -8.654578363591714, 'funded_btc_roi_upper_pct': -8.654578363591714, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 60:conservative_limit: net mean `14.519893539392301` bps; PF `1.059946520910913`; funded portfolio `{'roi_pct': -15.934668609172675, 'drawdown_pct': -77.15436111879974, 'funded_btc_roi_lower_pct': -35.16896454532906, 'funded_btc_roi_upper_pct': -35.16896454532906, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 60:opening_price_improvement: net mean `14.519893539392301` bps; PF `1.059946520910913`; funded portfolio `{'roi_pct': -15.934668609172675, 'drawdown_pct': -77.15436111879974, 'funded_btc_roi_lower_pct': -35.16896454532906, 'funded_btc_roi_upper_pct': -35.16896454532906, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 80:conservative_limit: net mean `-5.489377088307434` bps; PF `0.978573257016391`; funded portfolio `{'roi_pct': -40.38463546505729, 'drawdown_pct': -82.27890816537283, 'funded_btc_roi_lower_pct': -53.98549361268567, 'funded_btc_roi_upper_pct': -53.98549361268567, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.
- 80:opening_price_improvement: net mean `-5.489377088307434` bps; PF `0.978573257016391`; funded portfolio `{'roi_pct': -40.38463546505729, 'drawdown_pct': -82.27890816537283, 'funded_btc_roi_lower_pct': -53.98549361268567, 'funded_btc_roi_upper_pct': -53.98549361268567, 'note': '8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.'}`.

## Baseline diagnostics

Entry weeks: `152`. Positive entry-year fraction: `0.75`. Worst leave-one-entry-week-out mean: `17.585268441275606` bps.

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
      -92.17264158405621,
      189.06105286549544
    ],
    "excess_lower_bps": [
      -44.45890237538599,
      120.8350564679162
    ]
  },
  "alpha_policy": "Fixed0.025 conservative carryover from previous two-cell comparator; only1new registered cell; no global search correction",
  "new_registered_cells": 1
}
```

Calendar, month/year, UTC session/hour, weekday, overlapping session, causal BTC-state and symbol groups, plus every leave-week sensitivity are retained in the lossless result and compact result_summary. The intervals are descriptive and do not adjust the global repeated search.

## Controls and lag

500 weekly randomized BUY controls, original SELL exits, own funding and endogenous durations. Tail `0.012`; numerator `6/500`. No original holding duration reuse. All500 means retained in the artifact.

Seven-bar lag control:

```json
{
  "conservative_limit": [
    {
      "admitted": 1008,
      "completed": 1007,
      "censored_mtm": 1,
      "mean_net_bps": 3.613591673813281,
      "median_net_bps": -47.96913099683108,
      "mean_completed_only_net_bps": 2.198476329603603,
      "per_unit_profit_factor": 1.0263031603010702,
      "cash_profit_factor_with_cutoff_marks": 0.9438557733335131,
      "completed_cash_profit_factor": 0.9391411142390549,
      "win_fraction": 0.39384920634920634,
      "mean_gross_bps": 43.70823532781656,
      "mean_btc_excess_lower_bps": 17.906211757067567,
      "mean_btc_excess_upper_bps": 17.906211757067567,
      "mean_mfe_lower_bps": 373.73929059219944,
      "mean_mfe_upper_bps": 373.73929059219944,
      "mean_mae_lower_bps": -245.00806784834919,
      "mean_mae_upper_bps": -245.00806784834919
    }
  ],
  "opening_price_improvement": [
    {
      "admitted": 1008,
      "completed": 1007,
      "censored_mtm": 1,
      "mean_net_bps": 3.613591673813281,
      "median_net_bps": -47.96913099683108,
      "mean_completed_only_net_bps": 2.198476329603603,
      "per_unit_profit_factor": 1.0263031603010702,
      "cash_profit_factor_with_cutoff_marks": 0.9438557733335131,
      "completed_cash_profit_factor": 0.9391411142390549,
      "win_fraction": 0.39384920634920634,
      "mean_gross_bps": 43.70823532781656,
      "mean_btc_excess_lower_bps": 17.906211757067567,
      "mean_btc_excess_upper_bps": 17.906211757067567,
      "mean_mfe_lower_bps": 373.73929059219944,
      "mean_mfe_upper_bps": 373.73929059219944,
      "mean_mae_lower_bps": -245.00806784834919,
      "mean_mae_upper_bps": -245.00806784834919
    }
  ]
}
```

## Per-symbol baseline

| Symbol | Admitted | Completed | Cutoff | Mean net40 bps | Per-unit PF | Cash PF |
|---|---:|---:|---:|---:|---:|---:|
| ETHUSDT | 175 | 175 | 0 | 13.491311729529677 | 1.0700309845742721 | 0.9480201403540494 |
| SOLUSDT | 172 | 172 | 0 | 84.31787399894006 | 1.3764496681397913 | 1.1036299017932965 |
| LINKUSDT | 167 | 166 | 1 | 5.418353141662184 | 1.0199815926480176 | 0.9102347465895583 |

## Verification and limitations

1209 required repository tests and17 new tests passed; Ruff passed. Independent exact reproduction, separate cash/BTC/events/NAV/excursion oracle and diagnostic/gate audit retained.14 frozen lanes and prior paths hash-preserved. Full numeric evidence retained losslessly.500 weekly controls use own funding and endogenous duration; original SELL remains false under equality-or-unordered HOLD. Fixed descriptivealpha.025 is not global repeated-search correction. Prior volume/momentum/trend family overlap remains; no orthogonality claim. No retuning or promotion from historical screening. User completion requires separately frozen adequately powered untouched future confirmation with calibrated costs/quotes/execution, controls and paper reliability. Publication checks pending.

## Additional frozen descriptive reporting

Method frozen before EMV market outcomes. Independent514path first-maximum oracle and all/completed populations checked. Full lossless supplement retains original result/source/config/runtime/method/test/review bindings. No rule/gate/decision changes.

| Metric | All514 admissions | Completed513 |
|---|---:|---:|
| median_mfe_bps_bounds | [253.16932474705345, 253.16932474705345] | [253.11056525851637, 253.11056525851637] |
| median_mae_bps_bounds | [-276.15571164100845, -276.15571164100845] | [-276.9541559414812, -276.9541559414812] |
| correct_direction_endpoint_fraction | 0.35797665369649806 | 0.3567251461988304 |
| positive_active_week_fraction | 0.34868421052631576 | 0.34868421052631576 |
| positive_calendar_week_fraction_including_zeros | 0.3081395348837209 | 0.3081395348837209 |
| pre_first_mfe_mae_bps_bounds median | [-65.17625232878854, -65.17625232878854] | [-64.9217522039236, -64.9217522039236] |
| hypothetical_peak_net_after_cost_bps_bounds median | [212.238509079401, 212.238509079401] | [212.17998415968165, 212.17998415968165] |
| mfe_giveback_to_endpoint_bps_bounds median | [497.9842051530303, 497.9842051530303] | [497.16803020767645, 497.16803020767645] |

Best/worst per-unit net events retain endpoint status and cash PnL. Full weekly means/positive fractions, coin/month/week cash-PnL concentration, matched-event BTC OLS endpoint sensitivities, raw BUY completion/session clocks, conditional10/20/30/40/60/80reference-return costs and all514pathdetails retained. These cost rows condition on baseline40admissions and are not new funded simulations/gates. Retrospective peak-after-friction is not a fill; pre-first-MFE OHLC order bounds are not exact tick timing. OLS is dependent descriptive sensitivity, not causal alpha or confidence bounds. Rawflag clocks include ignored/rejected/final-unexecuted flags; UTC labels are fixed, no DST or session filter.

The recorded shared module/test exact078d55ae…/9b3be393… historical bytes are restored in Git under-text; the additive line-ending bridge retains former committedLF86e57e6…/660cc981… hashes and proves identical normalized code/AST. Old executions/reports remain unchanged.

## Independent accounting precision

Four baseline cases reproduce exactly. Separate literal source/cash/BTC/event/diagnostic oracle checks2056eventrecords and129528NAV marks. Maximum accounting residual7.275957614183426e-12, within the pre-existing1e-8audit bound; not falsely reported aszero.500stored control means and tail arithmetic checked, not an independent500control-path rerun.

Reproduce the supplement from the retained application snapshot with final rawresult SHA21e2c3df65f17eae737eb488c91c744ac62934e7790f88c6e59d5e675c98d3b3 and production runtime, restoring the base/work/outputs layout described by the KAMA supplement document. Exact shared module/test/method/review snapshots must match recorded hashes; existing output refuses overwrite. A later rerun has its own execution SHA and must not replace the immutable original record.
