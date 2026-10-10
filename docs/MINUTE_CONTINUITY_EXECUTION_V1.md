# Continuous minute data, power and execution design

PSR7 is a distinct feasibility protocol after PSR6's sparse twelve-day source audit. It has no predictor, trading rule, fitted loss or return claim. The failed PSR5 volume hypothesis remains closed. All frozen lanes, payoff geometry and existing prospective/session watches remain unchanged. Bollinger Bands are excluded. No orders are supported.

Before retrieval, commit `config/minute_continuity_execution_v1.json`. Fix the same BTC/ETH/SOL/LINK Spot universe and all 69 completed months January 2021–September 2026: 276 official monthly 1m ZIPs plus CHECKSUMs, 2,099 UTC days, 3,022,560 expected minutes per symbol. Validate every row and retain all bytes, source URLs, hashes and actual receipts. Monthly CSVs are streamed; no giant pooled price frame is retained. Missing candles are reported, never filled, trimmed or substituted. Whole complete Monday–Sunday panel weeks are counted separately from partial boundary weeks and weeks affected by any source gap. Retrieved history is development data; prior sample days were already inspected.

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
