# Public Force Index state batch 12 results

This is a frozen eight-hour Spot mathematical execution adaptation of an educational public signal and illustrative accounting example. Native exchange or deployed bot parity is not claimed. These historical data are development evidence. Viability requires separately frozen untouched future confirmation.

Baseline main `8267c6cde0d54476684525f10419c4e6da732282`; design `5b3485fed53118c661bbf51a637cce4bf3bbe73f`; execution revision `4148cc37d39ea569e044913b65b9d4b4b087ca68`; evaluator SHA256 `2af8543d6ef01e75c53b275e3087e25b53f10f3b60a9a6ee54dc11a1afa94eb8`.

## Source and execution

[Pinned source](https://github.com/cinar/indicatorts/blob/c6bfb623b2ccbac2c536d60740e8c458e4efa7cd/examples/volume/forceIndexStrategy.ts), MIT copyright 2022–2026 The Indicator Authors. Raw current close change times current base-asset volume; first prior=self gives raw0. EMA13 alpha2/14, beta1-alpha, firstseed0, exact currentRaw*alpha+previousEMA*beta. BUY every FI>0, SELL every FI<0, HOLD equality. Zero-volume raw0 decays EMA rather than forcing HOLD. No crossing, threshold or normalization changes. Fixed full-history anchor2023-04-01T00Z; no rolling240/admission/day/year reset. Eight-hour FI is not aggregation of minuteFI. Original TypeScript source calculations/actions independently executed on8,985synthetic rows; source math is not native deployedbot parity. Constant volume degenerates to scaled EMA13 close-difference momentum; prior trend/volume overlap disclosed, no incremental-volume or orthogonality claim.

Explicit adaptation: three independent 10,000 USDT sleeves; full-balance source intent with fee reserve. Quantity is Decimal(str(cash/(signal_close*(1+sidecost)))) floored to eight places, fixed at the completed signal. Next-minute open execution is all-or-reject: no resize, borrowing, short, pyramid, partial fill or orders. SELL closes an existing long at the next open. Held BUY flags counted before exit; no same-boundary re-entry. No source stop, target, trailing or timeout. A randomized BUY may enter while flat on a SELL boundary because SELL closes only already-held positions. Funded BTC has its own cash, quantity and costs. Final inventory is CENSORED_MTM, not a completed trade; queued final exits remain pending. Drawdown is sampled at eight-hour closes.

## Audited data

Binance Spot BTCUSDT, ETHUSDT, SOLUSDT, LINKUSDT: 2023-04-01 through 2026-09-30 inclusive; 1,841,760 minutes / 3,837 eight-hour bars each. First eligible entry 2023-06-20T00:00Z after 240 closed bars. BTC comparison; three altcoin sleeves. Quality-selected common continuous segment, no repairs or imputation, no 2022 bear-market coverage.

## Frozen screening result

| Candidate | Completed / cutoff | Net40 / net80 bps | PF40 | ROI40 / DD40 | Control tail | Decision |
|---|---:|---:|---:|---:|---:|---|
| ForceIndex8hCashSourceIntent | 584 / 1 | 40.218507 / 0.137474 | 1.195684 | 63.782497% / -62.375418% | 0.346000 | REJECTED_AS_ADAPTED |

Failed gates: all_symbols_positive, excess_descriptive_ci, net_descriptive_ci, placebo_tail, portfolio_drawdown.

Entry weeks: 162. Calendar weeks including zeros: 172. Descriptive 97.5% intervals: `{'net_bps': [-68.67376042037272, 173.77700405990038], 'excess_lower_bps': [-20.47012999510612, 127.34408342847661]}`. Worst leave-week mean: 9.541110 bps. Positive year fraction: 75.00%.

| Symbol | Admitted / completed / cutoff | Net40 bps | Admission counts |
|---|---:|---:|---|
| ETHUSDT | 203 / 203 / 0 | -8.244784 | `{'raw_entry_flags': 1732, 'accepted_entries': 203, 'held_entry_ignored': 1468, 'cash_rejected': 61}` |
| SOLUSDT | 196 / 196 / 0 | 109.402487 | `{'raw_entry_flags': 1839, 'accepted_entries': 196, 'held_entry_ignored': 1572, 'cash_rejected': 71}` |
| LINKUSDT | 186 / 185 / 1 | 20.207690 | `{'raw_entry_flags': 1772, 'accepted_entries': 186, 'held_entry_ignored': 1500, 'cash_rejected': 86}` |

Seven-bar lag: `{'conservative_limit': [{'admitted': 1049, 'completed': 1047, 'censored_mtm': 2, 'mean_net_bps': 4.79223679942228, 'median_net_bps': -49.33676676900256, 'mean_completed_only_net_bps': 4.081102483227492, 'per_unit_profit_factor': 1.0373060418027973, 'cash_profit_factor_with_cutoff_marks': 0.9985507395683993, 'completed_cash_profit_factor': 0.998115649844655, 'win_fraction': 0.36415633937082936, 'mean_gross_bps': 44.89160448198511, 'mean_btc_excess_lower_bps': 23.499621023312667, 'mean_btc_excess_upper_bps': 23.499621023312667, 'mean_mfe_lower_bps': 373.9188867678366, 'mean_mfe_upper_bps': 373.9188867678366, 'mean_mae_lower_bps': -217.03082976186488, 'mean_mae_upper_bps': -217.03082976186488}], 'opening_price_improvement': [{'admitted': 1049, 'completed': 1047, 'censored_mtm': 2, 'mean_net_bps': 4.79223679942228, 'median_net_bps': -49.33676676900256, 'mean_completed_only_net_bps': 4.081102483227492, 'per_unit_profit_factor': 1.0373060418027973, 'cash_profit_factor_with_cutoff_marks': 0.9985507395683993, 'completed_cash_profit_factor': 0.998115649844655, 'win_fraction': 0.36415633937082936, 'mean_gross_bps': 44.89160448198511, 'mean_btc_excess_lower_bps': 23.499621023312667, 'mean_btc_excess_upper_bps': 23.499621023312667, 'mean_mfe_lower_bps': 373.9188867678366, 'mean_mfe_upper_bps': 373.9188867678366, 'mean_mae_lower_bps': -217.03082976186488, 'mean_mae_upper_bps': -217.03082976186488}]}`.

20/40/60/80 nominal round-trip bps are split across actual entry/exit notionals. Both registered gap labels are identical because there are no protective prices. All return, MFE/MAE, session membership/overlap, symbol/calendar/year/weekday/hour, BTC state, leave-out and funded cash diagnostics are retained. 500 entry-week flag randomizations rerun their own quantities, admission, duration and original SELL-state exits. No observed endogenous duration is reused. 2,000 moving four-calendar-week blocks include zero-event weeks. Fixed alpha 0.025 is a conservative descriptive carryover for one cell, not a global repeated-search correction.

## Returns, excursions and portfolio accounting

Gross mean 80.459864 bps; median net -154.774241 bps; completed-only mean 38.877293 bps; win fraction 25.13%. Mean MFE 663.083254 bps and MAE -294.240941 bps (both bounds identical for these no-protection paths). Same-exit BTC excess 45.347943 bps.

Cash profit factor with cutoff marks 1.077851; completed-only cash PF 1.075143. Funded BTC return -21.131185%. Per-unit PF and arithmetic event means differ from cash-weighted realized portfolio outcomes.

Entry clock/session diagnostics: `{'n': 585, 'utc_hour_counts': {'0': 194, '8': 191, '16': 200}, 'nonexclusive_session_counts': {'Asia': 385, 'London': 191, 'New_York': 200}, 'exclusive_membership_counts': {'Asia': 194, 'Asia+London': 191, 'New_York': 200}}`. Full symbol, calendar-year, weekday, UTC hour, overlapping sessions, BTC-state, leave-symbol and leave-week groups retained in the result summary and lossless archive.

## Verification and decision boundary

1,109 mandatory tests (15 new) and Ruff passed. Source/config/Git-bound independent review was committed before any raw market load; missing-review cold probe blocked before output/cache creation. Final four-baseline reproduction and separate event/cash/BTC/NAV reconstruction are retained; no native bot execution or independent full 500-control rerun is claimed.

Fourteen frozen paths and 139 previous definitions/artifacts remain byte-identical. DON8, EMA8, VOL8, DV2, D4, payoff geometry, session watches and frozen prospective protocols are preserved. Bollinger excluded; no order path added. Minimum attempted cells: 25 trading /26 signal-model. Related controls/cost/gap versions are not independent trials.

Any historical survivor only permits a separately frozen, adequately powered future confirmation with calibrated execution/costs, controls and paper reliability. A rejection stays closed; no sizing, threshold, pair, date, exit, cost or gate changes rescue this version. No candidate is viable before untouched future confirmation passes.

Full results SHA256 `be866b58c6bdd51ee990cb89532f926b035c93ed0d13268e8e03110568c021d1` (26222332 bytes); lossless gzip SHA256 `26e443122c893823e7caa57640022adb4e82a83622079ba245acf9a01830cc39` (3196907 bytes). Complete baseline paths/events retained. Control means plus seed and lag summaries retained; full control paths reproducible but not stored.

## Rerun

Pinned Windows Python 3.13.14 / NumPy 2.2.4 / pandas 2.2.3, exact registrations and raw archives/receipts required. Choose a new output path.

```powershell
$env:PYTHONPATH='src'
python -m orderflow_edge_lab.public_force_index_batch12 --raw ../../outputs/Minute-continuous-source-data --cache ../protective_batch5_cache --output ../../outputs/ForceIndex-batch12-rerun.json
```
