# Gold/Silver Pair-Regime v5 — Development Result

## Evidence boundary

This is a **post-observation retrospective development study**, not future OOS.

The protocol was frozen before scoring at commit `aa771fdb5e47039357368bc4232d3c491dcc98db`.

Canonical development workflow run: `34959192084`

Canonical source head: `d63bb5e0fbdb449d9a2233e75dcab4dc6a2fc48f`

Artifact: `gold-silver-pair-regime-v5` (`10392307411`)

Artifact digest: `sha256:5188afa0d62f1b51dbbf6d171cd79cf7dead7648efaf7ff64c2038fe9a7b76ed`

The locked 2021-2023 validation and 2024-2026 retrospective extension were **not opened**.

## Question

After v2-v4 showed strong pair-state information but poor executable symmetry, v5 tested whether causal pair-internal conditions could decide whether an extreme adaptive XAU/XAG dislocation should **revert or continue**.

Positive predeclared feature scores were defined as reversion support. The state target was the future 21-day payoff of the mean-reversion pair direction. Economic translation used score > 0 => mean reversion and score < 0 => continuation.

## Frozen state hypotheses

Five pair-regime features were tested:

1. trailing 21-day pair trend reversion support;
2. prior-five-innovation reversal support;
3. low 21-day pair-volatility support;
4. stable-beta support;
5. equal-weight combination of the four.

All were causally standardized using prior 252-trading-day history.

## Canonical outcome

- unique state hypotheses: **5**
- state passes: **0**
- economic cells: **20**
- economic passes before neighborhood: **0**
- full development passes: **0**
- candidates frozen: **0**

### Predeclared state results

| Feature | Events | Folds | Median rho | Positive folds | p | q | Pass |
|---|---:|---:|---:|---:|---:|---:|---|
| trend reversion support 21 | 196 | 11 | **-0.620588** | 18.18% | 1.0 | 1.0 | no |
| innovation reversal support 5 | 196 | 11 | **-0.470588** | 27.27% | 1.0 | 1.0 | no |
| low pair volatility support 21 | 196 | 11 | **-0.281818** | 27.27% | 1.0 | 1.0 | no |
| stable beta support 21 | 196 | 11 | **-0.257397** | 27.27% | 1.0 | 1.0 | no |
| equal-weight pair-regime support | 196 | 11 | **-0.380952** | 9.09% | 1.0 | 1.0 | no |

Every predeclared feature points in the opposite direction from its frozen semantic definition. Therefore v5, as specified, is rejected and no economic cell can qualify.

### Economic diagnostics

No economic cell passes. Some aggregate means are positive, but the same directional asymmetry remains.

For example, `trend_reversion_support_21__threshold0p5__hold21` has:

- 19 trades
- median-fold net at 10 bps: **-30.14 bps**
- median-fold PF: **0.284**
- positive economic folds: **42.86%**
- overall mean: **+33.39 bps/trade**
- long-gold/short-silver subset mean: **+115.99 bps/trade**
- short-gold/long-silver subset mean: **-108.22 bps/trade**
- regime decisions: **2 reversion / 17 continuation**

Thus aggregate positive means in isolated cells do not overturn the frozen state failure or the pair-direction concentration problem.

## Post-observation sign diagnostic — hypothesis generation only

After v5 was complete, the uniformly negative state correlations were inspected as a diagnostic. This **cannot** convert v5 into a pass.

If the feature signs are reversed, the strongest development relationships would be:

- trend feature reversed: median rho **+0.620588**, 9/11 positive folds;
- equal-weight feature reversed: median rho **+0.380952**, 10/11 positive folds.

A post-hoc reversed-sign permutation diagnostic suggests these two relationships are interesting enough to generate a new hypothesis, but those numbers are not valid v5 evidence because the sign was chosen after observing v5.

The economic interpretation of the reversed trend feature is **trend exhaustion**: when an extreme adaptive dislocation extends the established 21-day pair trend, mean reversion may be more likely; when an extreme dislocation runs against the established trend, continuation may be more likely.

## Decision

**Reject v5 as predeclared.**

The only admissible continuation is to freeze the sign-reversed trend-exhaustion hypothesis as a new research version and test it on a separate period. The 2010-2020 development sample must not be reused to claim confirmation.

Therefore:

- do not open 2021-2023 under the v5 protocol;
- do not treat the post-hoc sign reversal as a v5 pass;
- do not test leverage;
- do not authorize future shadow or live execution.

## Claims

- predeclared pair-regime v5 state edge: **no**
- post-observation trend-exhaustion hypothesis generated: **yes**
- executable v5 development edge: **no**
- locked internal validation opened: **false**
- verified future OOS: **false**
- profitable edge established: **false**
- leverage authorized: **false**
- live enabled: **false**
