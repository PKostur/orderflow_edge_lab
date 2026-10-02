# Cross-sectional independent-venue replication v1

## Purpose

This lane asks whether the frozen cross-sectional momentum candidate transfers from its MEXC historical source to a genuinely separate venue data source.

It is **D2 descriptive transfer evidence** only:

- the strategy definition is frozen;
- the historical calendar is the already-inspected 2024-01-01 through 2026-09-12 period;
- the candidate is not retrained or retuned;
- the same daily calendar is enforced across the two venues;
- venue-specific realized public funding is used;
- same-period venue replication is not future OOS;
- a different venue is not an independent implementation/engine.

No replication result from this lane can by itself promote the candidate or authorize live trading or leverage.

## Frozen comparison

Candidate:

`mexc_xs_mom30_7_dn_v1`

The frozen candidate parameters, ten-symbol universe, 20 bps round-trip cost, 120-day folds, and historical window are reused unchanged.

The report compares:

- aggregate return/drawdown/funding summaries;
- fold summaries;
- daily executed-weight agreement;
- nonzero-side agreement;
- rebalance-event timing agreement;
- exact long/short basket agreement at the union of rebalance events;
- mean long-basket and short-basket Jaccard overlap.

Basket overlap is descriptive transfer information. It was added before a successful independent-venue replication report existed.

## Engineering source history

### Binance USD-M Futures

Status: `engineering_source_unavailable`

A GitHub-hosted runner received HTTP 451 from the Binance Futures endpoint before any replication report was produced.

Evidence use: none.

### Bybit Linear USDT Perpetual

Bybit documentation lists both `api.bybit.com` and `api.bytick.com` as official mainnet REST endpoints.

The loader first attempted `api.bybit.com`. After an HTTP 403 engineering-access failure it retried the identical public V5 request through `api.bytick.com`.

Workflow run `36147444359` received HTTP 403 from both official hosts before any replication report was produced.

Status: `engineering_source_unavailable_on_github_hosted_runner`

Evidence use: none.

The host fallback did not change the venue, candidate, historical window, symbols, economics, or evidence level.

## Next-source rule

A replacement venue may be attempted only because the prior public source is inaccessible, not because of a replication result.

Before any successful report, the replacement source must be recorded explicitly. The same frozen candidate definition, ten-symbol intent, historical period, calendar-alignment rule, and economics must be retained wherever the market listing history permits.

If the replacement venue cannot supply a materially comparable perpetual market/funding history for the frozen panel, the D2 lane should remain unresolved rather than silently changing the research question.
