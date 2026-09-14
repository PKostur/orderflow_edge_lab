# Two-Leg Relative Value V1

## Purpose

This protocol tests whether BTC-relative information can be monetized more faithfully as a genuinely hedged two-leg portfolio rather than as a single-leg altcoin trade conditioned on BTC.

It is a new development protocol. It does not alter `discovery-v1`, `regime-research-v1`, or the completed strategy-discovery-v2.1.x definitions.

## Research order

1. Estimate causal BTC/alt relative-value state using only completed bars.
2. Test whether the state predicts future spread continuation or reversion and whether the rolling beta remains stable.
3. Only state-screen passers may reach portfolio PnL translation.
4. Translate the frozen state into simultaneous alt and BTC legs with beta-normalized gross notional.
5. Apply execution cost to both legs.
6. Compare against reversed direction, BTC-leg-removed single-leg, and beta-equals-one controls.
7. Require temporal-fold and cross-symbol breadth. Do not select the highest development PF.
8. Run MAE/MFE and stop-path research only after an economic candidate clears the frozen screen.
9. Require genuine future-after-freeze evidence before any OOS or profitable-edge claim.

## Primary pods

The smallest active pod set is BTC/cross-asset context, mean reversion or trend/structure as applicable, execution economics, research validity/statistics, indicator orthogonality, risk path, data integrity, reliability/observability, transfer/generalization, and adversarial lead.

## Dependence

Calendar 21-day folds are the dependence clusters. A portfolio entry and its exit must remain inside the same fold. Cross-pair breadth is supporting generalization evidence and is not untouched OOS validation.

## Costs

The frozen sensitivity cases are 6, 8, and 10 bps round-trip per leg, with 8 bps per leg primary. Costs are applied to each leg's gross-notional weight. Funding is included only if legitimate historical funding observations are available. Missing funding must never be imputed or invented.

## Promotion boundary

No live transmission is added by this protocol. Promotion requires candidate freeze, holdout audit, genuine future-after-freeze validation, paper/shadow reliability, reconciliation, Ruflo meta-harness success, deterministic orderflow-multi-agent release-manager success, and separate user approval for any live connectivity.

The March 1 through September 12, 2026 development period has already informed the research program and cannot serve as untouched OOS evidence.
