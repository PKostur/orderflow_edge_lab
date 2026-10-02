# OKX Historical Funding Source Probe v1

## Purpose

This is an engineering and data-quality probe only.

The first OKX D2 venue replication preserved strong signal/basket transfer evidence but did not have complete realized-funding coverage. The separate funding-coverage audit measured only about 24.7% coverage across actually held symbol-day intervals.

This probe asks one question before any new economic replication is defined:

Can the official OKX historical market-data service expose downloadable funding-rate archives that cover the missing historical period?

It does not compute candidate PnL.

## Source contract

The probe uses the public endpoint bound by the official `okxapi/python-okx` SDK:

`GET /api/v5/public/market-data-history`

Funding-rate history is module `3`.

OKX's API changelog states that the historical market-data endpoint supports funding-rate data and daily/monthly aggregation. OKX's historical-data page states that perpetual funding-rate archives are available from March 2022 onward.

The current endpoint limits historical queries to ten daily days or ten monthly months per request. The first live probe also established an endpoint-side maximum of five `instFamilyList` values per request via OKX error `50025`. The probe therefore splits both the time window and the ten frozen families before inspecting archive contents.

## Fixed source queries

The candidate's current shared OKX price window starts in September 2025 and ends in September 2026.

The probe requests:

1. monthly metadata from September 2025 through June 2026 for BTC, ETH, SOL, XRP, and DOGE;
2. the same monthly period for BNB, ADA, LINK, SUI, and ENA;
3. monthly metadata for July and August 2026 for the first five-family group;
4. the same July and August period for the second five-family group;
5. daily metadata for September 1 through September 10, 2026 using the endpoint's funding-rate `ANY` contract;
6. daily metadata for September 11, 2026 using the same `ANY` contract.

These queries are source discovery only. Download URLs and filenames are recorded, but the strategy is not rerun.

## Hard boundary

The probe cannot:

- calculate strategy return;
- repair the inspected v1 economic report;
- retune or modify the candidate;
- promote the candidate;
- authorize live trading;
- authorize leverage.

If the source probe succeeds, a later step may download and validate the funding files. Only after complete realized-funding coverage is demonstrated should a separate versioned D2 economic replication protocol be frozen.


## First live source-contract correction

Workflow run `36157592839` passed all local source-probe tests but the first live monthly query was rejected by OKX with code `50025` because ten instrument-family values exceeded the live limit of five.

This is an engineering-source contract correction only. No archive contents were consumed, no candidate economics were calculated, and no strategy evidence was created. The fixed query plan now splits the frozen ten-family universe into two deterministic five-family groups.
