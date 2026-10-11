# Public Vortex state batch 10 results

This is a frozen eight-hour Spot mathematical execution adaptation of an educational public signal and illustrative accounting example. Native exchange or deployed bot parity is not claimed. These historical data are development evidence. Viability requires separately frozen untouched future confirmation.

Baseline main `6d15dda71282622e9ee4903f6c15d9409f49b38f`; design `32902d2f8f8f251c4e23174a9ea49335aad3f169`; execution revision `284e99ce78a33b9207d019281eb68242997c0f1d`; evaluator SHA256 `3cbd3849d441609e6fd5f0adae95adcf3a796d792d7e7eb40d94a291f548a490`.

## Source and execution

[Pinned source](https://github.com/cinar/indicatorts/blob/c6bfb623b2ccbac2c536d60740e8c458e4efa7cd/examples/trend/vortexStrategy.ts), MIT copyright 2022–2026 The Indicator Authors. Period 14, partial inclusive rolling sums, first prior=self, and zero true-range lines set to zero. BUY every plus>minus state, SELL every plus<minus state, HOLD equality. No crossover requirement or UTC-day reset. Original TypeScript feature/action math and illustrative same-close cost-free gains independently checked on 6,703 synthetic rows.

Explicit adaptation: three independent 10,000 USDT sleeves; full-balance source intent with fee reserve. Quantity is Decimal(str(cash/(signal_close*(1+sidecost)))) floored to eight places, fixed at the completed signal. Next-minute open execution is all-or-reject: no resize, borrowing, short, pyramid, partial fill or orders. SELL closes an existing long at the next open. Held BUY flags counted before exit; no same-boundary re-entry. No source stop, target, trailing or timeout. A randomized BUY may enter while flat on a SELL boundary because SELL closes only already-held positions. Funded BTC has its own cash, quantity and costs. Final inventory is CENSORED_MTM, not a completed trade; queued final exits remain pending. Drawdown is sampled at eight-hour closes.

## Audited data

Binance Spot BTCUSDT, ETHUSDT, SOLUSDT, LINKUSDT: 2023-04-01 through 2026-09-30 inclusive; 1,841,760 minutes / 3,837 eight-hour bars each. First eligible entry 2023-06-20T00:00Z after 240 closed bars. BTC comparison; three altcoin sleeves. Quality-selected common continuous segment, no repairs or imputation, no 2022 bear-market coverage.

## Frozen screening result

| Candidate | Completed / cutoff | Net40 / net80 bps | PF40 | ROI40 / DD40 | Control tail | Decision |
|---|---:|---:|---:|---:|---:|---|
| VortexState8hCashSourceIntent | 509 / 1 | 32.040372 / -8.008013 | 1.136794 | 22.913443% / -70.379761% | 0.078000 | REJECTED_AS_ADAPTED |

Failed gates: all_symbols_positive, excess_descriptive_ci, net80_positive, net_descriptive_ci, placebo_tail, portfolio_drawdown, positive_year_fraction.

Entry weeks: 156. Calendar weeks including zeros: 172. Descriptive 97.5% intervals: `{'net_bps': [-93.90812034569713, 168.16872088149907], 'excess_lower_bps': [-40.690312990229366, 112.34284582664431]}`. Worst leave-week mean: 15.524890 bps. Positive year fraction: 50.00%.

| Symbol | Admitted / completed / cutoff | Net40 bps | Admission counts |
|---|---:|---:|---|
| ETHUSDT | 179 / 179 / 0 | -10.749789 | `{'raw_entry_flags': 1839, 'accepted_entries': 179, 'held_entry_ignored': 1585, 'cash_rejected': 75}` |
| SOLUSDT | 159 / 159 / 0 | 97.798143 | `{'raw_entry_flags': 1880, 'accepted_entries': 159, 'held_entry_ignored': 1677, 'cash_rejected': 44}` |
| LINKUSDT | 172 / 171 / 1 | 15.784287 | `{'raw_entry_flags': 1822, 'accepted_entries': 172, 'held_entry_ignored': 1573, 'cash_rejected': 77}` |

Seven-bar lag: `{'conservative_limit': [{'admitted': 1032, 'completed': 1031, 'censored_mtm': 1, 'mean_net_bps': -5.180526016378479, 'median_net_bps': -50.24192075389622, 'mean_completed_only_net_bps': -5.98427790304789, 'per_unit_profit_factor': 0.9623142672678819, 'cash_profit_factor_with_cutoff_marks': 0.9468940663618458, 'completed_cash_profit_factor': 0.9452124888779637, 'win_fraction': 0.37887596899224807, 'mean_gross_bps': 34.878870672934674, 'mean_btc_excess_lower_bps': 17.657943659730808, 'mean_btc_excess_upper_bps': 17.657943659730808, 'mean_mfe_lower_bps': 361.8217726442059, 'mean_mfe_upper_bps': 361.8217726442059, 'mean_mae_lower_bps': -239.2256689814318, 'mean_mae_upper_bps': -239.2256689814318}], 'opening_price_improvement': [{'admitted': 1032, 'completed': 1031, 'censored_mtm': 1, 'mean_net_bps': -5.180526016378479, 'median_net_bps': -50.24192075389622, 'mean_completed_only_net_bps': -5.98427790304789, 'per_unit_profit_factor': 0.9623142672678819, 'cash_profit_factor_with_cutoff_marks': 0.9468940663618458, 'completed_cash_profit_factor': 0.9452124888779637, 'win_fraction': 0.37887596899224807, 'mean_gross_bps': 34.878870672934674, 'mean_btc_excess_lower_bps': 17.657943659730808, 'mean_btc_excess_upper_bps': 17.657943659730808, 'mean_mfe_lower_bps': 361.8217726442059, 'mean_mfe_upper_bps': 361.8217726442059, 'mean_mae_lower_bps': -239.2256689814318, 'mean_mae_upper_bps': -239.2256689814318}]}`.

20/40/60/80 nominal round-trip bps are split across actual entry/exit notionals. Both registered gap labels are identical because there are no protective prices. All return, MFE/MAE, session membership/overlap, symbol/calendar/year/weekday/hour, BTC state, leave-out and funded cash diagnostics are retained. 500 entry-week flag randomizations rerun their own quantities, admission, duration and original SELL-state exits. No observed endogenous duration is reused. 2,000 moving four-calendar-week blocks include zero-event weeks. Fixed alpha 0.025 is a conservative descriptive carryover for one cell, not a global repeated-search correction.

## Verification and decision boundary

1,078 mandatory tests (13 new) and Ruff passed. Source/config/Git-bound independent review was committed before any raw market load; missing-review cold probe blocked before output/cache creation. Final four-baseline reproduction and separate event/cash/BTC/NAV reconstruction are retained; no native bot execution or independent full 500-control rerun is claimed.

Fourteen frozen paths and 83 previous definitions/artifacts remain byte-identical. DON8, EMA8, VOL8, DV2, D4, payoff geometry, session watches and frozen prospective protocols are preserved. Bollinger excluded; no order path added. Minimum attempted cells: 23 trading /24 signal-model. Related controls/cost/gap versions are not independent trials.

Any historical survivor only permits a separately frozen, adequately powered future confirmation with calibrated execution/costs, controls and paper reliability. A rejection stays closed; no sizing, threshold, pair, date, exit, cost or gate changes rescue this version. No candidate is viable before untouched future confirmation passes.

Full results SHA256 `57a61c2d27fd7698915e173d11d6ef18517cbf3f05f63ee99ee818bd6b7874d2` (24803720 bytes); lossless gzip SHA256 `e7a32f4e3367ba91db77c63aff4de33f3f7376cbf31f409827edaba63c8e3d2c` (3144755 bytes). Complete baseline paths/events retained. Control means plus seed and lag summaries retained; full control paths reproducible but not stored.

## Rerun

Pinned Windows Python 3.13.14 / NumPy 2.2.4 / pandas 2.2.3, exact registrations and raw archives/receipts required. Choose a new output path.

```powershell
$env:PYTHONPATH='src'
python -m orderflow_edge_lab.public_vortex_batch10 --raw ../../outputs/Minute-continuous-source-data --cache ../protective_batch5_cache --output ../../outputs/Vortex-batch10-rerun.json
```
