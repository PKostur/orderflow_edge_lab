# Cross-Sectional OKX Independent-Venue Replication v1

This is a new D2 source-replication attempt for the already frozen candidate `mexc_xs_mom30_7_dn_v1`.

It does not replace or reinterpret the failed Binance or Bybit access attempts. Those produced no replication evidence.

## Independent venue

Replication venue:

`OKX USDT-Margined Perpetual Swap`

Public source endpoints:

- historical candles: `GET /api/v5/market/history-candles`;
- funding history: `GET /api/v5/public/funding-rate-history`.

The replication uses UTC daily candles (`1Dutc`) and the historical `realizedRate` funding field.

## Frozen candidate

No candidate parameter changes are permitted:

- 30-day cross-sectional momentum;
- 7-day holding period;
- dollar-neutral top/bottom quartile;
- 20 bps round-trip transaction cost;
- 1x gross exposure;
- actual realized venue funding.

MEXC and OKX are forced onto the same intersection calendar before signal generation and evaluation.

## Evidence level

This remains D2 independent-venue replication over an already inspected historical period.

It is useful for:

- signal/basket transfer;
- economic-result transfer only when realized-funding coverage is complete;
- venue-specific funding sensitivity;
- identifying source-specific behavior.

It is **not** future OOS, independent-engine replication, strategy promotion, or live-trading authorization.

If the OKX public source is inaccessible or cannot provide the required realized funding history, the attempt must fail as an engineering-source failure rather than substitute estimated funding.

## First completed run and data-quality qualification

First successful workflow run:

`36148530778`

Artifact ID:

`10871040817`

Artifact ZIP SHA-256:

`54fdb5111431f1c29db4a51698e4caf25b82afb737bed922636892bdacd5dbc3`

The full shared daily candle calendar in that artifact runs from `2025-09-17T00:00:00Z` through `2026-09-11T00:00:00Z`.

Signal transfer is very strong descriptively:

- exact daily executed-weight agreement: about 97.87%;
- non-zero side agreement: about 98.94%;
- rebalance-event agreement: 100%;
- exact long/short basket agreement across rebalance events: about 97.62%;
- mean long-basket Jaccard: about 98.41%;
- mean short-basket Jaccard: 100%.

Those statistics are valid D2 same-period signal/basket transfer evidence.

The first run also exposed an important funding-data limitation. The captured OKX funding files begin around `2026-06-22`, while the shared strategy calendar begins in September 2025. By contrast, the captured MEXC funding history already spans the shared strategy window. Therefore most of the OKX shared historical period does not have realized OKX funding observations in the artifact.

The current v1 backtest helper contributes zero when a funding frame has no settlement inside a held daily interval. For this first run, that means the reported OKX net return, Sharpe, drawdown, and fold economics are **partial-funding diagnostics**, not a complete realized-funding replication of the frozen candidate.

Consequences:

- the signal/basket replication result remains usable descriptive D2 evidence;
- the v1 economic comparison is not qualified as complete independent-venue economics;
- no profitable-edge, promotion, live-trading, or leverage claim is authorized;
- the v1 protocol and artifact must not be retroactively rewritten after inspection.

OKX's public historical-data service advertises perpetual funding-rate history from March 2022 onward. A corrected economic replication should therefore use that archive, or another source with demonstrably complete realized-funding coverage, under a new versioned replication protocol.

Reference:

- https://www.okx.com/en-sg/historical-data
