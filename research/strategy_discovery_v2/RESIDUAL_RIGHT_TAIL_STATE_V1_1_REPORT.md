# Residual Right-Tail State Discovery v1.1

## Status

Post-selection development diagnostic only. No verified OOS, profitable-edge, or live claim.

v1.1 was predeclared after v1 showed that a globally scored binary classifier could inherit substantial symbol/fold event-prevalence structure. v1.1 therefore used chronological expanding walk-forward tests and made within-symbol prediction the primary score.

## Protocol

Frozen config: `config/residual_right_tail_state_v1_1.json`.

- Exact same 1,616 source signals from the 1h rolling-beta-spread momentum cell.
- 144 core epochs.
- Training for test fold k used only folds < k.
- Intended test folds: 4-9.
- Continuous fold score: median of per-symbol Spearman correlations.
- Binary fold score: median of per-symbol ROC AUCs, with each symbol's 80th-percentile event threshold fit only on training data.
- Minimum six scorable symbol cells per test fold.
- 20,000 within-symbol x test-fold target permutations for each frozen family winner.
- No PnL translation permitted in v1.1.

## Structural caveat

Fold 9 contained only 64 source trades and did not provide enough symbols with the frozen minimum eight observations per cell. It therefore could not produce the required six within-symbol cells. The runner excluded it rather than weakening the cell-size rule.

As a result, the primary diagnostic contains five scorable chronological folds (4-8), not the six intended in the config. This prevents any promotion from v1.1 even if the numerical gates had otherwise aligned.

## Continuous target

Two of 72 continuous epochs passed the walk-forward development gate.

The frozen winner was:

- feature set: `R_X` (residual geometry + relative regime + cross-sectional state), 21 features;
- model: HistGradientBoosting, 120 iterations, 15 leaves, learning rate 0.05;
- median within-symbol fold Spearman: **+0.0996**;
- positive test-fold fraction: **4/5**.

Scorable chronological fold medians were approximately:

- fold 4: +0.047
- fold 5: -0.142
- fold 6: +0.100
- fold 7: +0.128
- fold 8: +0.125

The 20,000-permutation adversarial test produced null median approximately 0.000, null 95th percentile approximately +0.084, and **p ≈ 0.0259**. This fails the frozen p < 0.01 adversarial gate.

## Binary target

Four of 72 binary epochs passed the raw walk-forward gate, but the frozen winner rule selected the simpler model within 0.01 of the highest primary metric:

- feature set: `CORE`, 41 features;
- model: Logistic Regression, C=0.5;
- median within-symbol fold AUC: **0.5897**.

Scorable chronological fold medians were approximately:

- fold 4: 0.367
- fold 5: 0.489
- fold 6: 0.621
- fold 7: 0.639
- fold 8: 0.590

Only **3/5** scorable folds were above 0.5, below the frozen stability requirement. Therefore the winner fails the development gate.

Its adversarial result was nevertheless informative: 20,000 within-symbol x fold permutations produced null median AUC **0.500**, null 95th percentile approximately **0.560**, observed 0.590, and **p ≈ 0.00755**. Removing the v1 group-prevalence confound therefore moved the null back to chance, but the apparent signal was not temporally stable enough.

## Interpretable marginal observations

Within symbol x time cells, the largest median marginal associations with continuous future residual continuation included:

- cross-sectional share of positive 4h returns: rho ≈ **+0.122**;
- BTC 4h return: rho ≈ **+0.106**;
- BTC 24h realized volatility: rho ≈ **+0.105**;
- BTC 48h realized volatility: rho ≈ +0.080;
- BTC 24h return: rho ≈ +0.078;
- residual absolute cross-sectional rank: rho ≈ -0.081;
- local range state: rho ≈ -0.077.

These are hypothesis-generating observations, not independently validated features.

## Conclusion

No v1.1 model satisfies all predeclared validity conditions. Continuous prediction is temporally fairly consistent but not adversarially significant at the frozen level. Binary tail-event prediction clears the adversarial test but fails chronological stability. Fold 9 is structurally too small for the intended within-symbol scoring design.

The correct next step is not additional tuning on these same ten folds. The most informative next test is an independent historical replication period using a small frozen hypothesis set centered on the strongest v1.1 market-state observations (cross-sectional breadth and BTC trend/volatility), while preserving the source strategy and within-symbol chronological scoring. That replication must remain separate from future-after-freeze OOS evidence.
