# Two-Leg Relative Value V1 Development Report

## Status

Development-only evidence. No untouched OOS claim. No profitable-edge claim. No paper or live promotion.

Protocol: `two-leg-relative-value-v1` with pre-outcome implementation amendment `two-leg-relative-value-v1.1-amendment`.

Base research commit: `4a39c1d762c5e43a875a4254d7879b92cac09c36`.

Exact evaluated PR head: `44b9e5e831b3982688b06a8b4e7ffb087cf105cc` via PR merge ref `17ec1b961061ae8fc9431723bcce18e40b99bf91`.

Workflow run: `34871193022`.

Artifact: `two-leg-relative-value-v1-17ec1b961061ae8fc9431723bcce18e40b99bf91`, artifact ID `10359062726`, SHA-256 `8abb57a12653e096b51e6051928ec7e6718e28f2852cd41351f7f7aeb4894923`.

## State layer

All 36 frozen state variants cleared the deliberately permissive state screen. Rolling log-price residual variants had median fold reversion Spearman values roughly 0.23 to 0.44. Rolling return beta-residual variants were materially stronger, with several median fold reversion Spearman values above 0.8. The state screen therefore supports the narrow statement that the constructed residual-state variables contain information about subsequent change in the same residual construction on the development sample.

This is not treated as independent trading alpha. The predictor and target are mathematically related residual constructions, so the universal pass is vulnerable to construction-induced mean-reversion and overlapping-state interpretation. It is retained as state evidence only and is not sufficient for promotion.

Feature-association diagnostics found the largest median redundancy between BTC and alt realized volatility, absolute Spearman about 0.747. The remaining median feature associations were materially lower. No multi-feature combination was introduced in v1.

## Portfolio economics

Only state-pass variants entered the portfolio layer. There were 108 frozen economic variants across 6, 8 and 10 bps round-trip cost per leg cases.

Economic passes after the neighborhood gate: **0 / 108**.

Primary-cost base passes at 8 bps per leg: **0**.

The strongest primary-cost row was:

- family: `rolling_return_beta_residual`
- beta window: 96 bars
- residual lookback: 4 bars
- threshold: 2.0
- hold: 8 bars
- exit: fixed-time
- trades: 956
- folds: 10
- symbols: 9
- median fold net expectancy: about **-0.702 bps/trade**
- median fold PF: about **0.966**
- positive folds: **3 / 10**
- positive symbols: **2 / 9**
- reversed median fold expectancy: about **-15.30 bps/trade**
- single-leg median fold expectancy: about **-4.14 bps/trade**
- beta=1 median fold expectancy: about **-2.91 bps/trade**
- within-symbol-fold randomized-direction permutation p-value: about **0.0040**
- permutation 95th percentile median-fold expectancy: about **-3.56 bps/trade**

The original direction therefore contains detectable directional information relative to the randomized and reversed controls, but the magnitude is insufficient to overcome the frozen executable cost model. The beta-weighted hedge improves this cell relative to its single-leg and beta=1 controls, yet it remains net negative and unstable across folds and symbols.

No stop, RR, leverage, feature-combination or parameter rescue is permitted because the primary economic screen failed.

## Research conclusion

The two-leg BTC hedge changes the payoff structure and preserves more of the relative-value signal than the equivalent single-leg expression in the strongest cell, but it does not establish executable positive expectancy at the frozen primary cost assumption. The family is rejected for candidate freeze and forward promotion in v1.

The state result may be used only as a hypothesis generator for a separately versioned future protocol. Any future protocol must be frozen before inspecting new evidence, must avoid choosing features or residual definitions by this PnL result, and must continue to separate state prediction from strategy economics.

MAE/MFE stop research is not triggered. Candidate freeze is not triggered. Holdout audit is not triggered. Paper/shadow promotion is not triggered. Automatic live transmission remains disabled.
