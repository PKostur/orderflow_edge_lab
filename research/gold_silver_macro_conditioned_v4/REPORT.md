# Gold/Silver Macro-Conditioned Relative Value v4 — Development Result

## Evidence boundary

This is a **post-observation retrospective development study**, not future OOS.

The protocol was frozen before scoring at commit `c7822184a5a42e23fb276e78cd795d19ffb9ab4e`.

Canonical development workflow run: `34958775758`

Canonical source head: `0ed7c932f9b3a8fdbd3d3be9f059df5dd5b9c7f0`

Artifact: `gold-silver-macro-conditioned-v4` (`10392680714`)

Artifact digest: `sha256:86681150ce6aa545049fb118d1ca6ea5c9f0b851cea8afb43c2c8ef61ffef088`

The locked 2021-2023 validation and 2024-2026 retrospective extension were **not opened**.

## Question

v2 and v3 repeatedly found strong gold/silver relative-state information but an asymmetric executable outcome: long-gold/short-silver relative trades were often positive while the reverse sleeve was negative. v4 tested whether strictly lagged macro state could explain that asymmetry and choose the relative direction without post-hoc deleting shorts.

## Frozen macro hypotheses

All macro observations are strictly earlier than the pair signal date.

1. falling real-yield support: negative standardized 21-day change in DFII10;
2. weaker-USD support: negative standardized 21-day log change in DTWEXBGS;
3. rising-breakeven support: positive standardized 21-day change in DGS10 minus DFII10;
4. equal-weight macro support: arithmetic mean of those three.

Macro values are standardized causally against prior 252-trading-day history. Positive score predicts gold outperforming silver; negative score predicts silver outperforming gold.

Pair events are fixed from v3's strongest **state** configuration, not from PnL: RLS lambda 0.995 and |pre-update innovation z| >= 1.5.

## State-first outcome

- unique macro hypotheses: **4**
- pair-event observations per feature: **290**
- scorable dependence folds per feature: **13**
- state passes: **0**

### Falling real-yield support

- median fold Spearman: **+0.281891**
- positive folds: **7/13 = 53.85%**
- sign-flip p: **0.091245**
- BH-FDR q: **0.342683**
- result: **FAIL**

### Weaker-USD support

- median fold Spearman: **+0.129412**
- positive folds: **8/13 = 61.54%**
- sign-flip p: **0.171341**
- BH-FDR q: **0.342683**
- result: **FAIL**

### Rising-breakeven support

- median fold Spearman: **-0.031145**
- positive folds: **6/13 = 46.15%**
- sign-flip p: **1.000000**
- BH-FDR q: **1.000000**
- result: **FAIL**

### Equal-weight macro support

- median fold Spearman: **+0.028571**
- positive folds: **7/13 = 53.85%**
- sign-flip p: **0.380981**
- BH-FDR q: **0.507975**
- result: **FAIL**

Thus none of the four causal macro features robustly predicts the signed future hedged XAU/XAG return after an extreme pair dislocation.

## Economic translations

The protocol contained 16 predeclared cells: four macro features x two score thresholds x two holding periods.

- economic passes before neighborhood: **0**
- full development passes: **0**
- candidates frozen: **0**

Economic cells cannot qualify because their parent state feature failed. Their diagnostics also reinforce the earlier directional-asymmetry warning rather than overturning it.

For example, falling-real-yield support with |score| >= 0.5 and 42-day hold has:

- 16 non-overlapping trades
- median-fold net at 10 bps: **-72.61 bps**
- median-fold PF: **0.0**
- positive economic folds: **40%**
- overall mean: **+92.86 bps/trade**, but highly concentrated by direction
- long-gold/short-silver subset mean: **+222.95 bps/trade**
- short-gold/long-silver subset mean: **-123.94 bps/trade**

The 21-day version similarly has long subset **+193.69 bps/trade** and short subset **-121.96 bps/trade**, while median-fold economics remain negative.

This means positive aggregate means in some cells are not evidence of a symmetric macro-conditioned relative-value edge.

## Interpretation

The simple macro explanation is rejected. Falling real yields and a weaker dollar have some directional association in selected folds, but not enough cross-fold stability or multiplicity-adjusted evidence to explain the repeated gold/silver asymmetry.

The strongest surviving research fact remains the pair itself:

- extreme adaptive gold/silver innovations contain strong information about subsequent relative-state behavior;
- static and adaptive mean-reversion translations fail executable symmetry;
- simple real-yield/USD/breakeven conditioning does not solve the direction problem.

The next admissible mechanism should therefore remain inside the pair dynamics and test **reversion versus continuation regimes** using only causal pair-state variables such as trailing pair trend, residual/innovation persistence, volatility state, beta instability and displacement velocity. These variables must predict the future signed/absolute pair response state-first before any conditional PnL is evaluated.

## Decision

**Reject v4 as a promotable macro-conditioned strategy.**

Therefore:

- do not open locked validation;
- do not inspect 2024-2026 for this grid;
- do not test leverage;
- do not authorize future shadow or live execution;
- do not reinterpret the positive long-gold subsets as a validated long-only strategy.

## Claims

- macro explanation of pair asymmetry established: **no**
- executable v4 development edge: **no**
- locked internal validation opened: **false**
- verified future OOS: **false**
- profitable edge established: **false**
- leverage authorized: **false**
- live enabled: **false**
