# OCC Strategy R5.1 External Outlier Protocol

Status: external outlier diagnostic only. This study is not a candidate, is not eligible for promotion, and must not modify `config/candidates.json`, the candidate registry, or any live/shadow execution path.

## Frozen question

Does the published OCC Strategy R5.1 retain positive unlevered expectancy after its historical higher-timeframe lookahead behavior is removed?

## Frozen implementation

Published default logic only:

- MA type: SMMA
- MA length: 8
- Alternate resolution: enabled
- Alternate resolution multiplier: 3x chart timeframe
- Direction: both long and short
- Stop loss: disabled
- Take profit: disabled
- Parameter tuning: prohibited for this study

The signal is a crossover between the smoothed close series and smoothed open series.

## Diagnostic variants

1. `original_lookahead`: emulate the historical higher-timeframe `lookahead_on` behavior as a deliberately biased reproduction control.
2. `confirmed_htf`: identical SMMA 8 and 3x higher-timeframe structure, but only the last fully completed higher-timeframe candle is visible.
3. `same_tf`: SMMA 8 open/close crossover on the chart timeframe with no higher-timeframe request.

The deliberately biased variant exists only to quantify how much of the TradingView result can be attributed to future leakage. It must never be interpreted as tradable evidence.

## Data freeze

- Source: MEXC public futures klines
- Scored period: 2026-06-01 through 2026-09-12 exclusive
- Indicator prehistory: 7 calendar days before the scored period
- Prehistory is used only to initialize SMMA and regime state; trades with entry before 2026-06-01 are excluded from scoring
- Symbols: BTC_USDT, ETH_USDT, SOL_USDT, XRP_USDT, DOGE_USDT, LINK_USDT, SUI_USDT, ENA_USDT
- Chart timeframes: 5m, 15m, 1h
- Order timing: crossover detected at bar close, market fill at the next chart bar open

### Engineering correction after run 1

Run 1 fetched data starting exactly at the scored-period boundary. Inspection showed that a small number of early 1h trades were affected by indicator initialization and the regime classifier was still in warmup. Before interpreting per-symbol or per-regime results, the implementation was corrected to fetch seven days of prehistory while leaving the scored period, OCC parameters, symbols, timeframes, costs, and execution rule unchanged. Run 1 is therefore a preliminary engineering diagnostic, not the final evidence run. The warmup length was selected to exceed both the 8-period SMMA requirement at the slowest 3h alternate resolution and the 48-bar descriptive regime lookback, not from PnL optimization.

## Economics freeze

Round-trip friction cases:

- 0 bps, reproduction/control view only
- 12 bps
- 16 bps
- 20 bps

No leverage is applied. A negative unlevered result may not be rescued with leverage.

## Outputs

Report trade count, gross and net expectancy, win rate, profit factor, compounded return, max drawdown, simple descriptive regime dependence, and the paired performance change from `original_lookahead` to `confirmed_htf`.

## Interpretation boundary

This is an outside anomaly study. Even a strong result does not enter the candidate pipeline from this run. Any later decision to study OCC formally would require a separate explicit protocol before additional tuning or validation data are inspected.
