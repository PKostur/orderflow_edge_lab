# Basis Convergence V1 Report

## Status

Rejected at the market state layer. No strategy PnL translation was permitted.

## Protocol

Frozen protocol: `basis-convergence-v1-state-first`.

The study used directly observed MEXC fair price and index price history, the frozen ten symbol PnL independent universe, 1h bars, 21 day calendar dependence folds, 96 and 192 bar normalization windows, z thresholds 1.0, 1.5, and 2.0, and 4 and 8 hour state horizons.

## Result

The exact head research workflow evaluated 12 frozen state variants across 10 symbols with complete data.

- state variants: 12
- state passes: 0
- economic rows evaluated: 0
- primary economic passes: 0

Because no state variant satisfied the predeclared state gate, the strategy translation layer remained closed. Fees, funding, reversed direction, placebo, clustered randomization, MAE/MFE, stop and RR research were therefore not used to rescue the family.

## Validity and execution gates

Exact head workflow run `34901389729` completed successfully. CI, Ruflo Meta Harness Compatibility, and Multi Agent Hardening also passed on the same PR head before this outcome was recorded.

Evidence artifact: `basis-convergence-v1`, artifact ID `10371341106`, SHA256 `862050f8c31f44233ed34563faa66a70964b8e7a29fa6d90049c88c8d36a653a`.

## Conclusion

Observed MEXC fair price versus index price basis did not demonstrate the frozen predictive basis convergence state relationship strongly enough to reach economic testing. This lane is rejected under v1.

No profitable edge is established. No untouched OOS claim is made. No candidate freeze, paper promotion, or live order transmission is supported.
