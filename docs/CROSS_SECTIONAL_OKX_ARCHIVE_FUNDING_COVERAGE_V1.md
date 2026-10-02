# OKX Archive Funding Coverage Audit v1

## Purpose

This is a data-quality-only audit for the frozen cross-sectional candidate `mexc_xs_mom30_7_dn_v1`.

The first OKX venue replication demonstrated high signal/basket transfer but only about 24.7% realized-funding coverage from the current REST history endpoint. The official historical-data manifest then exposed 131 archive files across the missing period. A fixed two-file schema probe established the archive CSV contract before this parser was frozen.

No candidate PnL is computed by this audit.

## Frozen archive parser

The parser accepts only the exact CSV header:

`instrument_name,funding_rate,funding_time`

Semantics are fixed before the full coverage result is inspected:

- `instrument_name`: exact OKX swap instrument ID;
- `funding_rate`: finite decimal converted to float;
- `funding_time`: Unix milliseconds interpreted in UTC;
- exactly three columns per row;
- target mapping: `BASE_USDT -> BASE-USDT-SWAP`;
- duplicate instrument/time records are permitted only when the rate is identical;
- conflicting duplicates fail closed.

Archive safety limits and ZIP path validation remain fixed.

## Frozen source set

The successful source probe returned exactly 131 unique official download URLs under the fixed query plan. This audit requires the manifest count to remain 131 before downloading.

The source set consists of:

- monthly single-instrument funding archives from September 2025 through August 2026;
- daily all-swap archives for September 1 through September 11, 2026.

## Coverage rule

The candidate's unchanged executed daily weights are reconstructed from OKX daily price history.

For every symbol-day interval with a nonzero executed weight, the audit requires at least one finite archive funding record strictly inside the held interval. This is the same settlement inclusion rule used by the cross-sectional backtest.

Complete economic-source admissibility requires 100% held-interval coverage.

Missing funding is never treated as a zero funding rate for admission purposes.

## Provenance

Source-manifest probe:

- run `36157784751`;
- artifact SHA-256 `72c59845a9ff36ff13d26022cb9eda599ec4f3041d00abfe9b9194682c6ecd94`.

Archive-schema probe:

- run `36158364681`;
- artifact SHA-256 `aa20b98dd5b75a23ca5fe5e5800409a50b881c4b93a7d5d64c64d525d29a8b09`;
- both fixed samples used the same three-column header;
- BTC September 2025 monthly sample contained 90 funding rows;
- September 11, 2026 all-swap daily sample contained 2,064 rows.

## Hard boundary

This audit cannot:

- compute strategy returns;
- repair or overwrite the inspected D2 v1 economics;
- retune or modify the candidate;
- define a trading filter;
- promote a strategy;
- authorize live trading;
- authorize leverage.

If and only if this audit demonstrates complete held-interval funding coverage, a separate D2 economic replication v2 may be specified and frozen before any v2 PnL is inspected.


## Transport hardening

The first full-archive attempt, workflow run `36159121966`, passed the frozen parser tests but encountered HTTP 429 while fetching the 131-file archive set. It produced no coverage verdict and therefore no data-quality evidence.

The transport layer was hardened without changing any research definition:

- bounded retry for HTTP 429 and transient 5xx responses;
- exponential backoff with a capped delay and optional Retry-After respect;
- archive download concurrency reduced to one in the validation workflow.

The 131-file source set, exact CSV parser contract, candidate specification, price window, held-interval coverage rule, and 100% admissibility threshold remain unchanged.
