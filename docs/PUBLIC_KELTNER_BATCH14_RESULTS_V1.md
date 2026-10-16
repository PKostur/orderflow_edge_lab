# Public Keltner one-unit long/cash batch14 results

Frozen mathematical Spot adaptation; historical development evidence only. No viable candidate or future confirmation. Source formulas, unit quantity, native parity and license limits remain in the preregistration. No live orders.

Baseline `d76882adeb37e7d59bd483d3e07dee7969832dd3`; design `cb40b70bcb39baf48931b847ee0ba8c34679a5a1`; execution `536a4cab62dcc2fff79b71132e6e30e1397f494b`; evaluator exact SHA256 `2db0a5e971bdfbbb77576c20abe45e3c3ca1ea7e164f7e90cb665719ba84b9fb`.

## Source and clock

[Pinned source](https://github.com/ali-azary/Algorithmic-Trading-From-Beginner-to-Advanced/blob/945c7c430c799687be17092eaebcad6baace1a9e/codes/KeltnerBreakoutStrategy.py). EMA30 SMA seed, effective Wilder ATR7 seedTR1..7, multiplier1. Original prior-bar breakout is checked after the current bar completes and fills at the following open; breakout atj is filledopenj+2. Held long exits on current close<current EMA30. Flat entry can coincide with current exit and waits until a later boundary to liquidate. Strict floating comparisons, including flat EMA roundoff, and full-history carry are retained. Native two-sided source differs from this declared long/cash scope. Bounded README Code MIT statement, absent standalone notice and placeholder remain disclosed. No native exchange bot or published profitability claim.

## Data and execution

Binance Spot BTC/ETH/SOL/LINK,2023-04-01 through2026-09-30 inclusive;1,841,760 minutes and3,837 eight-hour bars each. First eligible2023-06-20T00Z after240 closed bars. BTC benchmark; three10000USDT sleeves, fixed one base unit. All-or-reject at next minute OPEN with fee-inclusive debit. No stop/target/trailing/timeout or resize. Eight-hour-close drawdown is not an intrabar bound. No2022 bear coverage. These data were already inspected.

## Decision

REJECTED_AS_ADAPTED

Failed gates: excess_descriptive_ci, net_descriptive_ci, positive_year_fraction.

## Returns and portfolio

- admitted: `237`
- completed: `235`
- censored_mtm: `2`
- mean_net_bps: `142.7104474106305`
- median_net_bps: `-260.9082110181826`
- mean_completed_only_net_bps: `137.93289923616715`
- per_unit_profit_factor: `1.4818580415281162`
- cash_profit_factor_with_cutoff_marks: `0.9827837226113781`
- completed_cash_profit_factor: `0.9815890416218389`
- win_fraction: `0.2911392405063291`
- mean_gross_bps: `183.36259349243667`
- mean_btc_excess_lower_bps: `123.58841180333569`
- mean_btc_excess_upper_bps: `123.58841180333569`
- mean_mfe_lower_bps: `1064.7168010067116`
- mean_mfe_upper_bps: `1064.7168010067116`
- mean_mae_lower_bps: `-417.33520499897475`
- mean_mae_upper_bps: `-417.33520499897475`

- roi_pct: `-0.36518284000005563`
- drawdown_pct: `-8.61210413455521`
- funded_btc_roi_lower_pct: `-1.0451420630958275`
- funded_btc_roi_upper_pct: `-1.0451420630958275`
- note: `8h-close hypothetical liquidation-value marks; drawdown is not an intrabar bound. Funded BTC intervals are reference bounds, not executed fills.`

## Cost stress

- 20bps: mean `163.01621468426117`, PF `1.5767637588985002`, ROI `1.1178785799999424`, DD `-8.094530559471924`.
- 40bps: mean `142.7104474106305`, PF `1.4818580415281162`, ROI `-0.36518284000005563`, DD `-8.61210413455521`.
- 60bps: mean `122.44517020135635`, PF `1.3951984709410237`, ROI `-1.848244259999976`, DD `-9.138895470204755`.
- 80bps: mean `102.22026207018611`, PF `1.3158437842523878`, ROI `-3.331305679999985`, DD `-9.675153025361405`.

## Clusters, sessions and controls

Entry weeks `108`; calendar weeks including zeros `172`; worst leave-week mean `37.65121701339345`; positive-year fraction `0.5`.

97.5% descriptive intervals: `{'net_bps': [-117.17266359082237, 517.4340842572049], 'excess_lower_bps': [-50.66819766622574, 364.9893254100358]}`.

500 weekly randomized complete-entry-qualifier controls tail `0.048`; independent cash/admission/durations and original current-close<EMA30 exits. Controls replace the entire delayed entry qualifier and retain the original separate current EMA exit. Seven-bar lag `{'conservative_limit': [{'admitted': 490, 'completed': 487, 'censored_mtm': 3, 'mean_net_bps': 31.15146544110217, 'median_net_bps': -79.77618901268636, 'mean_completed_only_net_bps': 27.182306336048953, 'per_unit_profit_factor': 1.2028150046540187, 'cash_profit_factor_with_cutoff_marks': 1.0488644687820952, 'completed_cash_profit_factor': 1.0540974323313845, 'win_fraction': 0.3448979591836735, 'mean_gross_bps': 71.35648133465368, 'mean_btc_excess_lower_bps': 44.207454836719215, 'mean_btc_excess_upper_bps': 44.207454836719215, 'mean_mfe_lower_bps': 525.6267395111374, 'mean_mfe_upper_bps': 525.6267395111374, 'mean_mae_lower_bps': -257.1750391195894, 'mean_mae_upper_bps': -257.1750391195894}], 'opening_price_improvement': [{'admitted': 490, 'completed': 487, 'censored_mtm': 3, 'mean_net_bps': 31.15146544110217, 'median_net_bps': -79.77618901268636, 'mean_completed_only_net_bps': 27.182306336048953, 'per_unit_profit_factor': 1.2028150046540187, 'cash_profit_factor_with_cutoff_marks': 1.0488644687820952, 'completed_cash_profit_factor': 1.0540974323313845, 'win_fraction': 0.3448979591836735, 'mean_gross_bps': 71.35648133465368, 'mean_btc_excess_lower_bps': 44.207454836719215, 'mean_btc_excess_upper_bps': 44.207454836719215, 'mean_mfe_lower_bps': 525.6267395111374, 'mean_mfe_upper_bps': 525.6267395111374, 'mean_mae_lower_bps': -257.1750391195894, 'mean_mae_upper_bps': -257.1750391195894}]}`.

Symbol/year/month/weekday/hour, UTC session memberships/overlap, BTC state, MFE/MAE, leave-week/symbol, all cost/gap and cash histories are retained in full and compact artifacts. Cutoff marks are not completed trades. Both gap labels coincide because no protective orders exist. Bootstrap uses2000 moving4-calendar-week blocks including zeros. Fixedalpha.025 is descriptive carryover, not global repeated-search adjustment.

## Audit and trial accounting

Four exact baseline reproductions; 948 independently reconstructed event records and 129528 NAV values, maximum residual 0.0. Stored control tail arithmetic and gate/calendar/portfolio checks are separate from a full independent500path replay, which is not claimed.

Independent audit `4fb10235f9885fd6ee7d8686cddd039f7d84bc0f2e2824e966a513853724a1de`; limits remain in that report.1144 mandatory tests and18 new tests pass; Ruff passes.14 frozen and202 prior paths rehashed. New cell brings minimum27 trading/28 signal-model attempts. Earlier rejected versions remain closed. Historical survival would only permit a separate future-only preregistration; viability requires passing that future confirmation.

Raw `4872532a3d954f3424a00090ec822fced453246dcba9563e56a2b454f7c78f46` (19174899bytes); lossless gzip `a6f3dd3ba36df46f2bb28c38a400a75eac8950693f0908e913df822c4672fb00` (1835051bytes).

## Rerun

Pinned Python3.13.14/NumPy2.2.4/pandas2.2.3/SciPy1.15.2/win32 and exact raw archives/config/audits required. Choose a new output path.

```powershell
$env:PYTHONPATH='src'
python -m orderflow_edge_lab.public_keltner_batch14 --raw ../../outputs/Minute-continuous-source-data --cache ../protective_batch5_cache --output ../../outputs/Keltner-batch14-rerun.json
```

## Cash weighting and symbol diagnostics

Per-unit returns average entry-normalized ratios. Cash PnL weights actual one-unit entry notionals, which vary by symbol and price over time. Positive average per-unit return and PF therefore do not establish positive funded return. The funded portfolio lost0.365183% in this fixed model; cash PF is0.982784 including cutoff marks and0.981589 completed-only. These are additional economic diagnostics; the frozen rejection gates remain exactly the two confidence intervals and positive-year fraction.

| Symbol | Completed / cutoff | Mean net40 bps | Per-unit PF | Cash PF with cutoff |
|---|---:|---:|---:|---:|
| ETHUSDT | 80 / 0 | 30.113761 | 1.111332 | 0.969748 |
| LINKUSDT | 82 / 1 | 96.279939 | 1.299929 | 0.996738 |
| SOLUSDT | 73 / 1 | 316.514057 | 2.069069 | 1.240100 |
