# Residual Right-Tail State Discovery v1

## Evidence status

Post-selection state discovery downstream of strategy-discovery-v2.1.3. The source strategy and all ten source PnL folds were already inspected before this study. Folds 7-9 were locked only from this new feature/model search; they are not untouched OOS evidence. No profitable-edge, OOS, or live claim is made.

Source strategy: 1h `rolling_beta_spread_momentum`, regression window 192, |z| >= 1.5, hold 8 bars. Exact source trade count reproduced: **1,616**.

## Frozen experiment

The protocol was frozen in `config/residual_right_tail_state_v1.json` before new state results were computed.

- Development folds: 0-6.
- Feature-selection-locked folds: 7-9.
- 6 predeclared feature sets covering residual geometry, BTC regime, asset regime, relative/cross-sectional regime, and session context.
- 144 core epochs total: 72 continuous-target model variants and 72 binary right-tail model variants.
- No strategy PnL was used to select features or models.
- Family winners were subjected to 10,000 target permutations within symbol x 21-day development dependence cluster.
- Frozen adversarial significance gate: p < 0.01.

## Continuous target

Target: signed 8h beta-neutral residual continuation, aligned to the source residual-momentum direction.

**0/72 continuous epochs passed the development gate.**

The best continuous epoch was a CORE Ridge model (`alpha=100`) with development median fold Spearman **+0.0483** and positive correlation in **4/7** development folds. It therefore missed the predeclared development gate before the locked data was considered.

On locked folds 7-9 its Spearman correlations were approximately **+0.074, -0.049, -0.006**, median **-0.006**. The 10,000-permutation p-value was approximately **0.1285**. Continuous residual-continuation magnitude is rejected for this information set.

## Binary right-tail target

Target: whether signed beta-neutral residual continuation exceeded the training-only 80th percentile.

**57/72 binary epochs passed the initial development gate.** This looked encouraging before the adversarial control.

The frozen winner rule selected the simplest model within 0.01 of the highest development AUC:

- feature set: residual geometry only (`R`), 11 features;
- model: Random Forest, 120 trees, max depth 3, minimum leaf 20;
- development median fold AUC: **0.6393**;
- AUC > 0.5 in **7/7** development folds;
- median top-quintile lift: **1.437x**.

Locked folds 7-9 produced AUCs of approximately **0.681, 0.522, 0.582**, median **0.582**, so the model passed the feature-search-locked support rule.

However, the dependence-preserving adversarial test rejected the model. With the target permuted only within each symbol x 21-day development cluster, the null median AUC was already approximately **0.600**, its 95th percentile approximately **0.635**, and the observed 0.639 development AUC had **p = 0.0317**. This fails the frozen p < 0.01 gate.

Interpretation: much of the apparent classification power is attributable to symbol/fold-level tail-event prevalence and regime structure rather than sufficiently strong within-regime discrimination. The model therefore cannot be translated back into the trading strategy under this protocol.

## Symbol diagnostic

Leave-one-symbol-out AUCs for the binary winner were positive on all nine symbols but varied materially, approximately 0.576 to 0.816. This remains a diagnostic only because simultaneous symbols do not create independent time evidence.

## Marginal state observations

The largest development-fold median marginal associations with continuous signed residual continuation were still modest. Residual acceleration, residual z, local range, BTC volume state, residual volatility and cross-sectional residual dispersion were among the largest absolute associations, generally around |rho| 0.07-0.12. None establishes an independent predictive feature.

## Conclusion

The v1 search does **not** establish a state discriminator for the right-tail winners. The apparent binary signal survives the three feature-search-locked folds but fails the stricter dependence-preserving permutation gate because the null itself carries substantial symbol/fold structure.

The next version must remove that source of pseudo-predictability rather than tune the rejected model. v1.1 should make within-symbol/time-regime discrimination the primary objective, using chronological walk-forward folds and group-relative or within-cell ranking metrics. No v1 threshold, model, or PnL gate should be promoted.

Claims remain: post-selection development research only; no verified OOS; no profitable edge established; live execution disabled.
