# BTC Residual Momentum beta45 v1 — D2 current-month funding tail provenance

Status: **transport-only evidence preservation completed before any valid Binance D2 strategy result existed**.

The pre-result D2 transport amendment already permits a required current-month funding tail to be captured from the connected Binance public USD-M market-data source when Binance Vision has not yet published that month.

## Frozen source slice

- Source: official Binance USD-M public funding-rate history, read-only connected Binance market data.
- Endpoint semantics: `/fapi/v1/fundingRate`.
- Retrieval date: `2026-09-16` UTC.
- Exact query interval: `2026-09-01T00:00:00Z` through `2026-09-12T00:00:00Z` exclusive.
- Exact symbols: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, BNBUSDT, ADAUSDT, LINKUSDT, SUIUSDT, ENAUSDT.
- Preserved D2-relevant source fields: `symbol`, `fundingTime`, `fundingRate`.
- Snapshot: `binance_funding_tail_2026-09-01_2026-09-12.json`.
- Snapshot SHA-256: `ba7f10432475e5dc885d309a67ae3f989c028d622e7371c07009e4fa45cdeea8`.

The snapshot retains the exact exchange timestamps and funding-rate strings used by D2. It does not impose a synthetic settlement frequency. This matters because ENAUSDT had 4-hour settlements in part of the frozen interval while most other symbols had 8-hour settlements.

## Merge rule

Binance Vision remains authoritative for all available archived daily klines and completed-month funding archives. The frozen snapshot is used only for the missing September 2026 funding tail. No price data, candidate rule, cost, execution assumption, symbol universe, control, gate or evidence boundary is changed.

The loader fails closed on unsupported schema, incomplete query coverage, missing symbols, mismatched vector lengths, invalid rates, duplicate timestamps or non-monotonic timestamps. The existing D2 tail check remains active after the merge.

When the September 2026 Binance Vision monthly funding archive becomes available, this snapshot should be reconciled against the archive. Any material data discrepancy is a data-integrity issue and must not be handled by retuning the frozen candidate.
