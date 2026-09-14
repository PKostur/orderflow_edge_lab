# Strategy Discovery v4 — Funding/Basis Carry Development Conclusion

## Status

Development-only conclusion. The locked internal holdout remains unopened. Leverage remains untested. No verified-OOS, profitable-edge, or live-execution claim is made.

## Canonical evidence

The canonical GitHub evaluation reused the immutable public-MEXC carry dataset produced by workflow run `34875908501` and reproduced the frozen development precheck exactly.

- single-symbol strategy cells: 122
- cross-sectional funding-spread cells: 18
- state-screen passes: 10 single-symbol, 18 cross-sectional
- full preliminary economic passes: 0 single-symbol, 0 cross-sectional
- locked holdout opened: false
- leverage tested: false

The canonical evaluator is `scripts/run_carry_v4_development.py`. The canonical workflow is `.github/workflows/strategy-discovery-v4-carry-eval.yml`; workflow run `34880103885` completed successfully on source head `93aa6cfb8852e5fc3b36572f417f1a83ece0dcd7`, including exact-metric reproduction and deterministic release-manager checks.

## Strongest state finding

Funding persistence is forecastable enough to pass the predeclared state screen in multiple cells. A representative positive-funding carry cell (current funding >= 5e-5, nonnegative basis, 24h hold) has positive funding-state association but remains economically negative after realistic two-leg spot/perpetual friction.

This establishes a state relationship, not a tradeable edge.

## Best economic near-miss

The strongest development cell is the cross-sectional funding-spread portfolio:

- top/bottom k: 2
- funding lookback: 5 settlements
- hold: 72h
- state median Spearman: +0.2308915864
- positive state folds: 13/15
- trades: 89
- primary-cost median fold net expectancy: +6.757970357 bps
- primary-cost median fold PF: 1.129761394
- high-cost median fold net expectancy: +2.757970357 bps
- positive economic folds: 8/15 = 53.33%

The frozen development gate requires at least 60% positive folds (9/15). The candidate therefore fails and cannot open the holdout. The threshold is not relaxed after seeing the near-miss.

## Decision

Strategy Discovery v4 carry is stopped at the development stage. The result is useful: public MEXC funding contains persistent information and a cross-sectional funding spread can show positive average economics, but temporal stability is insufficient under the frozen gate.

Any future carry version must be structurally new and predeclared independently—for example execution economics based on legitimately modeled maker fills, explicit funding-event timing, or materially longer carry horizons. It must not be a post-hoc relaxation or threshold tweak around the 8/15-fold result.
