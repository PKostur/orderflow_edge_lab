# Weekly ETF momentum v2 — D3 pre-calculation clarification

Frozen after D0 was recorded and before any D3 PnL was calculated.

- D3 is evaluated as an independent locked holdout block.
- The first D3 observation starts from zero prior target weights for the original, reversed and benchmark portfolios.
- Therefore the first D3 rebalance pays the frozen establishment cost under the same turnover formula used at D0.
- D3 does not inherit the final D0 holdings or turnover state. This avoids using discovery-period portfolio state to reduce holdout costs.
- All signal, score, ranking, dividend, entry/exit and cost parameters remain exactly those in FREEZE.json and FREEZE_CLARIFICATION.md.
