# Self Improvement v1: 20 Epoch Pilot

This report records a PnL-independent state-prediction experiment over existing order-flow evidence. It does not modify `discovery-v1` or `regime-research-v1`, does not establish untouched OOS evidence, and does not authorize live execution.

## Design

Nine independent capture batches were used for grouped development scoring. The newest three batches were locked before model selection. Twenty epochs were predeclared across four state targets and five model/feature configurations per target. One winner per target family was selected by median leave-one-batch-out Spearman correlation, then evaluated once on the locked three-batch holdout.

## Development epochs

| Epoch | Family | Model | Feature set | Median Spearman | Positive batches | Median nMAE |
|---:|---|---|---|---:|---:|---:|
| 1 | directionality_chop | ridge | directionality_primary | +0.037 | 67% | 0.570 |
| 2 | directionality_chop | ridge | directionality_domain | -0.004 | 44% | 0.569 |
| 3 | directionality_chop | elastic_net | orthogonal_core | -0.019 | 33% | 0.571 |
| 4 | directionality_chop | random_forest | orthogonal_core | -0.053 | 22% | 0.582 |
| 5 | directionality_chop | hist_gradient_boosting | orthogonal_core | -0.043 | 22% | 0.587 |
| 6 | volatility_expansion | ridge | volatility_primary | +0.239 | 100% | 0.829 |
| 7 | volatility_expansion | ridge | volatility_domain | +0.269 | 100% | 0.808 |
| 8 | volatility_expansion | elastic_net | orthogonal_core | +0.215 | 100% | 0.820 |
| 9 | volatility_expansion | random_forest | orthogonal_core | +0.261 | 100% | 0.790 |
| 10 | volatility_expansion | hist_gradient_boosting | orthogonal_core | +0.213 | 100% | 0.866 |
| 11 | liquidity_deterioration | ridge | liquidity_primary | +0.019 | 78% | 0.680 |
| 12 | liquidity_deterioration | ridge | liquidity_domain | -0.009 | 44% | 0.679 |
| 13 | liquidity_deterioration | elastic_net | orthogonal_core | +0.222 | 100% | 0.687 |
| 14 | liquidity_deterioration | random_forest | orthogonal_core | +0.297 | 100% | 0.678 |
| 15 | liquidity_deterioration | hist_gradient_boosting | orthogonal_core | +0.305 | 100% | 0.699 |
| 16 | future_direction | ridge | direction_primary | -0.071 | 22% | 0.639 |
| 17 | future_direction | ridge | direction_domain | +0.047 | 78% | 0.647 |
| 18 | future_direction | elastic_net | orthogonal_core | +0.120 | 89% | 0.652 |
| 19 | future_direction | random_forest | orthogonal_core | +0.106 | 56% | 0.650 |
| 20 | future_direction | hist_gradient_boosting | orthogonal_core | +0.041 | 67% | 0.683 |

## Locked holdout results

| Family | Winner | Dev median rho | Holdout median rho | Positive holdout batches | Interpretation |
|---|---|---:|---:|---:|---|
| directionality_chop | E01 ridge | +0.037 | +0.187 | 67% | Weak. Not promoted. |
| volatility_expansion | E07 ridge | +0.269 | +0.253 | 100% | Replicated state signal. Requires forward validation. |
| liquidity_deterioration | E15 hist_gradient_boosting | +0.305 | +0.327 | 100% | Strongest pilot result. Nonlinear multivariate signal. Requires orthogonality/adversarial follow-up and future OOS. |
| future_direction | E18 elastic_net | +0.120 | -0.070 | 33% | Failed holdout. Reject for this cycle. |

## Research conclusions

The pilot improved state prediction most clearly for volatility expansion and liquidity deterioration. The future-direction model showed development improvement but failed on the locked batches, so it is rejected rather than tuned against the holdout. No strategy PnL was used to choose any epoch. The three-batch holdout is an internal existing-data holdout and must not be described as genuine untouched OOS evidence.
