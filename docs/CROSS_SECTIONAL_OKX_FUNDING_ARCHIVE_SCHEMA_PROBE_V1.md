# OKX Funding Archive Schema Probe v1

## Purpose

This is an engineering-only schema probe. It follows the successful OKX historical funding source probe, which found 131 official archive download URLs covering the candidate's missing historical funding period.

No candidate PnL is computed.

## Fixed samples

The archive files are selected before inspecting their contents:

1. monthly single-instrument sample:
   `BTC-USDT-SWAP-fundingrates-2025-09.zip`;
2. daily all-swap sample:
   `allswap-fundingrates-2026-09-11.zip`.

Both URLs come from the successful source-manifest probe. The sample selection is deliberately fixed to cover the two archive forms required for the eventual historical period.

## What is recorded

For each ZIP, the probe records:

- download byte size;
- ZIP member names;
- compressed and uncompressed member sizes;
- CSV header;
- row count;
- observed row column counts;
- at most three raw rows for schema discovery.

The tiny row sample is engineering metadata only. It is not used for candidate scoring.

## Safety and integrity

The parser rejects:

- invalid ZIP files;
- encrypted members;
- unsafe member paths;
- archives exceeding fixed download or uncompressed-size limits;
- excessive member counts;
- archives with no CSV member.

## Hard boundary

The probe cannot:

- compute strategy returns;
- retest the candidate;
- repair the inspected v1 economic result;
- freeze parser semantics from assumptions;
- define or run D2 economic replication v2;
- promote a strategy;
- authorize live trading;
- authorize leverage.

If the two fixed archives expose a stable parseable funding schema, the next step is to freeze a deterministic archive parser and run a complete held-interval funding coverage audit. Only after complete coverage is demonstrated may a separate v2 economic replication protocol be frozen.
