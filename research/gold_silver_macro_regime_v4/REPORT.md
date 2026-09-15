# Gold/Silver Macro Regime v4 — State Study Result

## Evidence boundary

This is a **post-observation retrospective state study**, not future OOS and not a PnL backtest.

Protocol frozen before scoring at `dc729de4d92aca1b7104315e8977e81b12e497e1`.

Canonical workflow run: `34971546645`

Canonical source head: `83d29df3eb4774d63f6628b83b3ca6657fa285b9`

Artifact: `gold-silver-macro-regime-v4` (`10396524884`)

Artifact digest: `sha256:01eee6f6b030d4d6be633733e72f2655fec7cbe1c540016a2fe778d9e23a75be`

2021-2023 locked validation and the 2024-2026 retrospective extension remained unopened. No conditioned PnL, leverage, shadow, or live execution was tested.

## Frozen question

v1-v3 repeatedly found gold/silver convergence-state information but asymmetric executable returns. v4 asked whether lagged real-yield and VIX state explains that asymmetry strongly enough to become a causal conditioner.

The v3 relationship model was fixed rather than re-searched: recursive log-price equilibrium, lambda 0.995, |innovation z| >= 1.5. Six macro features were tested separately on long-spread and short-spread dislocations, for 12 hypotheses total, using one-trading-day-lagged FRED data, 126-day dependence folds, 20,000 sign flips, and BH-FDR q <= 0.10.

## Canonical outcome

- development price rows: **2,834**
- complete macro-feature coverage: **94.81%**
- dislocation events: **290**
- hypotheses: **12**
- state passes: **0**
- state conditioners frozen: **0**
- conditioned PnL tested: **false**

### Baseline asymmetry

The asymmetry exists before macro conditioning:

- long-spread side: **29 events**, **5 folds**, median fold convergence target **+1.0766**, positive target folds **100%**
- short-spread side: **261 events**, **12 folds**, median fold convergence target **-0.0153**, positive target folds **50%**

Thus the fixed adaptive relationship model itself generates a highly unbalanced side distribution.

### Macro-condition results

No lagged real-yield or VIX feature survives the frozen state gate.

Long-spread feature point estimates are sometimes positive, including the safe-haven composite (median fold Spearman about **+0.627**), but the side has only **2 scorable feature folds** after the minimum-event rule, far below the required 10-fold breadth. These are therefore sparse observations, not promotable evidence.

The short-spread side has adequate breadth (11 scorable folds for the macro features), but none shows robust positive aligned predictability. Examples:

- VIX level aligned predictor: median fold Spearman about **-0.105**, q = **1.0**
- real-yield 21-day change aligned predictor: median fold Spearman about **+0.183**, positive-rho folds **54.5%**, q about **0.753**
- safe-haven composite: median fold Spearman about **+0.156**, positive-rho folds **54.5%**, q about **0.753**

## Decision

**Reject lagged real-yield/VIX conditioning as the explanation for the observed gold/silver side asymmetry.**

Do not:

- lower the fold-breadth requirement around the sparse long-spread observations;
- score conditioned PnL from these macro features;
- open 2021-2023 validation;
- inspect 2024-2026 for this protocol;
- test leverage or authorize live execution.

The next admissible mechanism is a separately frozen **quantile/threshold asymmetric relationship study**. It should test lower-tail and upper-tail residual states directly, because both the project evidence and published gold/silver literature indicate that the relationship can be nonlinear, state-dependent, and asymmetric.

## Claims

- macro explanation established: **false**
- conditioned PnL tested: **false**
- verified future OOS: **false**
- profitable edge established: **false**
- leverage authorized: **false**
- live enabled: **false**
