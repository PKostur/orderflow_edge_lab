# PSR4: BTC-relative strength — rejected as specified

## Definition and provenance

The design was committed at `a79816e74505a577a4f77ad51684dc430aff917f` before predictor outcomes were calculated. Implementation commit `34092f8b097f615ff12b8857416f125c7ff24f29` was clean at the recorded run. The existing public study ledger is extended separately; no prospective registry, frozen strategy, payoff geometry or session watch is changed. Bollinger Bands are excluded.

This is **spent-data development evidence**. Chronological held-forward predictions establish causal evaluation mechanics, not genuinely unseen OOS evidence. No live order path, paper-account mutation, promotion or prospective watch is added.

The retained Binance Spot source has 6,726 aligned 8h candles per symbol, BTCUSDT/ETHUSDT/SOLUSDT/LINKUSDT, from **2020-08-11 00:00 UTC through 2026-09-30 16:00 UTC**. No new candles were fetched. Raw and aligned CSV bytes are checked against the retained provenance manifest. The legacy manifest itself permits only Git's LF/CRLF text transport; both its working-file hash and design Git-blob hash are recorded. New output bytes are preserved across platforms using scoped Git attributes.

At Monday 00:00 UTC, use 91 completed UTC daily closes to obtain 90 daily log returns. Estimate a 90-day OLS beta with an intercept, then calculate alt 30-day log return minus that beta times BTC 30-day log return. Do not subtract the daily intercept or clip beta. The target is the altcoin's arithmetic return minus BTC's, from Monday 08:00 open to the next Monday 08:00 open, in basis points.

The pooled baseline uses BTC 30-day return, beta and symbol dummies; the extended model adds exactly one strength input. Both use training-only StandardScaler and Ridge(alpha=1, fit_intercept=True, solver='svd'). Each forecast fits 104 earlier weeks; the immediately preceding week's label is unavailable until Monday 08:00 and is excluded. No feature, threshold or model search was conducted.

There are **603 forecasts across 201 shared weeks**, November 21, 2022 through September 21, 2026, with final target exit **September 28, 2026 at 08:00 UTC**. The source offers 306 eligible weekly snapshots before the training/gap requirement. Each primary forecast has 312 training rows. The delayed control has 600 forecasts over 200 weeks because its first training row lacks a prior eligible strength input; no imputation or primary-cohort trimming is performed.

## Prediction results

Positive MSE reduction means improvement against the BTC-context baseline. Negative means worse forecasts.

| Evaluation | Forecasts | MSE reduction |
|---|---:|---:|
| Overall | 603 | **-1.09807%** |
| ETH | 201 | -1.25596% |
| SOL | 201 | -1.03233% |
| LINK | 201 | -1.13057% |
| 2022 partial | 18 | -3.72926% |
| 2023 | 156 | -0.81209% |
| 2024 | 159 | +0.41188% |
| 2025 | 156 | -3.03563% |
| 2026 partial | 114 | -0.46561% |

Baseline MSE is **728,058.777377 bps²**; extended MSE is **736,053.354270 bps²**. Baseline MAE is **574.194333 bps**; extended MAE is **577.968494 bps**. Relative-direction accuracy is **48.7562%**, versus baseline **48.9221%** and always-positive **44.1128%**. Extended calibration slope is **-0.539025**, intercept **51.509248 bps**. These secondary metrics do not replace the declared primary endpoint.

The 2,000-replicate circular four-week shared-symbol bootstrap gives a descriptive **99% MSE-reduction interval [-3.81585%, +0.90061%]**, seed 20261010. Every leave-week result remains negative, range **[-1.38016%, -0.76380%]**. Leave-year results range **[-1.65646%, -0.42597%]**; leave-symbol results range **[-1.16853%, -1.07105%]**. These are development robustness checks, not corrected significance claims.

Five of seven gates fail: the 1% improvement hurdle, positive bootstrap lower bound, improvement for every symbol, improvement in two of the three complete years, and positive leave-year results. The minimum-week and three-symbol gates pass.

## Controls and economics

The delayed-strength model worsens MSE by **1.32125%** against its matched 600-row baseline. Its relative-direction accuracy of 50.8333% does not rescue the failed primary endpoint.

The 500 within-year four-week block placebos shuffle extended-minus-baseline forecast contributions with a shared mapping across symbols. Mean MSE reduction is **-0.90820%**, descriptive 95% range **[-2.60069%, +0.80833%]**. **57.8%** perform at least as well as the actual feature. Incomplete year-end block tails remain fixed (2022:2 weeks, 2023:0, 2024:1, 2025:0, 2026:2). This is a descriptive control frequency, not a formal p-value.

**Economics: NOT_RUN.** No candidate trades were evaluated, no capital/PnL/MFE/MAE or cost-stress results were calculated, and no new trading cell was spent. `trade_count` is null rather than a fabricated zero-trade strategy result. Prediction targets use hypothetical next-open price windows; they are not a trade ledger.

The implemented conditional evaluator is tested on synthetic data. Only a passing state screen would run the one strictly-greater-than-80bps, seven-day, long-only Spot candidate. It uses three equal initial sleeves, cash at zero, no redistribution, weekly close/reentry, multiplicative half-cost at each fill and 20/30/40/60/80bps round-trip stress. Growth and benchmark advantage at 60bps are mandatory. Portfolio drawdown is sampled at 8h opens/post-fill equity; MFE/MAE exclude exit candles and cannot resolve intrabar order. These costs are assumptions, not actual historical execution calibration.

## Reproduce and inspect

Use a checkout containing the design commit (fetch full history if the checkout is shallow), install the existing research requirements, then choose a new output directory:

```powershell
python -m orderflow_edge_lab.btc_relative_state --spec config/public_btc_relative_state_v1.json --design-commit a79816e74505a577a4f77ad51684dc430aff917f --output-dir runs/psr4-rerun
python scripts/verify_public_btc_relative.py --artifact-dir artifacts/public_btc_relative_state_20261010 --output runs/psr4-independent.json
```

Recorded artifacts are under `artifacts/public_btc_relative_state_20261010`: report, all forecasts, all fitted training windows/scaler statistics/model coefficients and independent reconciliation. A second complete run reproduced forecasts and model artifacts byte-for-byte and the report's results exactly; only the disclosed worktree-dirty flag differed. Output files are exclusively created rather than overwritten.

Independent reconciliation imports neither the study module nor sklearn. It rebuilds calendar features and targets from CSV, selects training labels by completion timestamps and solves ridge normal equations directly. All 603 forecasts reconcile within 1e-6: maximum feature discrepancy 3.56e-15, target discrepancy 4.55e-13 bps and prediction discrepancy 5.58e-12 bps.

Tests cover known-beta/intercept semantics, invalid/zero-variance inputs, future-price invariance, missing grids, unavailable labels, training-only scaling, conditional rejection, null/noise controls, shared-week placebos, exclusive output, source/config provenance, exit-candle exclusion and multiplicative cash/close-reentry/BTC-schedule accounting. Frozen-manifest files have no changes from base main `6395ededb7bec6e1080c2bf993484630efee31a0`.

## Decision and next step

**REJECTED_AS_SPECIFIED.** Retuning this identifier is prohibited. Prior strategy and monthly-momentum rejections remain intact. One predictor hypothesis, baseline/extended/delayed model definitions and 500 noncandidate placebos are logged separately from trading cells; the prior minimum cumulative signal-cell count remains ten. This is not a complete selection history or a family-wise correction.

Close this definition. Review a distinct falsifiable market-state question and its evidence requirements before committing another identifier or gathering data. There is no survivor to replicate or prospective protocol to open.
