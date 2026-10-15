# Public OU one-unit long/cash batch13 results

Frozen mathematical Spot adaptation; historical development evidence only. No viable candidate or future confirmation. Source formulas, unit quantity, native parity and license limits remain in the preregistration. No live orders.

Baseline `806568ce262a6dc5d084e2c2c5228031268bdaf5`; design `71f4f948e647d536b88efdb2a157457b66be634b`; execution `33e39979ed06deb5b617aaaaeba8a0b6e144f5a4`; evaluator exact SHA256 `a982c29c8805becfe405df3dd7b32733f3ad337d680a8bb31612af4169b6f429`.

## Data and execution

Binance Spot BTC/ETH/SOL/LINK,2023-04-01 through2026-09-30 inclusive;1,841,760 minutes and3,837 eight-hour bars each. First eligible2023-06-20T00Z after240 closed bars. BTC benchmark; three10000USDT sleeves, fixed one base unit. All-or-reject at next minute OPEN with fee-inclusive debit. No stop/target/trailing/timeout or resize. Eight-hour-close drawdown is not an intrabar bound. No2022 bear coverage. These data were already inspected.

## Decision

REJECTED_AS_ADAPTED

Failed gates: excess_descriptive_ci, net_descriptive_ci, placebo_tail.

## Returns and portfolio

- admitted: `172`
- completed: `172`
- censored_mtm: `0`
- mean_net_bps: `87.32803527953644`
- median_net_bps: `127.88956555639385`
- mean_completed_only_net_bps: `87.32803527953644`
- per_unit_profit_factor: `1.6232288644749577`
- cash_profit_factor_with_cutoff_marks: `1.5391893528647833`
- completed_cash_profit_factor: `1.5391893528647833`
- win_fraction: `0.6453488372093024`
- mean_gross_bps: `127.7582077656269`
- mean_btc_excess_lower_bps: `48.399641022311975`
- mean_btc_excess_upper_bps: `48.399641022311975`
- mean_mfe_lower_bps: `455.44744964474353`
- mean_mfe_upper_bps: `455.44744964474353`
- mean_mae_lower_bps: `-418.93547614364263`
- mean_mae_upper_bps: `-418.93547614364263`

- roi_pct: `3.1286234266666657`
- drawdown_pct: `-2.955112314676356`
- funded_btc_roi_lower_pct: `2.55563436187225`
- funded_btc_roi_upper_pct: `2.55563436187225`
- note: `8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.`

## Cost stress

- 20bps: mean `107.52292663123112`, PF `1.8058355470028082`, ROI `4.078905046666637`, DD `-2.9360019759679945`.
- 40bps: mean `87.32803527953644`, PF `1.6232288644749577`, ROI `3.1286234266666657`, DD `-2.955112314676356`.
- 60bps: mean `67.17341290362019`, PF `1.4559858258593732`, ROI `2.178341806666695`, DD `-2.9745121533578`.
- 80bps: mean `47.05893917785293`, PF `1.3041863564484664`, ROI `1.228060186666724`, DD `-3.042051112628319`.

## Clusters, sessions and controls

Entry weeks `59`; calendar weeks including zeros `172`; worst leave-week mean `57.300079317082115`; positive-year fraction `1.0`.

97.5% descriptive intervals: `{'net_bps': [-21.01664972375278, 190.75382170591055], 'excess_lower_bps': [-34.09102218068358, 138.3594791548805]}`.

500 weekly randomized complete-entry-qualifier controls tail `0.546`; independent cash/admission/durations and original z>0 exits. Controls can enter invalid-fit rows; invalid exits remain false. Seven-bar lag `{'conservative_limit': [{'admitted': 139, 'completed': 139, 'censored_mtm': 0, 'mean_net_bps': 9.17192350792935, 'median_net_bps': 64.95525517562051, 'mean_completed_only_net_bps': 9.17192350792935, 'per_unit_profit_factor': 1.0516695380017445, 'cash_profit_factor_with_cutoff_marks': 1.0553063748126346, 'completed_cash_profit_factor': 1.0553063748126346, 'win_fraction': 0.5899280575539568, 'mean_gross_bps': 49.288845045035444, 'mean_btc_excess_lower_bps': 17.630520766090203, 'mean_btc_excess_upper_bps': 17.630520766090203, 'mean_mfe_lower_bps': 391.24303409712104, 'mean_mfe_upper_bps': 391.24303409712104, 'mean_mae_lower_bps': -490.06294268568104, 'mean_mae_upper_bps': -490.06294268568104}], 'opening_price_improvement': [{'admitted': 139, 'completed': 139, 'censored_mtm': 0, 'mean_net_bps': 9.17192350792935, 'median_net_bps': 64.95525517562051, 'mean_completed_only_net_bps': 9.17192350792935, 'per_unit_profit_factor': 1.0516695380017445, 'cash_profit_factor_with_cutoff_marks': 1.0553063748126346, 'completed_cash_profit_factor': 1.0553063748126346, 'win_fraction': 0.5899280575539568, 'mean_gross_bps': 49.288845045035444, 'mean_btc_excess_lower_bps': 17.630520766090203, 'mean_btc_excess_upper_bps': 17.630520766090203, 'mean_mfe_lower_bps': 391.24303409712104, 'mean_mfe_upper_bps': 391.24303409712104, 'mean_mae_lower_bps': -490.06294268568104, 'mean_mae_upper_bps': -490.06294268568104}]}`.

Symbol/year/month/weekday/hour, UTC session memberships/overlap, BTC state, MFE/MAE, leave-week/symbol, all cost/gap and cash histories are retained in full and compact artifacts. Cutoff marks are not completed trades. Both gap labels coincide because no protective orders exist. Bootstrap uses2000 moving4-calendar-week blocks including zeros. Fixedalpha.025 is descriptive carryover, not global repeated-search adjustment.

## Audit and trial accounting

Independent audit `06dc5350c3d3bd01afa829e7005913b66c1e7de53c7679097a25db0ca36e4caf`; limits remain in that report.1126 mandatory tests and17 new tests pass; Ruff passes.14 frozen and169 prior paths rehashed. New cell brings minimum26 trading/27 signal-model attempts. Earlier rejected versions remain closed. Historical survival would only permit a separate future-only preregistration; viability requires passing that future confirmation.

Raw `374ce971e6c448726f0e5046991c5c12418e1448e5c2d2fa5cb5a1207cc637ee` (17554002bytes); lossless gzip `c04f8a8a9c8563fa592cc65817634124542d8918e8a7feab11cfdf314183a298` (952436bytes).

## Rerun

Pinned Python3.13.14/NumPy2.2.4/pandas2.2.3/SciPy1.15.2/win32 and exact raw archives/config/audits required. Choose a new output path.

```powershell
$env:PYTHONPATH='src'
python -m orderflow_edge_lab.public_ou_batch13 --raw ../../outputs/Minute-continuous-source-data --cache ../protective_batch5_cache --output ../../outputs/OU-batch13-rerun.json
```

## Independent verification detail

Four baseline cost/gap cases reproduced exactly; 688 event records, 12 cash/BTC paths and 129528 NAV values independently reconstructed, maximum residual 0.0. Calendar bootstrap intervals, portfolio returns/drawdown, leave-week, symbol/year breadth and final gates independently recomputed. Stored500 control means verify273/500 tail arithmetic; full500 path replay was not independently performed. Scalar source reconstruction shares the frozen SciPy kernel, not an independent OLS derivation.

| Symbol | Completed / cutoff | Mean net40 bps | PF40 |
|---|---:|---:|---:|
| ETHUSDT | 46 / 0 | 79.361558 | 1.793493 |
| LINKUSDT | 63 / 0 | 125.831052 | 1.782519 |
| SOLUSDT | 63 / 0 | 54.641812 | 1.367400 |
