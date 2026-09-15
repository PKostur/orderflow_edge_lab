# Gold/Silver Quantile Threshold v5 — State Study Result

## Evidence boundary

This is a **post-observation retrospective state study**, not future OOS and not a PnL backtest.

Protocol frozen before scoring at `616206d66ec90d8ef437044cce56fd2a9f7e5f02`.

Canonical workflow run: `34971949834`

Canonical source head: `7ad61be69c5cd331a6e656f7b281e1a8929eaf46`

Artifact: `gold-silver-quantile-threshold-v5` (`10397384289`)

Artifact digest: `sha256:3c94b8994410de91d5a8acef947ffd1c5222acaa07da7c639767cbf020007dce`

No PnL, validation, later-era extension, leverage, shadow, or live execution was opened.

## Frozen question

Does a causal rolling gold/silver residual have asymmetric lower-tail versus upper-tail convergence dynamics when tail states are defined by empirical residual quantiles rather than symmetric z thresholds?

The relationship model was fixed at trailing 252-day OLS on log prices. Four state hypotheses were tested: lower 10%, lower 20%, upper 80%, upper 90%. Predictor was tail depth and target was 21-day side-adjusted residual convergence. The gate required breadth across 126-calendar-day dependence folds, positive median convergence, positive depth/convergence association, 20,000 sign flips, and BH-FDR q <= 0.10.

## Outcome

- hypotheses: **4**
- state passes: **0**
- state tails frozen: **0**
- PnL tested: **false**

### Lower 20% tail

`lower_q20` is the strongest lower-tail result:

- events: **331**
- scorable folds: **10**
- median fold Spearman: **+0.5683**
- positive Spearman folds: **100%**
- sign-flip p: **0.01595**
- BH-FDR q: **0.02127**
- median fold convergence target: **+1.0644**
- positive target folds: **80%**

It fails because the frozen breadth requirement is 12 scorable folds. The requirement is not relaxed after inspection.

### Lower 10% tail

- events: **197**
- scorable folds: **8**
- median fold Spearman: **+0.5998**
- positive Spearman folds: **100%**
- q: **0.03070**
- median fold target: **+1.0227**
- positive target folds: **75%**

Again, statistical point estimates are strong but breadth is insufficient.

### Upper tails

`upper_q80` has broad coverage and significant tail-depth association:

- events: **706**
- scorable folds: **20**
- median fold Spearman: **+0.3621**
- positive Spearman folds: **85%**
- q: **0.02127**

But median convergence is small (**+0.0818**) and only **55%** of target folds are positive, below the frozen 60% requirement.

`upper_q90` similarly has significant depth association but a **negative** median convergence target and only **46.7%** positive target folds.

## Interpretation

v5 does not authorize a tail strategy. It does show that the lower tail contains a strong but breadth-limited convergence pattern, while the upper tail does not exhibit stable positive convergence despite significant within-tail depth relationships.

A remaining statistical question is distinct from v5: threshold/error-correction models predict a shift in conditional adjustment **after crossing a threshold**, not necessarily a monotonic relationship between tail depth and subsequent convergence. A separately frozen study may therefore test fold-level tail-state convergence relative to a same-side non-tail baseline without using tail depth as the predictor.

## Claims

- quantile-tail state pass: **false**
- PnL tested: **false**
- verified future OOS: **false**
- profitable edge established: **false**
- leverage authorized: **false**
- live enabled: **false**
