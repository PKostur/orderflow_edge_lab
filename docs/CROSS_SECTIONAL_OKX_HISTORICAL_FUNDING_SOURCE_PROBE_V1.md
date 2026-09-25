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

The current endpoint limits historical queries to ten daily days or ten monthly months per request. The probe therefore splits the required period into fixed requests before inspecting source results.

## Fixed source queries

The candidate's current shared OKX price window starts in September 2025 and ends in September 2026.

The probe requests:

1. monthly metadata from September 2025 through June 2026 for the ten frozen instrument families;
2. monthly metadata for July and August 2026 for the same families;
3. daily metadata for September 1 through September 10, 2026 using the endpoint's funding-rate `ANY` contract;
4. daily metadata for September 11, 2026 using the same `ANY` contract.

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
