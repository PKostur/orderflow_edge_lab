# Public NVI state batch 11 results

This is a frozen eight-hour Spot mathematical execution adaptation of an educational public signal and illustrative accounting example. Native exchange or deployed bot parity is not claimed. These historical data are development evidence. Viability requires separately frozen untouched future confirmation.

Baseline main `1acd163b7c6eb3c38b265aa661c85f4eef0e4da8`; design `bf690091c2d738fe48dfca7dbcfe699f61ecb146`; execution revision `0e3327a6da2b13ccf767bfe430b6b00bc84993a7`; evaluator SHA256 `834ed11157d9679efc8a9b10397a4d9be313e5d3cf3b4a53197fb7298054a564`.

## Source and execution

[Pinned source](https://github.com/cinar/indicatorts/blob/c6bfb623b2ccbac2c536d60740e8c458e4efa7cd/examples/volume/negativeVolumeIndexStrategy.ts), MIT copyright 2022–2026 The Indicator Authors. NVI starts at 1000 and updates for falling or equal base-asset volume; strictly rising volume freezes it. EMA period 255 uses alpha 2/256 and the first NVI as seed. BUY every NVI<EMA, SELL every NVI>EMA, HOLD equality; published direction unchanged. Initialize once at 2023-04-01T00Z and carry all history through warmup, with no rolling-window or admission/day/year reset. Period 255 is unused by NVI itself. Binance volume is the sum of the complete constituent minute base-asset volumes. Original TypeScript math/actions independently executed on 8,985 synthetic rows; this is source-math evidence, not native bot execution parity.

Explicit adaptation: three independent 10,000 USDT sleeves; full-balance source intent with fee reserve. Quantity is Decimal(str(cash/(signal_close*(1+sidecost)))) floored to eight places, fixed at the completed signal. Next-minute open execution is all-or-reject: no resize, borrowing, short, pyramid, partial fill or orders. SELL closes an existing long at the next open. Held BUY flags counted before exit; no same-boundary re-entry. No source stop, target, trailing or timeout. A randomized BUY may enter while flat on a SELL boundary because SELL closes only already-held positions. Funded BTC has its own cash, quantity and costs. Final inventory is CENSORED_MTM, not a completed trade; queued final exits remain pending. Drawdown is sampled at eight-hour closes.

## Audited data

Binance Spot BTCUSDT, ETHUSDT, SOLUSDT, LINKUSDT: 2023-04-01 through 2026-09-30 inclusive; 1,841,760 minutes / 3,837 eight-hour bars each. First eligible entry 2023-06-20T00:00Z after 240 closed bars. BTC comparison; three altcoin sleeves. Quality-selected common continuous segment, no repairs or imputation, no 2022 bear-market coverage.

## Frozen screening result

| Candidate | Completed / cutoff | Net40 / net80 bps | PF40 | ROI40 / DD40 | Control tail | Decision |
|---|---:|---:|---:|---:|---:|---|
| NegativeVolumeIndex8hCashSourceIntent | 127 / 2 | 57.909192 / 17.757538 | 1.219489 | 2.892278% / -60.060766% | 0.000000 | REJECTED_AS_ADAPTED |

Failed gates: excess_descriptive_ci, net_descriptive_ci, portfolio_drawdown.

Entry weeks: 70. Calendar weeks including zeros: 172. Descriptive 97.5% intervals: `{'net_bps': [-180.64399954258403, 299.24328219352884], 'excess_lower_bps': [-136.5704985990278, 132.8215122188594]}`. Worst leave-week mean: 23.849857 bps. Positive year fraction: 75.00%.

| Symbol | Admitted / completed / cutoff | Net40 bps | Admission counts |
|---|---:|---:|---|
| ETHUSDT | 34 / 33 / 1 | 61.230260 | `{'raw_entry_flags': 797, 'cash_rejected': 18, 'accepted_entries': 34, 'held_entry_ignored': 745}` |
| SOLUSDT | 35 / 35 / 0 | 46.601095 | `{'raw_entry_flags': 783, 'accepted_entries': 35, 'held_entry_ignored': 736, 'cash_rejected': 12}` |
| LINKUSDT | 60 / 59 / 1 | 62.623644 | `{'raw_entry_flags': 1721, 'accepted_entries': 60, 'held_entry_ignored': 1630, 'cash_rejected': 31}` |

Seven-bar lag: `{'conservative_limit': [{'admitted': 239, 'completed': 237, 'censored_mtm': 2, 'mean_net_bps': 48.28637166389104, 'median_net_bps': 3.2905988456910507, 'mean_completed_only_net_bps': 46.15145370688785, 'per_unit_profit_factor': 1.3140961080608848, 'cash_profit_factor_with_cutoff_marks': 1.147406879005191, 'completed_cash_profit_factor': 1.1262226260086545, 'win_fraction': 0.5062761506276151, 'mean_gross_bps': 88.56006453629145, 'mean_btc_excess_lower_bps': 23.571147942098186, 'mean_btc_excess_upper_bps': 23.571147942098186, 'mean_mfe_lower_bps': 394.8007619179519, 'mean_mfe_upper_bps': 394.8007619179519, 'mean_mae_lower_bps': -372.08818531304223, 'mean_mae_upper_bps': -372.08818531304223}], 'opening_price_improvement': [{'admitted': 239, 'completed': 237, 'censored_mtm': 2, 'mean_net_bps': 48.28637166389104, 'median_net_bps': 3.2905988456910507, 'mean_completed_only_net_bps': 46.15145370688785, 'per_unit_profit_factor': 1.3140961080608848, 'cash_profit_factor_with_cutoff_marks': 1.147406879005191, 'completed_cash_profit_factor': 1.1262226260086545, 'win_fraction': 0.5062761506276151, 'mean_gross_bps': 88.56006453629145, 'mean_btc_excess_lower_bps': 23.571147942098186, 'mean_btc_excess_upper_bps': 23.571147942098186, 'mean_mfe_lower_bps': 394.8007619179519, 'mean_mfe_upper_bps': 394.8007619179519, 'mean_mae_lower_bps': -372.08818531304223, 'mean_mae_upper_bps': -372.08818531304223}]}`.

20/40/60/80 nominal round-trip bps are split across actual entry/exit notionals. Both registered gap labels are identical because there are no protective prices. All return, MFE/MAE, session membership/overlap, symbol/calendar/year/weekday/hour, BTC state, leave-out and funded cash diagnostics are retained. 500 entry-week flag randomizations rerun their own quantities, admission, duration and original SELL-state exits. No observed endogenous duration is reused. 2,000 moving four-calendar-week blocks include zero-event weeks. Fixed alpha 0.025 is a conservative descriptive carryover for one cell, not a global repeated-search correction.

## Verification and decision boundary

1,094 mandatory tests (16 new) and Ruff passed. Source/config/Git-bound independent review was committed before any raw market load; missing-review cold probe blocked before output/cache creation. Final four-baseline reproduction and separate event/cash/BTC/NAV reconstruction are retained; no native bot execution or independent full 500-control rerun is claimed.

Fourteen frozen paths and 106 previous definitions/artifacts remain byte-identical. DON8, EMA8, VOL8, DV2, D4, payoff geometry, session watches and frozen prospective protocols are preserved. Bollinger excluded; no order path added. Minimum attempted cells: 24 trading /25 signal-model. Related controls/cost/gap versions are not independent trials.

Any historical survivor only permits a separately frozen, adequately powered future confirmation with calibrated execution/costs, controls and paper reliability. A rejection stays closed; no sizing, threshold, pair, date, exit, cost or gate changes rescue this version. No candidate is viable before untouched future confirmation passes.

Full results SHA256 `9d50a95f6cdccc7a5f5e090bf88aad44cf2a9c857cfc06a6126e046f9d92ae53` (16840299 bytes); lossless gzip SHA256 `383c89a203ac2da423e84b6c67f9a83c020950b8c83f8f006fb19237396e48ca` (1790743 bytes). Complete baseline paths/events retained. Control means plus seed and lag summaries retained; full control paths reproducible but not stored.

## Rerun

Pinned Windows Python 3.13.14 / NumPy 2.2.4 / pandas 2.2.3, exact registrations and raw archives/receipts required. Choose a new output path.

```powershell
$env:PYTHONPATH='src'
python -m orderflow_edge_lab.public_nvi_batch11 --raw ../../outputs/Minute-continuous-source-data --cache ../protective_batch5_cache --output ../../outputs/NVI-batch11-rerun.json
```
