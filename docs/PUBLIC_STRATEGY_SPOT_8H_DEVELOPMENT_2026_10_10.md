# Public-strategy Spot 8h historical development review — 2026-10-10

**Decision:** PSV1-VOLUME-IMPULSE and PSV1-VWAP-REVERSION are rejected as specified. PSV1-FAILED-DOWNSIDE is **development-interesting but not ready**. No v2 candidate, prospective freeze, future T0, paper order, or live strategy is created. These are inspected historical outcomes, not untouched out-of-sample evidence. The three v1 definitions and all existing frozen research lanes remain unchanged.

## Source and exact first run

The source is Binance **Spot** public `GET /api/v3/klines`, `interval=8h`, UTC. Retrieval began `2026-10-10T08:30:24Z`. The collector preserved exact HTTP response page bytes in `artifacts/public_spot_8h_20261010/raw/`, derived aligned CSVs, and checked every 8h timestamp. Requested window: `[2020-01-01T00:00:00Z, 2026-10-01T00:00:00Z)`. BTC, ETH and LINK each returned 7,395 contiguous bars from 2020-01-01; SOL returned 6,726 from 2020-08-11. The common four-symbol grid is **6,726 bars, 2020-08-11T00:00:00Z through 2026-09-30T16:00:00Z**. There were **zero internal gaps** in each raw series or in the common grid; no forward fill. SOL's listing availability sets the common start. A separate connected Binance Spot tool returned two BTC bars at 2021-01-01 00:00 and 08:00 UTC matching the local CSV's six OHLCV fields, a spot check rather than authentication of every bar.

| Spot source | Raw response SHA256 | Aligned CSV SHA256 |
|---|---|---|
| BTCUSDT | `4168f20e9aff20710847ac31a93e46d5f058efd8ea620c28b026d9ee6e8d821f` | `96e25db1fd9882e6435d8b9a9bf23a716ccf0f004de46329f6db2bb47c054d82` |
| ETHUSDT | `edca258e5393ef7a7321d3e440fa4e83d3d0504792f153befe06a3d8f6b8924e` | `ccbce670762e32b6cd04a80502399a500f34cff856f1794c8bca68bab8858712` |
| SOLUSDT | `f5a24e9e026e719742c2254983f8bfa2a24562c2b5d826688398f7e18d910a5b` | `7b556ce71b1ae787c64baadc66f07aa3b6505f28ff4bad3d77cf7fd7024b7fc7` |
| LINKUSDT | `df66f12043a3aac8be892de166002dee6acaff0c70ade9f3414c39df977e18ab` | `d4bc5b454dec76812fd8358443c78ddf4d67eafc8e6d513d1d5267eb7599ddd2` |

The unchanged `config/public_strategy_shadow_v1.json` was run **before** the diagnostic code or perturbations. Its canonical specification SHA256 is `9d53b634175f6599561822d3de7db5aa5b1f04af1524a1f5d83dd8871ce8bbda`. The exact output is `artifacts/public_spot_8h_20261010/exact_v1_report.json`; the independent re-evaluation of each baseline matched its signal count, completed count and mean net bps. The later diagnostics are in `diagnostics_final.json`. Both preserve development-only and no-deployment flags.

## Exact v1 economics

All figures use next-bar-open entry, fixed next-open exit after the specified hold, and 20 bps assumed round-trip costs. BTC is bought hypothetically over the identical entry/exit window and charged the same 20 bps; equal costs cancel in alt minus BTC excess. Signals include skipped overlaps; completed trades exclude them. Compounded return and drawdown serially multiply event returns in chronological order; simultaneous symbols make this **an event-series diagnostic, not a deployable portfolio equity curve**.

| Candidate | Signals / overlap / completed | Weeks | Gross / net / BTC net / excess, bps mean | Win / median net / PF | Sequential compound / max DD | Worst / best net, bps |
|---|---:|---:|---|---|---|---|
| Volume impulse | 297 / 38 / 259 | 144 | 33.13 / 13.13 / -28.62 / +41.75 | 47.9% / -53.97 / 1.05 | -27.90% / -78.16% | -2077 / +3748 |
| Failed downside | 255 / 2 / 253 | 120 | 67.09 / 47.09 / +13.05 / +34.03 | 54.2% / +26.40 / 1.30 | +131.06% / -61.36% | -2130 / +2439 |
| VWAP reversion | 3519 / 945 / 2574 | 300 | 11.12 / -8.88 / -6.02 / -2.86 | 47.7% / -9.98 / 0.94 | -98.86% / -99.78% | -2490 / +4056 |

All three represented ETH, SOL and LINK and exceeded the draft minimum 60 trades, 12 weeks and 3 symbols. Those are volume gates, **not a power result**. No pending trades occurred at the fixed data boundary.

| Candidate | Net bps @10 / 20 / 30 / 40 / 60 bps cost | Mean / median MFE, bps | Mean / median MAE, bps | Correct gross direction |
|---|---|---|---|---:|
| Volume impulse | +23.13 / +13.13 / +3.13 / -6.87 / -26.87 | +542 / +366 | -469 / -306 | 48.6% |
| Failed downside | +57.09 / +47.09 / +37.09 / +27.09 / +7.09 | +368 / +226 | -358 / -242 | 56.5% |
| VWAP reversion | +1.12 / -8.88 / -18.88 / -28.88 / -48.88 | +285 / +179 | -304 / -199 | 51.4% |

Mean potential favorable excursion after 20 bps friction is +522, +348 and +265 bps respectively; these are **unrealized candle extremes**, not executable gains. Mean adverse excursion in strictly completed bars before the maximum favorable candle is -221 bps for 151 volume events, -182 bps for 138 downside events and -156 bps for 1,255 VWAP events. For other events MFE is in the entry candle, so preceding-bar adverse excursion is undefined. Mean adverse before exit equals the full holding-window MAE shown above. An 8h candle does not disclose whether its high preceded its low; no intrabar stop or fill order is inferred.

## Dependence, regime and control checks

Weeks are UTC ISO calendar weeks **pooled across symbols**. Two thousand fixed-seed whole-week bootstrap resamples give descriptive 98.33% Bonferroni-width intervals for the three exact candidates. This is multiplicity-aware in width, but is **not a calibrated formal test**, especially after seven inspected public hypotheses, this historical inspection, and nine reported threshold cells. The v1 equal-week normal intervals and these trade-weighted resamples answer different summaries; neither licenses a significance claim.

| Candidate | Positive weeks | Three-candidate adjusted bootstrap excess interval, bps | Leave-one-week-out excess range | Leave-one-symbol-out excess, ETH / LINK / SOL omitted |
|---|---:|---|---|---|
| Volume impulse | 50.0% | [-44.36, +136.05] | [+30.18, +54.57] | +28.76 / +85.54 / +14.24 |
| Failed downside | 53.3% | [-34.29, +113.86] | [+17.20, +42.80] | +31.65 / +43.50 / +27.66 |
| VWAP reversion | 52.0% | [-19.38, +14.55] | [-4.96, -1.06] | -2.11 / -0.36 / -6.12 |

Volume impulse has negative net expectancy on LINK (-68.1 bps) and negative BTC excess in 2022, 2023 and 2026. Failed downside has positive net on each symbol (+49.7 ETH, +16.9 LINK, +77.7 SOL bps) but negative BTC excess in 2020 and 2023. Its BTC-relative mean is +131.4 bps in 52 prior-BTC-bear events and +5.7 bps in 223 lower-volatility events, indicating regime concentration. The largest positive week contributes 14.9% of positive weekly net PnL; the largest positive month contributes 13.3%. VWAP reversion is net negative on all three symbols and in 2022–2026. Full-sample descriptive BTC beta slopes are 0.993, 1.414 and 1.351; beta-adjusted net intercepts are +21.69, +0.36 and -27.76 bps. Beta is fitted on inspected data, so this is sensitivity, not a tradable hedged result.

The regime bins use **only prior** BTC closes: 30-bar change >+10% bull, <-10% bear, otherwise sideways; prior 30 8h log-return sample standard deviation >=2.5% is high volatility. No regime changes any signal. The JSON includes all yearly, monthly, regime, volatility, symbol, week and session rows, including negative years and groups.

The 8h grid allows entry hours only at 00, 08 and 16 UTC. Coarse Asia/London/New York proxies show raw signal counts of **104/54/139** for volume impulse, **93/84/78** for failed downside, and **1141/1300/1078** for VWAP. Completed trade counts by the same hours are 94/42/123, 93/82/78 and 887/964/723. Session overlaps are not separately identifiable at this resolution. These are descriptive; no session filter was selected.

Controls keep original trade counts and holding periods: a +7-bar shifted-entry control and 500 fixed-seed random entry times within the same symbol's ISO entry week. The latter is a blocked timing placebo, not a state-matched causal counterfactual; it can overlap. Matched BTC is reported above. Results are excess bps:

| Candidate | Observed | +7-bar shift | Same-week random mean, 95% range | Fraction of placebos >= observed |
|---|---:|---:|---|---:|
| Volume impulse | +41.75 | -32.37 | +76.20 [+16.58, +132.71] | 86.8% |
| Failed downside | +34.03 | -32.69 | -16.68 [-49.86, +22.35] | 0/500 |
| VWAP reversion | -2.86 | +2.76 | -22.75 [-32.18, -12.78] | 0/500 |

The VWAP placebo comparison alone does not rescue a negative standalone and BTC-relative strategy. The volume placebo often beats the signal. Failed downside merits independent replication because its timing control is weaker, but the cluster interval and beta sensitivity prevent a final candidate.

## Bounded development neighborhood and trial accounting

Only **one parameter at a time** was perturbed, with all nine cells disclosed below; six are additional inspected cells. No best cell was selected. The original 25-source survey and seven hypothesis families remain part of the broader selection history. Every cell still uses next-open spot execution, the original holding time and the same four-market dataset.

| Family and varied threshold | 3 threshold values: completed / net @20 / net @40 / BTC excess, bps |
|---|---|
| Volume multiple | 1.5: 610 / +18.18 / -1.82 / +30.95; **2.0 draft:** 259 / +13.13 / -6.87 / +41.75; 2.5: 130 / -8.79 / -28.79 / -4.35 |
| Failed-downside close location | 0.60: 329 / +28.39 / +8.39 / +20.87; **0.70 draft:** 253 / +47.09 / +27.09 / +34.03; 0.80: 166 / +25.28 / +5.28 / +14.24 |
| VWAP displacement, bps | 50: 2670 / -7.81 / -27.81 / -1.49; **70 draft:** 2574 / -8.88 / -28.88 / -2.86; 90: 2464 / -8.72 / -28.72 / -3.05 |

## Disposition and next experiment

- **PSV1-VOLUME-IMPULSE — REJECTED.** Fails 40 bps cost stress; median net is negative; LINK and several years are negative; same-week placebo is stronger on average.
- **PSV1-FAILED-DOWNSIDE — DEVELOPMENT-INTERESTING, NOT READY.** Net and BTC-relative means are positive, stress survives 60 bps, all symbols contribute, and the bounded threshold check stays positive. The adjusted cluster interval includes zero, the beta-adjusted intercept is nearly zero, and high-volatility/bear market concentration is material. No final/frozen v2 is justified.
- **PSV1-VWAP-REVERSION — REJECTED.** Net and BTC-relative expectancy are negative; all symbols have negative net returns; adjacent thresholds remain negative at 20 bps.

**Next step:** design an independent, untouched replication of the original failed-downside definition on a distinct spot venue or genuinely later candles, with executable next-open cost calibration, a predeclared sample/power plan, and an independent event-driven signal/fill implementation. Commit and freeze that new protocol **before** observing its evaluation window. Do not tune the v1 ID, start a future watch, or promote based on this development dataset.

## Reproduction and evidence limits

```text
python scripts/collect_public_spot_8h.py --output artifacts/public_spot_8h_20261010
python -m orderflow_edge_lab.public_strategy_shadow --config config/public_strategy_shadow_v1.json --data-dir artifacts/public_spot_8h_20261010/aligned_csv --as-of 2026-10-01T00:00:00Z --mode development --output artifacts/public_spot_8h_20261010/exact_v1_report.json
python -m orderflow_edge_lab.public_strategy_development --config config/public_strategy_shadow_v1.json --exact-report artifacts/public_spot_8h_20261010/exact_v1_report.json --data-dir artifacts/public_spot_8h_20261010/aligned_csv --output artifacts/public_spot_8h_20261010/diagnostics_final.json
```

Collectors and evaluators use exclusive-create outputs, so use a new directory for a rerun. Raw HTTP pages, aligned CSVs, SHA manifest, exact per-event report and full diagnostics are committed together. Fixed friction is an assumption, not venue-calibrated executable fills. No Freqtrade or NautilusTrader parity run was completed, and no formal OOS or profitability claim is made. Existing frozen protocols, payoff geometry and session watches were not modified.
