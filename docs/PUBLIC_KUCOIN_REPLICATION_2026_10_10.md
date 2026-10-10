# Failed-downside descriptive venue replication

Study `PSR2-KUCOIN-FAILED-DOWNSIDE` closes the requested venue-access gate. **Reject cost-robust survival and prospective promotion.** No threshold retuning, future watch, or frozen-lane change is justified.

The coverage and analysis design was committed as `ce7d0f4363ed9ec01883ab61e581ae3ecfcfad38` before the first successful historical request. KuCoin metadata provided SOL's listing timestamp; coverage was fixed to the first complete following UTC day, August 5, 2021, through September 30, 2026. Every pair has 5,649 native UTC 8h bars, ending at 16:00 UTC September 30. The collector rejects missing, duplicate, misaligned or invalid bars without filling, trimming or selecting a different range. Exact response bytes, each request URL and send/receive time, CSV hashes, design hash and design commit are in `artifacts/public_kucoin_8h_20261010/manifest.json`. Files are byte-preserved in Git. No credentials or order endpoints were used.

The [official candle API](https://www.kucoin.com/docs-new/rest/spot-trading/market-data/get-klines) warns that candles can be incomplete. The [official fee guidance](https://www.kucoin.com/support/360015188494) says pair/account conditions affect fees. Public metadata gives all four pairs feeCategory 1 and taker coefficient 1.00; this is not verification of the user's actual regional/account fee. The 30 bps round-trip sensitivity assumes 10 bps taker per side plus 10 bps spread/slippage. No cost level is presented as calibrated historical execution.

## Results

The independent streaming engine from the engineering audit is reused unchanged: 30 prior lows, strict downside breach and close recovery, close location at least 0.70, no bullish-bar requirement, entry next open, hold two bars, per-symbol nonoverlap and same-open reentry. Only failed downside is evaluated, with no new threshold cells. BTC uses each venue's own identical entry/exit window. The matched-period Binance run resets the same 30-bar warmup at the same boundary; it is reported separately, never pooled.

| Metric | KuCoin | Binance, identical range |
|---|---:|---:|
| Signals / skipped / completed / pending | 215 / 1 / 214 / 0 | 216 / 1 / 215 / 0 |
| Active exit weeks | 99 | 99 |
| Mean gross, bps | 24.5454 | 41.9818 |
| Mean net at 20 / 30 / 40 / 60 / 80 bps | 4.5454 / -5.4546 / -15.4546 / -35.4546 / -55.4546 | 21.9818 / 11.9818 / 1.9818 / -18.0182 / -38.0182 |
| Same-window BTC excess, bps | 12.8650 | 22.5484 |
| Descriptive week bootstrap 98% interval, bps | [-41.2335, 73.3161] | [-32.9210, 82.2248] |
| Leave one week out excess range, bps | [-1.6536, 22.6364] | [8.3291, 32.3467] |
| Equal initial coin sleeves return / drawdown at reference20 | -2.3125% / -26.0485% | 10.6131% / -23.9935% |
| Full-sample beta / reference20 intercept, bps | 1.2961 / -10.5938 | 1.3005 / -3.2912 |

KuCoin ETH/LINK/SOL trade counts are 54/87/73; respective net20 means +31.4252/+6.9866/-18.2476 bps, BTC excess +37.7908/+6.4568/+2.0638. Leave-ETH-out excess falls to +4.4525 bps. Mean MFE/MAE are +309.1361/-339.6740 bps, medians +213.1369/-238.0012; these OHLC bounds do not establish intrabar order or achievable fills. The detailed ledger and all predeclared year/month/hour/regime diagnostics are in `replication.json`. UTC entries at 00/08/16 are coarse session information.

The +7-bar shifted timing control has KuCoin net20 -11.2111 and BTC excess -15.3713 bps. The 500 same-week/symbol timing placebos average -17.1449 bps excess, with descriptive 95% range [-44.1005,13.9218]; 2.6% meet or exceed observed excess. These controls permit overlapping synthetic trades and do not preserve matched market state. Neither their tail fraction nor the bootstrap interval is a formal discovery p-value. The inherited three-candidate interval is explicitly descriptive; the prior 25-source/seven-family/nine-cell selection history remains relevant.

## Execution gate and decision

Four timestamped 20-level books were retained. At 1,000 USDT notional the displayed simultaneous buy-then-sell loss excluding fees was 0.0719 bps ETH, 0.9132 SOL and 0.8383 LINK. BTC had insufficient displayed ask depth, so its gate failed; no extrapolation was substituted. Receipt ages were 0.216–0.359 seconds. These single current snapshots cannot calibrate historical boundary execution, latency, account fees or future liquidity. Spread is included once in the depth walk.

Cross-venue positive gross excess survives descriptively, but net expectancy fails the fixed 30/40 bps sensitivities, the cluster interval crosses zero, removing one week reverses excess, the equal-sleeve reference20 portfolio loses, and beta-adjusted intercept is negative. Shared market weeks are not additional independent OOS observations. Prior power infeasibility remains unchanged. **Close failed downside as a research candidate for promotion; retain its historical development evidence without retuning.** Volume impulse and VWAP remain rejected from the original study. A new economic hypothesis needs a new identifier and an adequate validation design; no automatic collection or prospective protocol is opened here.

## Reproduction and verification

With repository source on the Python path, `python -m orderflow_edge_lab.kucoin_replication` verifies hashes and writes the report exclusively. For a rerun preserve the committed report and choose a separate workspace copy. `python scripts/collect_public_kucoin_8h.py` requires committed design bytes and refuses to overwrite the source folder. API responses may change after this retrieval; the retained bytes are the reproducible evidence.

Tests cover missing/duplicate/non-UTC candles, invalid OHLCV, depth exhaustion, spread accounting and every committed source hash. The deterministic multi-agent report and CI checks provide engineering verification, not scientific validation.
