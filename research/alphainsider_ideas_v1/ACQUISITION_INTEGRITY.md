# AlphaInsider-inspired scan v1 — Massive acquisition integrity note

Recorded before any local strategy PnL is calculated.

The Massive custom aggregate endpoint's `limit=50000` constrains the underlying base aggregates used to build 5-minute bars. Broad ascending requests over the frozen January-September scan therefore returned temporally truncated result sets even though the requested date range was wider.

Correction is engineering-only and does not change the frozen protocol:
- Each frozen date segment is fetched twice with identical ticker, resolution, adjustment and dates: once `sort=asc` and once `sort=desc`.
- The two result sets are unioned and deduplicated by exact timestamp before any signal or PnL calculation.
- Coverage must span the requested segment endpoints and required strategy timestamps before that ticker/date can be eligible.
- Duplicate timestamps must have identical OHLCV/VWAP values; any conflicting duplicate invalidates the affected ticker/date rather than choosing one version.
- No partial/truncated dataset may be used for strategy PnL.
- This acquisition correction was triggered by date-coverage inspection only; no strategy return was inspected.
