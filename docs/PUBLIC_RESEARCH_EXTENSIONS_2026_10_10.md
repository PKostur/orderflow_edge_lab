# Public research extensions: volume state and minute feasibility

## Definitions and boundaries

The two independent study definitions were committed before outcome calculation or archive retrieval at `2d97c880ed34c46bf21a12204edbf43a0201fa3b`. Implementation commit `fee7520d856c483c3d36a7771a9051d25ff59beb` produced the volume result; `18d1be2bd12ad292f6cc7b3bd900cd246d0ebdfb` parallelized independent archive transfers before the completed minute audit. Neither introduces a trading rule, account mutation, prospective watch or promotion. All earlier public rejections remain closed. Frozen DON8/EMA8/VOL8/DV2/D4, payoff geometry and session/prospective protocols are unchanged. Bollinger Bands are excluded.

The CLI has two explicit lanes, `volume` and `minute`, with a byte-bound specification/design commit and exclusive output directories. Retained source raw/CSV hashes are checked; newly retrieved archive ZIP and official CHECKSUM bytes, URLs, request and actual receipt times are recorded. Invalid or incomplete data fail closed. Parallel downloads use four independent symbol paths, fixed aggregation order and no symbol/date substitution. A partial preliminary sequential transfer was stopped for download efficiency and retained outside the repository; it is not the completed study evidence.

## PSR5: volume to future volatility

This is spent-data development prediction, not genuinely unseen OOS and not a repeat of the rejected volume-impulse return strategy. The question is whether prior completed volume adds information about future volatility beyond volatility persistence and BTC context.

Retained Binance Spot BTC/ETH/SOL/LINK has **6,726 aligned 8h candles per symbol**, August 11, 2020 00:00 UTC through September 30, 2026 16:00 UTC. No new 8h prices were fetched.

Forecast daily at 00:00 UTC. Baseline inputs are log prior-day, seven-day-mean and thirty-day-mean volatility proxies, prior BTC proxy and symbol identity. The incremental input is log prior-day turnover proxy relative to the preceding30-day mean, including that day. Turnover is typical price times base volume, not actual quote turnover. The future target is log(sum of three squared candle close/open log returns + 1e-12), from 08:00 through the following08:00. This coarse proxy omits gaps and within-candle paths and must not be called tick realized variance.

Fit StandardScaler only on the rolling730-day training cohort, then fixed Ridge(alpha=1,intercept=True,solver='svd'). Exclude the immediately preceding day because its target completes08:00 after the current00:00 forecast. Models pool symbol-day rows equally. No threshold/feature/horizon search occurs.

There are **4,440 forecasts over1,480 days and213 shared calendar-week clusters**, September11,2022 through September29,2026; final target ends September30,2026 at08:00 UTC. Each fit uses2,190 training rows. The delayed-volume control omits its first three forecast rows because its first training row has no earlier eligible feature; no imputation or main-cohort trimming is performed.

| Cohort | Forecasts | MSE reduction versus persistence/BTC baseline |
|---|---:|---:|
| Overall | 4,440 | **+0.36810%** |
| ETH | 1,480 | -0.20716% |
| SOL | 1,480 | +0.70394% |
| LINK | 1,480 | +0.78209% |
| 2022 partial | 336 | +2.54268% |
| 2023 | 1,095 | +0.70596% |
| 2024 | 1,098 | +0.41200% |
| 2025 | 1,095 | -0.51749% |
| 2026 partial | 816 | -0.08171% |

Baseline/extended MSE is **1.745296/1.738872 log-proxy units squared**, MAE **1.026536/1.025141 log-proxy units**. The descriptive99% circular four-week bootstrap interval for MSE reduction is **[-0.59857%,+1.26698%]**, 2,000 draws, seed20261010. Leave-week range is **[+0.30250%,+0.45451%]**, leave-year range **[+0.16469%,+0.63153%]**.

The delayed control has4,437 forecasts and **+0.12727%** improvement. The500 within-year28-day contribution-permutation controls have mean **-1.05861%**, descriptive95% range **[-1.60238%,-0.47357%]**; none performs at least as well as the actual feature. This is a descriptive control frequency, not a corrected p-value. Shared mappings keep symbols together; short year tails stay fixed.

**REJECTED_AS_SPECIFIED.** Three of six gates fail: the1% improvement hurdle, positive99% lower bound, and improvement for every symbol. The sample-size, two-complete-year and leave-year gates pass. Stronger performance than placebos does not override the failed gates. No retuning under this identifier is permitted.

**Economics NOT_DESIGNED_NOT_RUN.** There is no directional rule or executed trade cell, and trade count is null. Even a passing volatility predictor would need a separate committed economic application before any trading assessment. The user's growth-and-benchmark requirement has not been weakened or replaced with a volatility metric.

## PSR6: minute BTC lead–lag feasibility

The fixed same-symbol panel is an adaptation of a published one-minute price-transmission question, **not** a replication of the paper's low-trade-count small-cap universe or its selected event windows. January1 and July1 in2021–2026 were chosen in the design before retrieval. Twelve sparse days cannot establish continuous multiyear coverage, out-of-sample prediction or an executable edge.

The collector requests48 official Binance Spot daily1m ZIPs with48 CHECKSUMs, requiring1440 continuous minutes in each file. Millisecond timestamps before2025 and microsecond timestamps from2025 are explicitly validated and normalized. Every day requires the same four-symbol grid. Per-day diagnostics compare BTC/alt contemporaneous close returns with BTC-leading-one-minute correlation without crossing day boundaries; they are observational, with no significance or promotion gate. Absolute one-minute move distributions are compared with a60bps cost assumption only as a scale check, not expected profits.

Current20-level public books are walked for a hypothetical1,000USDT buy/sell round trip. Both sides must have sufficient depth; duplicate, unsorted or crossed levels reject the snapshot. Raw book bytes, request duration and local receipt age at assessment are recorded. Exchange feed age, historical slippage, account fees and latency are unverified. A current book walk cannot establish historical execution readiness.

Completed archive counts, observations, cost scales and dispositions are recorded in the minute result artifact and the final delivery report. Source-access feasibility alone does not authorize a strategy backtest or deployment. Any incomplete archive panel withholds all panel lead diagnostics; unavailable book information is separately labeled.

All **48 archives and48 CHECKSUMs passed**, retaining69,120 candles across12 fixed UTC days, January1,2021 through July1,2026. There are36 alt/date diagnostics, each with1,439 within-day returns and1,438 BTC-leading-one-minute pairs. No archive, gap, checksum or timestamp-unit failure occurred. Raw archives/checksums/books occupy2,968,725 bytes.

The following are **medians of twelve per-day diagnostics**, not correlations estimated after concatenating separated dates:

| Symbol | Contemporaneous correlation | BTC leads1minute correlation | Median daily95th-percentile absolute move |
|---|---:|---:|---:|
| ETH | 0.778305 | -0.000921 | 10.96865bps |
| SOL | 0.703010 | 0.014133 | 21.02230bps |
| LINK | 0.544867 | 0.020208 | 16.95778bps |

Across equally sized sample days, fractions of absolute moves above60bps are ETH0.09266%, SOL0.79917%, LINK0.22585%. Magnitude alone is not forecastable profit. The observed one-minute lead correlations are small relative to contemporaneous correlations; this descriptive observation is not a declared significance test or a full-history rejection.

All four current book snapshots had enough displayed depth for the fixed1,000USDT walk. Round-trip losses excluding fees were BTC0.001205bps, ETH0.039906bps, SOL0.907029bps, LINK1.299052bps. Receipts were October10,2026 16:33:20–16:33:21 UTC; local receipt ages at common assessment ranged0.002564–1.164048seconds, request durations0.380347–0.520859seconds. Exchange feed age is unavailable. These are hypothetical displayed-depth walks, not orders or verified fills.

**SOURCE_ACCESS_FEASIBLE_EXECUTION_AND_PREDICTION_UNCONFIRMED.** Data access passes; predictive and economic survival remain unestablished. Trade count is null and no trading cell was executed. There is no evidence-supported candidate to freeze. A further minute study would first need a separately committed continuous-sample/power and historical execution design; do not mine a lag, asset or threshold from these diagnostics.

## Reproduce

Install the existing research dependencies and use a checkout containing the immutable design commit. Choose new output directories; existing files are never overwritten.

```powershell
python -m orderflow_edge_lab.public_research_extensions --lane volume --spec config/public_research_extensions_v1.json --design-commit 2d97c880ed34c46bf21a12204edbf43a0201fa3b --output-dir runs/psr5-rerun
python -m orderflow_edge_lab.public_research_extensions --lane minute --spec config/public_research_extensions_v1.json --design-commit 2d97c880ed34c46bf21a12204edbf43a0201fa3b --output-dir runs/psr6-new-retrieval
```

Volume forecasts, all training windows/scaler statistics/model coefficients and result JSON are retained under `artifacts/public_research_extensions_20261010/volume`. A second run reproduced all three files byte-for-byte. Minute retrieval receipts/current books naturally change on rerun; archive content must pass its newly supplied checksum and be labeled as a new retrieval. Outputs are preserved across platform checkouts using scoped Git attributes.

Tests cover future-price/volume isolation, exact target and training clocks, training-only scaling, missing-grid/zero-turnover rejection, millisecond/microsecond conversion, complete minute grids, malformed checksum/name/content rejection, duplicate/crossed books, insufficient depth on either side and null-feature rejection without trading. Specialist review corrected audit timestamp/checksum/depth issues before the completed runs. The deterministic release-manager report is a separate engineering gate, not evidence of a profitable model.

## References

- [Andersen (1996), Return Volatility and Trading Volume](https://www.kellogg.northwestern.edu/academics-research/research/detail/1996/return-volatility-and-trading-volume-an-information-flow-interpretation/): motivates investigating information/volume/volatility relationships; does not validate this crypto predictor.
- [Kurihara and Matsumoto (2026), Price Transmission from Bitcoin to Altcoins](https://link.springer.com/article/10.1007/s10690-026-09589-z): motivates minute-scale source/execution assessment; its reported returns do not establish results for our panel.
- [Binance public-data documentation](https://github.com/binance/binance-public-data): archive layout, official checksums and the2025 timestamp-unit transition.
