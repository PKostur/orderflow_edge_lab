# dv2_volume_confirmed_momentum_30d_v1 freeze clarification

Status: **PRE-VALIDATION IMPLEMENTATION CLARIFICATION**

This note is recorded before independent-engine reproduction and before any Binance D2 economic result.

The selected Sprint 3 `volume_momentum_30d` series was generated under the family's preregistered `common_comparison_warmup_days = 45`. The candidate's economic signal remains exactly a 30-completed-day prior median of volume. The extra 15 days are not a signal parameter and are not used in the score; they only fix the historical evaluation start so validation reproduces the exact D0 series rather than adding earlier observations that were absent from selection.

Therefore all retrospective D0/D2 replication runs use:

- economic volume lookback: 30 completed days;
- fixed common evaluation warm-up: 45 completed days;
- first signal after that fixed warm-up;
- next-UTC-daily-open execution;
- 10 bps per transaction side on actual turnover;
- actual realized funding during each holding interval;
- final-sample liquidation cost only for closed historical evaluation accounting.

Prospective D4 does **not** use an artificial terminal liquidation and may use arbitrarily long pre-start data only as warm-up. No rule, ranking direction, cost, position size, symbol, or volume field may be changed based on validation results.
