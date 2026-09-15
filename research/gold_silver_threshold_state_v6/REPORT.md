# Gold/Silver Threshold State v6 — State Study Result

## Evidence boundary

This is a **post-observation retrospective state study**, not future OOS and not a PnL backtest.

Protocol frozen before scoring at `ffeac8a7c0c83ece0c5a8c6677edd8983cce6030`.

Canonical workflow run: `34972427739`

Canonical source head: `401d477ae69040f7c23389c9a099b499293be6ab`

Artifact: `gold-silver-threshold-state-v6` (`10397502697`)

Artifact digest: `sha256:3d3c0ba7f32f9c779fab90c9e56451ab9d9162a954b3aff6001092637ae19286`

No PnL, locked validation, later-era extension, leverage, shadow, or live execution was opened.

## Frozen question

v5 tested whether deeper residual-tail observations monotonically predicted faster convergence. v6 instead tested the threshold-state hypothesis directly: within each dependence fold, does crossing a causal empirical residual threshold change the **average convergence** versus same-side non-tail states?

The relationship model was fixed at trailing 252-day OLS on log prices. Four tail hypotheses were tested: lower 10%, lower 20%, upper 80%, upper 90%. Dependence clusters were 252 calendar days. Each scorable fold required at least 8 tail events and 20 same-side non-tail baseline events. The primary statistic was median tail convergence minus median same-side non-tail convergence; 20,000 fold sign flips and BH-FDR controlled multiplicity.

## Canonical outcome

- hypotheses: **4**
- state passes: **0**
- state tails frozen: **0**
- PnL tested: **false**

### Lower 10% tail

- same-side events: **823**
- tail events: **247**
- scorable folds: **8**
- median fold tail effect: **+0.9506**
- positive tail-effect folds: **100%**
- sign-flip p: **0.03030**
- BH-FDR q: **0.11609**
- median tail target: **+1.0227**
- positive tail-target folds: **87.5%**

This is the strongest economic-looking state result but fails both the frozen 10-fold breadth requirement and q <= 0.10 after four-hypothesis correction.

### Lower 20% tail

- same-side events: **823**
- tail events: **418**
- scorable folds: **7**
- median fold tail effect: **+1.0265**
- positive tail-effect folds: **85.7%**
- sign-flip p: **0.05805**
- BH-FDR q: **0.11609**
- median tail target: **+1.0487**
- positive tail-target folds: **100%**

It also fails breadth and multiplicity correction.

### Upper 80% tail

- same-side events: **1,352**
- tail events: **764**
- scorable folds: **10**
- median fold tail effect: **+0.0943**
- positive tail-effect folds: **60%**
- sign-flip p: **0.33138**
- BH-FDR q: **0.33138**
- median tail target: **+0.1280**
- positive tail-target folds: **60%**

It has adequate breadth but fails the effect-stability and FDR gates.

### Upper 90% tail

- same-side events: **1,352**
- tail events: **565**
- scorable folds: **10**
- median fold tail effect: **+0.1734**
- positive tail-effect folds: **70%**
- sign-flip p: **0.27894**
- BH-FDR q: **0.33138**
- median tail target: **+0.0041**
- positive tail-target folds: **50%**

It also fails.

## Decision

**Reject v6.** Do not relax q=0.10, fold breadth, or target-stability requirements around the lower-tail near-miss.

Across ratio-z, static residual, adaptive equilibrium, macro conditioning, empirical tail-depth, and threshold-state formulations, gold/silver relative-value has repeatedly shown interesting state structure without a complete robust state-to-executable-edge chain. This research family is therefore paused rather than retuned further.

The next gold lane should be structurally orthogonal: intraday **cross-session return transmission** in XAUUSD, tested state-first before any economic translation.

## Claims

- threshold-state pass: **false**
- PnL tested: **false**
- verified future OOS: **false**
- profitable edge established: **false**
- leverage authorized: **false**
- live enabled: **false**
