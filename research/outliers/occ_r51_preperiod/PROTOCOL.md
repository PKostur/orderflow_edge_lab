# OCC R5.1 Retrospective Preperiod Replication

Status: external outlier follow-up only. This is not a candidate, is not eligible for promotion, and does not modify candidate, shadow, or live paths.

This follow-up was frozen after the corrected 2026-06-01 through 2026-09-12 outlier run showed that the published lookahead implementation was strongly profitable while the causal implementation was broadly negative after costs. The only residual observation was a small gross-positive 1h pocket concentrated on long trades.

## Frozen purpose

Use an earlier, previously uninspected period to test whether that residual is stable or is better explained by the later market regime. Because this earlier period is being inspected after the later-period result, it is retrospective replication, not genuine future out-of-sample evidence.

## Frozen settings

No OCC parameter or execution setting changes are permitted:

- SMMA length 8
- Alternate resolution multiplier 3x
- Both long and short directions
- No stop loss
- No take profit
- Next-chart-bar-open execution after a close-confirmed crossover
- Variants: original lookahead diagnostic, confirmed causal HTF, same-timeframe control
- Costs: 0, 12, 16, 20 bps round trip
- Indicator prehistory: 7 calendar days
- Symbols: BTC_USDT, ETH_USDT, SOL_USDT, XRP_USDT, DOGE_USDT, LINK_USDT, SUI_USDT, ENA_USDT
- Timeframes: 5m, 15m, 1h

## Replication window

- Scored start: 2026-03-01 UTC
- End exclusive: 2026-06-01 UTC
- Warmup start: 2026-02-22 UTC

No symbol, timeframe, side, or regime is removed based on the later-period results. Primary comparison remains the full cross-symbol/timeframe causal result versus the deliberately biased lookahead control. The 1h and long/short breakdown is diagnostic only.
