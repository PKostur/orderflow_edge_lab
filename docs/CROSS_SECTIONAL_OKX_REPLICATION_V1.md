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
- economic-result transfer;
- venue-specific funding sensitivity;
- identifying source-specific behavior.

It is **not** future OOS, independent-engine replication, strategy promotion, or live-trading authorization.

If the OKX public source is inaccessible or cannot provide the required realized funding history, the attempt must fail as an engineering-source failure rather than substitute estimated funding.
