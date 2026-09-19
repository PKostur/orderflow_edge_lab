# FX Asian-range breakout v1 — acquisition status

- Protocol frozen: `3e05b90d9049b0fb3359d33ba33d148b0c1dddff`
- Calculation clarification: `b43427fcf4f704c4f44be5d0fe866aadcd134693`
- Reproducible evaluator: `2623594d67b235c348f42ba73d67660d0c71a3b1`
- D0 PnL inspected: **NO**
- Full-universe scoring permitted: **NO until all four pairs cover the full frozen D0 window**
- Source limitation: hourly aggregate requests consume the provider's underlying-minute limit, so the year is reconstructed in overlapping fixed chunks and deduplicated by pair + timestamp.
- Current acquisition is engineering/data work only. No thresholds, session hours, costs, markets, or acceptance gates have changed after freeze.
