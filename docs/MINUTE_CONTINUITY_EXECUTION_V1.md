# Continuous minute data, power and execution design

PSR7 is a distinct feasibility protocol after PSR6's sparse twelve-day source audit. It has no predictor, trading rule, fitted loss or return claim. The failed PSR5 volume hypothesis remains closed. All frozen lanes, payoff geometry and existing prospective/session watches remain unchanged. Bollinger Bands are excluded. No orders are supported.

Before retrieval, commit `config/minute_continuity_execution_v1.json`. Fix the same BTC/ETH/SOL/LINK Spot universe and all 69 completed months January 2021-September 2026: 276 official monthly 1m ZIPs plus CHECKSUMs, 2,099 UTC days, 3,022,560 expected minutes per symbol. Validate every row and retain all bytes, source URLs, hashes and actual receipts. Monthly CSVs are streamed; no giant pooled price frame is retained. Missing candles are reported, never filled, trimmed or substituted. Whole complete Monday-Sunday panel weeks are counted separately from partial boundary weeks and weeks affected by any source gap. Retrieved history is development data; prior sample days were already inspected.

The power calculation is a hypothetical planning approximation: one-sided alpha .01, 80% power, standardized paired weekly mean-loss effect .25 yields 161 independent weeks. The effect is not .25 basis points or a measured lead-lag effect. Only 299 complete calendar weeks exist before data gaps; independence is unproven. A fixed four-week dependence-inflation scenario requires 644 calendar weeks. No predictor is fit to estimate weekly loss variance. Counting millions of candles or three altcoins as independent observations is prohibited. A power failure cannot be repaired by lowering the requirement after retrieval.

Eight exact public S3 prefixes for Spot monthly bookTicker/bookDepth are inspected. An empty listing or access failure says only what was observed at that path, not that all historical execution sources are unavailable. A top-of-book ticker would still not supply full depth, exchange/broker latency, actual fees or fills. Futures data are not substituted. OHLCV cannot reconstruct those inputs. Cost envelopes are fixed assumptions: 10bps fee each side plus 0/20/40bps round-trip execution burden, giving 20/40/60bps scenarios. Primary stress stays 60bps, with no discount. This study does not compute PnL or infer historical fills from candle extrema.

The deliverable is an audited continuous-coverage verdict, explicit hypothetical power sensitivity and historical execution evidence status, with tests, retained source manifest and reviewable engineering report. Missing execution inputs or failed dependence-power scenario block research readiness even if price data retrieval succeeds. Completion of the study is separate from survival of a strategy; there is no candidate to promote or prospective protocol to activate.

Sources: [Binance official public-data schema/checksums](https://github.com/binance/binance-public-data) and [Binance Spot API documentation](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints). Timestamp units change from milliseconds to microseconds on January 1, 2025.

## Implementation and evidence accounting

Immutable design commit: `1f05a9c2e93d9f26b908ee9faeb00def487e8f52`. Initial auditor implementation: `15f1b2eda2cb0d2158e6485c1a1dbb9d60c4f270`. Collector failure handling was reviewed before retrieval. Each ZIP is retained with its own receipt before the checksum request; checksum bytes/receipt are retained separately even when validation fails. Resume verifies the exact bound raw bytes and receipts. Changed bytes, missing receipts or another design fail closed. Prefix responses use unique filenames and are retained before XML interpretation, preserving earlier retrievals.

The validator fails fast on the first invalid row in a month. `observed_valid_candles` counts only rows in monthly files which fully passed the schema audit. Rejected months have unknown daily candle/gap counts; their entire daily/weekly contribution is withheld conservatively. `missing_minutes_in_verified_archives` counts gaps only in schema-valid files and is **not** total source missingness. A checksum can pass while row/schema validation fails. No values are repaired to obtain continuity. Complete shared weeks require seven complete UTC days in all four symbols from fully audited archives.

Raw ZIPs, checksums and their receipts are deliberately retained outside Git because this full panel is large. The committed source manifest contains portable relative filenames, exact download URLs, byte lengths, hashes and UTC receipts. The report contains its own source-manifest/daily-quality hashes. A fresh directory retrieves a new receipt/version of the public archives; the same bound raw directory revalidates the retained version without substituting updated archives. Upstream archives can change, so new retrievals must never silently replace this evidence.

## Reproduce

From a repository checkout with research dependencies, choose an unused report directory and a separate raw directory:

```powershell
$env:PYTHONPATH = 'src'
python -m orderflow_edge_lab.minute_continuity_execution --spec config/minute_continuity_execution_v1.json --design-commit 1f05a9c2e93d9f26b908ee9faeb00def487e8f52 --raw-dir ../psr7-retained-raw --output-dir runs/psr7-audit
```

To revalidate the retained source version, reuse the bound raw directory with a new report directory. Raw archive/checksum receipts remain unchanged; source-failure observation timestamps and fresh prefix-probe responses may differ. Reports must distinguish those retrieval-dependent fields from deterministic calendar and quality calculations. This is development evidence, not a reserved holdout.

## Completed audit: October 10, 2026

All 276 monthly ZIPs and 276 official checksums were retrieved and matched, covering January 1, 2021 through September 30, 2026 inclusive, for BTCUSDT, ETHUSDT, SOLUSDT and LINKUSDT. Checksums prove retained bytes match the published checksums; they do not prove schema completeness.

| Audit measure | Result |
|---|---:|
| Expected panel minute slots | 12,090,240 |
| Fully audited candles | 11,219,639 |
| Complete symbol-month archives | 247 |
| Schema-valid archives with gaps | 9 |
| Rejected symbol-month archives | 20 |
| Known missing minutes in schema-valid archives | 841 |
| Expected slots in rejected months, unquantified | 869,760 |
| Unique symbol-days | 8,396 |
| Complete calendar weeks before quality exclusions | 299 |
| Verified shared complete weeks | 271 |

The exact accounting is 11,219,639 + 841 + 869,760 = 12,090,240. Rejected-month slots are **not measured missing candles**. All four symbols failed the declared nominal close-time rule in February, April, August and December 2021 and March 2023. The first invalid rows were respectively 14,621; 34,651; 17,400; 33,420; and 33,880. Whole months were rejected without repairing timestamps. Schema-valid gaps were 90 minutes per symbol in March 2021, 120 per symbol in September 2021, and one SOL minute in February 2023. BTC/ETH/LINK each had 62 complete, two gapped and five rejected archives; SOL had 61 complete, three gapped and five rejected archives.

| Year | Fully audited candles | Known missing | Rejected symbol-months |
|---|---:|---:|---:|
| 2021 | 1,410,360 | 840 | 16 |
| 2022 | 2,102,400 | 0 | 0 |
| 2023 | 1,923,839 | 1 | 4 |
| 2024 | 2,108,160 | 0 | 0 |
| 2025 | 2,102,400 | 0 | 0 |
| 2026 January–September | 1,572,480 | 0 | 0 |

The 271 verified weeks exceed the optimistic hypothetical 161-independent-week count, but independence and observed paired loss variance are unestablished. They fail the fixed 644-calendar-week scenario. The floor of 271/4 = 67 is only an optimistic count equivalent, not measured effective sample size or 67 contiguous usable blocks. No predictor was fitted and no adequacy claim is supported.

All eight exact Spot monthly bookTicker/bookDepth prefix probes returned HTTP 200 with no listed objects, both initially and on revalidation. This finding applies only to the probed paths. Historical execution remains unconfirmed; cost envelopes of 20/40/60 basis points remain assumptions. No trading simulation, return, MFE/MAE, fills or PnL was run; trade count is not applicable. There are zero new predictor hypotheses and zero trading cells.

Initial provenance-guard commit: `861faa69989e93d39e7239e321a3723ed3de1555`. Final implementation commit: `5e357ce517053b8a1172688b138fa66cc223d9ad`. Windows CI exposed coarse-clock prefix filename collisions; UUID suffixes now prevent them, with an identical-clock regression test. Full retained-source revalidation was repeated after this storage-only fix, preserving all study rules and quality results. Full cached revalidation retained every original archive, checksum and receipt, with byte-identical daily quality output. Initial reports are preserved separately; failure-observation times and fresh prefix receipts differ. The final retained directory contains 1,129 files totaling 524,657,312 bytes, including all three sets of prefix responses. `local_raw_verification.json` records every retained file hash and verifies all archive/checksum/receipt and prefix-body hashes. Raw archive requests began 2026-10-10T20:24:37.448122Z; the last checksum receipt was 20:43:00.997665Z. Final prefix receipts ended at 2026-10-10T21:02:52.004440Z.

**Decision: FEASIBILITY_STUDY_COMPLETE_RESEARCH_READINESS_BLOCKED.** Source continuity, established independence/loss variance, the declared dependence scenario and historical execution evidence have not passed. The study is closed without promotion, retuning or an automatic watch. Any later predictive study requires a distinct preregistration and the missing evidence. PSR5 remains rejected as specified: its eight-hour volume feature improved aggregate MSE by 0.36809846%, below its 1% hurdle, with a descriptive 99% interval of [-0.59856917%, +1.26697856%] and negative ETH improvement. That failed definition is not reopened.

## Engineering verification

The repository's mandatory unittest suite passed all 960 tests, including ten PSR7 tests. Ruff and whitespace checks passed. The local mandatory multi-agent report passed manifest verification with release-manager status `reviewable`, zero errors and zero warnings. Independent read-only evidence review reconciled the report, raw inventory and original/final audit.

An additional broad pytest run found 1,014 passing tests, 67 passing subtests and three failures in existing conditioning-epoch/cross-sectional tests. The same three failures were reproduced in an isolated archive of unchanged base commit `36eaf477178598b4343d886c672e61510b34a17b`. They concern an existing successful-run ledger recovery filter, an existing test missing a next-day open and a stale rebalance-count expectation. Those frozen/existing research lanes were preserved. The mandatory CI uses unittest; this audit does not claim that the optional broad pytest suite is fully green.
