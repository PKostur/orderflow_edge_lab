# Range-shock momentum 30d v1 - freeze clarification

Status: frozen before any independent-engine, Binance D2, or 2025 D3 economic result.

The candidate's economic signal uses exactly 30 strictly prior completed daily true-range observations. Sprint 4 compared all range-shock variants only after the family's preregistered common 45-day evaluation warm-up. To reproduce the frozen D0 observation boundary exactly, historical reproduction, D2 and D3 evaluations use a fixed 45 completed-day evaluation warm-up.

This 45-day value is not an added signal input, tuning parameter, or additional range baseline. The score remains:

`(close_t / open_t - 1) * true_range_t / median(true_range[t-30:t])`

with true range defined using completed bar t and prior close, followed by next-open execution. The prospective D4 shadow may load more historical data for warm-up, but no pre-forward-start PnL is permitted.

No candidate direction, lookback, universe, portfolio weight, cost, funding, execution, gate, or evidence boundary is changed by this clarification.
