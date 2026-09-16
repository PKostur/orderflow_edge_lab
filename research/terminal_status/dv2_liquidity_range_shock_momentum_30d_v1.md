# dv2_liquidity_range_shock_momentum_30d_v1 - TERMINAL

Status: **DEAD_CANDIDATE_ID**

The candidate reproduced exactly on an independent MEXC implementation and passed same-period Binance D2, but failed the preregistered non-overlapping Binance 2025 D3 temporal holdout. Under the frozen research rules, D3 failure is terminal and cannot be rescued by retuning, leverage, later D4 observations, or selecting a different historical period.

## D2 Binance 2026
- State: D2_SOURCE_REPLICATED
- Mean net: +17.018676 bps/day
- 1.5x-cost mean net: +9.615295 bps/day
- 2.0x-cost mean net: +2.211913 bps/day
- Block-bootstrap lower bound: +1.226555 bps/day
- Minimum leave-one-symbol-out mean: +10.942996 bps/day
- Candidate minus reversed control: +63.650879 bps/day
- All frozen D2 hard gates passed.

## D3 Binance 2025
- State: D3_TEMPORAL_FAILED
- Mean net: -14.745932 bps/day
- 1.5x-cost mean net: -22.560398 bps/day
- 2.0x-cost mean net: -30.374863 bps/day
- Block-bootstrap lower bound: -33.210591 bps/day
- Minimum leave-one-symbol-out mean: -17.784459 bps/day
- Best-symbol positive-PnL share: 55.647859%
- Best-calendar-month positive-PnL share: 90.458340%
- Candidate minus reversed control: +1.765997 bps/day

Failed D3 gates: positive baseline expectancy, positive 1.5x-cost expectancy, positive LOSO, best-symbol concentration, best-month concentration, and >=5 bps/day advantage over the reversed control.

The D4 boundary frozen before this result is retained only as audit evidence. The D4 workflow is retired and must not be used to revive this candidate ID.
