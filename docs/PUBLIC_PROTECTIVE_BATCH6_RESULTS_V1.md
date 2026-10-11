# Public protective batch6 results

Two new public-source mathematical adaptations were frozen before market outcomes. Historical evidence is spent development; no native fill parity or untouched confirmation pass is claimed. The user endpoint requires confirmation on future observations collected after a separate freeze.

Baseline main `eaac1e58f4cf05b56611c1bd4ef29293914cfc6e`; design `eaaef0c1845cc56cc5ba4d20413153e85b65b377`; evaluator `4885536c061c6ad1980db93091e4d03cf41e56ee`.

## Data and mechanics

Binance Spot BTCUSDT, ETHUSDT, SOLUSDT and LINKUSDT,2023-04-01 through2026-09-30 inclusive:1,841,760minutes and3,837 eight-hour bars each. First eligible entry2023-06-20 00:00 UTC after240closed bars. The longest shared complete segment is unchanged from the prior quality-only selection; no repairs/imputation or2022bear coverage. BTC is a funded benchmark; three altcoin sleeves trade hypothetically.

PSAR uses an independent official-reference recurrence, strict close crosses, ATR14 stop3/target2 and original-long-condition bracket replacements. CMF21 uses original signed close-location volume arithmetic and NaN propagation. Native5m horizon is adapted to8h. Its actual-entry5% stop and fee-aware rounded strict1% ROI are explicit mathematical ports: ROI observed at minute close queues a next-minute-open liquidation, without a resting target. Native limit orders, off-exchange stop polling and tick rounding are adapted; no native execution parity. See the immutable configuration and source/framework audits.

Both retain fee-reserved signal-close sizing, next-open all-or-reject affordability,20/40/60/80bps economic cases, no intrabar re-entry/borrowing/timeout, censored cutoff inventory, funded BTC intervals and MFE/MAE uncertainty. Drawdown is sampled at8h closes. Source trigger fees are fixed at0.1% each side; total fees plus assumed friction vary by cost case.

## Results

| Candidate | Completed / pending | Net40 / net80 mean bps | PF40 | ROI40 / DD40 | Placebo tail | Decision |
|---|---:|---:|---:|---:|---:|---|
| PSARReference8hSpot | 333 / 1 | -0.926011 / -40.842793 | 0.996337 | -13.533303% / -57.916985% | 0.894000 | REJECTED_AS_ADAPTED |
| CMF21Spot8hMinuteCloseROI | 1777 / 0 | -47.731484 / -87.461416 | 0.569948 | -94.203645% / -94.724952% | 0.282000 | REJECTED_AS_ADAPTED |

Table: first conservative-limit full history. Every supported baseline history must pass; full branch/gap/cost histories and all events remain in the lossless archive. CMF has no target and both registered target-gap profiles intentionally coincide.

### PSARReference8hSpot

Failed gates: all_symbols_positive, excess_descriptive_ci, leave_week_positive, net40_mean, net80_positive, net_descriptive_ci, placebo_tail, portfolio_drawdown, positive_year_fraction.

Entry weeks 157; calendar weeks including zeros 172. Descriptive97.5% intervals `{'net_bps': [-98.12876381717075, 90.26447486792715], 'excess_lower_bps': [-53.72421619814377, 74.9794395963849]}`. Worst leave-week mean -6.444640bps; positive year fraction 50.00%.

| Symbol | Admitted / completed / pending | Net40 bps | Flag accounting |
|---|---:|---:|---|
| ETHUSDT | 108 / 107 / 1 | -54.120565 | `{'raw_entry_flags': 143, 'accepted_entries': 108, 'cash_rejected': 35}` |
| SOLUSDT | 108 / 108 / 0 | 25.050369 | `{'raw_entry_flags': 150, 'accepted_entries': 108, 'cash_rejected': 42}` |
| LINKUSDT | 118 / 118 / 0 | 23.985539 | `{'raw_entry_flags': 159, 'accepted_entries': 118, 'cash_rejected': 41}` |

Seven-bar lag summaries: `{'conservative_limit': [{'admitted': 313, 'completed': 312, 'censored_mtm': 1, 'mean_net_bps': -73.80789643156488, 'median_net_bps': -173.4307005222202, 'mean_completed_only_net_bps': -74.05797277499373, 'per_unit_profit_factor': 0.7427072063525931, 'cash_profit_factor_with_cutoff_marks': 0.7236663754536142, 'completed_cash_profit_factor': 0.723647344461389, 'win_fraction': 0.3961661341853035, 'mean_gross_bps': -34.02355934311417, 'mean_btc_excess_lower_bps': -18.534408673642563, 'mean_btc_excess_upper_bps': -7.341037049529206, 'mean_mfe_lower_bps': 401.8743412879596, 'mean_mfe_upper_bps': 410.5118065202229, 'mean_mae_lower_bps': -421.63299832217797, 'mean_mae_upper_bps': -416.6552215380783}], 'opening_price_improvement': [{'admitted': 313, 'completed': 312, 'censored_mtm': 1, 'mean_net_bps': -73.79397162621629, 'median_net_bps': -173.4307005222202, 'mean_completed_only_net_bps': -74.04400333885877, 'per_unit_profit_factor': 0.7427557479347591, 'cash_profit_factor_with_cutoff_marks': 0.723702012932178, 'completed_cash_profit_factor': 0.72368298293371, 'win_fraction': 0.3961661341853035, 'mean_gross_bps': -34.0095787269225, 'mean_btc_excess_lower_bps': -18.52048386829398, 'mean_btc_excess_upper_bps': -7.327112244180617, 'mean_mfe_lower_bps': 401.8743412879596, 'mean_mfe_upper_bps': 410.5118065202229, 'mean_mae_lower_bps': -421.63299832217797, 'mean_mae_upper_bps': -416.6552215380783}]}`.

Supported joint histories: `{'20:conservative_limit': 1, '20:opening_price_improvement': 1, '40:conservative_limit': 1, '40:opening_price_improvement': 1, '60:conservative_limit': 1, '60:opening_price_improvement': 1, '80:conservative_limit': 1, '80:opening_price_improvement': 1}`.

### CMF21Spot8hMinuteCloseROI

Failed gates: all_symbols_positive, excess_descriptive_ci, leave_week_positive, net40_mean, net80_positive, net_descriptive_ci, placebo_tail, portfolio_drawdown, positive_year_fraction.

Entry weeks 160; calendar weeks including zeros 172. Descriptive97.5% intervals `{'net_bps': [-68.52001781138462, -27.47660678954054], 'excess_lower_bps': [-22.717039890167626, -0.9777673277640115]}`. Worst leave-week mean -49.247461bps; positive year fraction 0.00%.

| Symbol | Admitted / completed / pending | Net40 bps | Flag accounting |
|---|---:|---:|---|
| ETHUSDT | 519 / 519 / 0 | -40.562732 | `{'raw_entry_flags': 1479, 'accepted_entries': 519, 'held_entry_ignored': 754, 'cash_rejected': 205, 'unexecuted_final_entry': 1}` |
| SOLUSDT | 662 / 662 / 0 | -51.021699 | `{'raw_entry_flags': 1488, 'accepted_entries': 662, 'held_entry_ignored': 601, 'cash_rejected': 224, 'unexecuted_final_entry': 1}` |
| LINKUSDT | 596 / 596 / 0 | -50.319506 | `{'raw_entry_flags': 1422, 'cash_rejected': 232, 'accepted_entries': 596, 'held_entry_ignored': 594}` |

Seven-bar lag summaries: `{'conservative_limit': [{'admitted': 1975, 'completed': 1975, 'censored_mtm': 0, 'mean_net_bps': -43.48833814885621, 'median_net_bps': 81.5683803051992, 'mean_completed_only_net_bps': -43.48833814885621, 'per_unit_profit_factor': 0.5685397745003902, 'cash_profit_factor_with_cutoff_marks': 0.56409432163327, 'completed_cash_profit_factor': 0.56409432163327, 'win_fraction': 0.649620253164557, 'mean_gross_bps': -3.5824797847233327, 'mean_btc_excess_lower_bps': -7.350237873423901, 'mean_btc_excess_upper_bps': -3.1478326347344256, 'mean_mfe_lower_bps': 110.98084769763318, 'mean_mfe_upper_bps': 110.98084769763318, 'mean_mae_lower_bps': -183.7054072392373, 'mean_mae_upper_bps': -180.47903987748956}], 'opening_price_improvement': [{'admitted': 1975, 'completed': 1975, 'censored_mtm': 0, 'mean_net_bps': -43.48833814885621, 'median_net_bps': 81.5683803051992, 'mean_completed_only_net_bps': -43.48833814885621, 'per_unit_profit_factor': 0.5685397745003902, 'cash_profit_factor_with_cutoff_marks': 0.56409432163327, 'completed_cash_profit_factor': 0.56409432163327, 'win_fraction': 0.649620253164557, 'mean_gross_bps': -3.5824797847233327, 'mean_btc_excess_lower_bps': -7.350237873423901, 'mean_btc_excess_upper_bps': -3.1478326347344256, 'mean_mfe_lower_bps': 110.98084769763318, 'mean_mfe_upper_bps': 110.98084769763318, 'mean_mae_lower_bps': -183.7054072392373, 'mean_mae_upper_bps': -180.47903987748956}]}`.

Supported joint histories: `{'20:conservative_limit': 1, '20:opening_price_improvement': 1, '40:conservative_limit': 1, '40:opening_price_improvement': 1, '60:conservative_limit': 1, '60:opening_price_improvement': 1, '80:conservative_limit': 1, '80:opening_price_improvement': 1}`.

## Verification and interpretation

500 randomized-entry controls per adaptation preserve eligible entry-week raw flag counts, rerun causal source exits/protection and own endogenous durations. Seven-bar causal lag excludes pre-warmup flags.2000 moving4calendar-week bootstrap draws include zero-event weeks. Intervals and control tails are descriptive, without a global repeated-search adjustment. Full session, cluster, return, MFE/MAE, BTC, symbol/year and leave-out diagnostics remain auditable.

1,019 mandatory tests, including15new synthetic tests, passed; Ruff passed. Pre-outcome read-only review and independent baseline/control accounting review are retained. Exact-head publication checks are recorded separately. The fourteen frozen hashes and all prior public definitions/PSR11 artifacts are preserved. DON8, EMA8, VOL8, DV2, D4, payoff geometry, session watches and prospective protocols are unchanged. Bollinger is excluded; no order clients added.

Minimum cumulative attempted trading cells19; signal/model cells20. Related cost/gap/control variants are not independent trials. Source searches, forecast and feasibility history remain separately disclosed. PSAR shares the prior ATR payoff shape; CMF belongs to the broad volume family. No independence claim.

No candidate is viable until a separately frozen, adequately powered untouched future confirmation passes with calibrated costs and paper reliability. Rejected versions stay closed; a next source needs new registration before outcomes. A historical survivor permits prospective registration only.

## Repeat the registered study

Use the pinned Windows Python 3.13.14 / NumPy 2.2.4 / pandas 2.2.3 runtime, a checkout retaining the registration commit and the exact raw archives/checksum receipts. Cached arrays are rehashed and bound to those archives. Choose a new output path; the evaluator refuses overwriting an earlier attempt. From the repository root:

```powershell
$env:PYTHONPATH='src'
python -m orderflow_edge_lab.public_protective_batch6 --raw ../../outputs/Minute-continuous-source-data --cache ../protective_batch5_cache --output ../../outputs/Protective-batch6-rerun.json
```

Pre-outcome independent validation matched SAR on eight synthetic fixtures and 64 prefixes, and CMF execution on 40 synthetic cases. Final baseline reproduction uses the same frozen strategy evaluator with an independent accounting reconstruction; it is not a second native trading engine. Stored control tails are independently recalculated, not all 500 control paths independently rerun.

A separate bounded source survey inspected seven further files and accepted no new candidate under its exclusions. Its pinned hashes/defaults and reasons are in source-only-next-survey.json. This adds zero trading cells and does not establish that every possible public source has been exhausted.
