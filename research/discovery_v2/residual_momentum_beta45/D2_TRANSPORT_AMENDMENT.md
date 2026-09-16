# BTC Residual Momentum beta45 v1 — D2 Transport Amendment

Status: **infrastructure-only amendment made before any Binance D2 strategy result existed**.

Candidate freeze: `db6bd6b06078ed52fb244a1efadb0ae6a8177718`  
D2 contract freeze: `69805b22002c74f37c9e1a8ba7ab3e8fd49751e6`  
Failed infrastructure run: GitHub Actions `35096502555`

## What happened

The first D2 workflow passed all local guardrails and the immutable-candidate assertions, then failed on the first Binance USD-M kline request with HTTP `451` from `https://fapi.binance.com` on the U.S.-hosted GitHub Actions runner. It produced **no Binance dataset, no backtest result, and no candidate pass/fail state**.

This is therefore not a strategy failure and contains no result information that can be used to alter the candidate.

## Allowed transport correction

The strategy specification, symbols, historical window, funding requirement, cost model, controls and hard D2 gates remain unchanged.

The data transport may use another official Binance public-market-data delivery surface when the production USD-M REST hostname is inaccessible from the runner, in this order:

1. Binance public market-data mirror for the same public endpoint path, if it serves the USD-M path correctly.
2. Binance Public Data archive (`data.binance.vision`) for the exact USD-M datasets. Archive files must be checksum/hash preserved and normalized without changing timestamps or values.
3. If the archive does not yet publish a required current-month funding tail, that tail may be captured from the connected Binance public USD-M market-data source and preserved verbatim with its retrieval provenance and hash before the D2 result is computed.

No non-Binance venue may substitute under this amendment.

## Non-negotiable invariants

- Window remains `2026-01-01T00:00:00Z` to `2026-09-12T00:00:00Z` exclusive.
- Exact 10-symbol universe remains unchanged; no silent dropping of symbols.
- Exact beta45 residual-momentum rule remains unchanged.
- Actual Binance historical funding remains required.
- Costs and all D2 pass/fail gates remain unchanged.
- Same-period cross-source evidence remains D2, not future OOS.
- Any actual D2 strategy result after this amendment is evaluated against the already-frozen D2 gates.

This amendment exists solely to separate a geographic HTTP-access problem from strategy evidence.