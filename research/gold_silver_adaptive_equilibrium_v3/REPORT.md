# Gold/Silver Adaptive Equilibrium v3 — Development Result

## Evidence boundary

This is a **post-observation retrospective development study**, not future OOS.

The protocol was frozen before scoring at commit `2a9b77aaf4cea6ea6f3f6560b0f982de21e57a49`.

Canonical development workflow run: `34957887750`

Canonical source head: `f0a100dd0ca22cd73bd5050ec710957805b5ab8a`

Artifact: `gold-silver-adaptive-equilibrium-v3` (`10392196777`)

Artifact digest: `sha256:6c2a803ebc0937c4a17707def6ba562bfdc8ab08b88ae8a5840f88968075f64f`

The locked 2021-2023 internal validation and 2024-2026 retrospective extension were **not opened**.

## Why this experiment exists

v2 established statistically durable gold/silver convergence-state information, but its static rolling-OLS equilibrium produced sparse and directionally asymmetric executable returns. v3 therefore changed the relationship model itself: recursive least squares updates the gold/silver log-price equilibrium each day, signals are one-step innovations relative to the prior model, and exits occur when the live adaptive innovation normalizes.

## Frozen design

- independent MT5-style cash XAUUSD/XAGUSD daily bars pinned to external commit `bda79c6...`
- development: 2010-01-01 through 2020-12-31
- recursive least squares on log(gold) = alpha + beta * log(silver)
- 252-trading-day initialization
- forgetting factors: 0.99 / 0.995 / 0.998
- one-step innovation computed before the daily model update
- entry thresholds: |innovation z| >= 1.5 / 2.0
- adaptive normalization exit: |live innovation z| <= 0.5
- maximum holds: 21 / 42 trading days
- mean-reversion direction only
- pre-update beta frozen for each trade
- both legs enter next common open and exit together
- 5 / 10 / 20 bps round-trip cost on total gross notional; primary 10 bps
- 126-calendar-day dependence folds
- 20,000 fold-sign randomizations per unique state hypothesis
- six unique state hypotheses; BH-FDR is applied across those six hypotheses
- controls: reversed direction, unhedged gold, equal-dollar gold-minus-silver, and forced max-hold
- both long-spread and short-spread subsets must be positive for promotion

## Canonical outcome

- unique state hypotheses: **6**
- state passes: **3**
- economic cells: **12**
- economic passes before neighborhood: **0**
- full development passes: **0**
- candidates frozen: **0**

### State evidence strengthens

Three adaptive state hypotheses pass the frozen state gate:

1. `lambda0p99__entryz1p5`
   - state events: **253**
   - scorable folds: **13**
   - median fold Spearman: **+0.596992**
   - positive state folds: **84.62%**
   - sign-flip p: **0.008500**
   - BH-FDR q: **0.016999**

2. `lambda0p995__entryz1p5`
   - state events: **290**
   - scorable folds: **13**
   - median fold Spearman: **+0.697802**
   - positive state folds: **92.31%**
   - sign-flip p: **0.007100**
   - BH-FDR q: **0.016999**

3. `lambda0p998__entryz1p5`
   - state events: **477**
   - scorable folds: **14**
   - median fold Spearman: **+0.287590**
   - positive state folds: **71.43%**
   - sign-flip p: **0.003750**
   - BH-FDR q: **0.016999**

The |z| >= 2.0 hypotheses have high point estimates but only 5-7 scorable folds and therefore fail the frozen breadth requirement.

This materially reinforces the conclusion from v1 and v2: large gold/silver relative dislocations contain reproducible information about subsequent relative-state convergence.

## Why executable economics still fail

No one of the 12 economic cells satisfies the frozen economic gate. The recurring problem is not the state signal; it is directional asymmetry.

Representative cells:

### `adaptive_reversion__lambda0p998__entryz1p5__maxhold21`

- trades: **33**
- median-fold net at 10 bps: **+68.84 bps**
- median-fold PF: **3.65**
- positive economic folds: **62.5%**
- median-fold net at 20 bps: **+58.84 bps**
- overall mean net at 10 bps: **-3.64 bps/trade**
- long-spread mean net: **+275.41 bps/trade**
- short-spread mean net: **-31.55 bps/trade**
- strategy median-fold risk-adjusted score: **+0.365**
- unhedged-gold control: **-0.120**
- static equal-dollar spread control: **-0.319**

It is the closest cell to the frozen 35-trade requirement, but aggregate expectancy remains negative and the short-spread sleeve is negative.

### `adaptive_reversion__lambda0p998__entryz1p5__maxhold42`

- trades: **21**
- median-fold net: **+89.37 bps**
- overall mean net: **-13.69 bps/trade**
- long-spread mean net: **+267.75 bps/trade**
- short-spread mean net: **-60.59 bps/trade**

### `adaptive_reversion__lambda0p995__entryz1p5__maxhold42`

- trades: **17**
- median-fold net: **+126.18 bps**
- overall mean net: **-26.55 bps/trade**
- long-spread mean net: **+261.76 bps/trade**
- short-spread mean net: **-146.67 bps/trade**

The same sign asymmetry appears across forgetting factors rather than in one isolated parameter cell.

## Interpretation

The repeated pattern across two materially different relationship models is now a research finding in its own right:

- relative-state convergence predictability is strong;
- negative innovations followed by long-gold / short-silver trades are often profitable;
- positive innovations followed by short-gold / long-silver trades are persistently weak or negative;
- simply deleting the losing side after observing this would be post-hoc selection and is not allowed.

The next admissible question is therefore **what pre-existing market state predicts whether a gold/silver dislocation will converge symmetrically, persist, or exhibit this directional asymmetry?** A new experiment should test macro/regime variables state-first before translating any conditioning into PnL.

## Decision

**Reject v3 as a promotable executable strategy.**

Therefore:

- do not open 2021-2023 locked validation;
- do not inspect 2024-2026 for this grid;
- do not test leverage;
- do not authorize future shadow or live execution;
- do not create a post-hoc long-spread-only strategy from these results;
- do not lower the trade-count or both-direction gates.

The next research lane should be a separately frozen **macro-conditioned gold/silver relative-value regime study** that tests the directional asymmetry as a state-prediction problem before any conditioned PnL is evaluated.

## Claims

- adaptive gold/silver convergence-state information: **yes**
- executable v3 development edge: **no**
- locked internal validation opened: **false**
- verified future OOS: **false**
- profitable edge established: **false**
- leverage authorized: **false**
- live enabled: **false**
