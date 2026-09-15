# Gold/Silver Error-Correction Relative Value v2 — Development Result

## Evidence boundary

This is a **post-observation retrospective development study**, not future OOS.

The protocol was frozen before scoring at commit `4dd0d54f132593082e26a654e03935b8c623615c`.

Canonical development workflow run: `34957510867`

Canonical source head: `b004197dab7e41492ca3c3d3f07d1d6e542a03f3`

Artifact: `gold-silver-error-correction-relative-value-v2` (`10392202184`)

Artifact digest: `sha256:763ae32fec59067cf71b41e8e2b7667b752c71dc77f98332b44b8d78e0fc66a4`

The locked 2021-2023 internal validation and 2024-2026 retrospective extension were **not opened**.

## Why this experiment exists

v1 found statistically durable information in gold/silver relative extremes but failed to monetize it robustly with fixed 21/42-day holds. v2 therefore changed the mechanism to a causal rolling log-price residual, explicit AR(1)/half-life relationship admission, and convergence-based exits.

## Frozen design

- independent MT5-style cash XAUUSD/XAGUSD daily bars pinned to external commit `bda79c6...`
- development: 2010-01-01 through 2020-12-31
- rolling OLS log-price residual lookbacks: 252 / 504 trading days
- entry thresholds: |z| >= 1.5 / 2.0
- exit thresholds: |z| <= 0.25 / 0.5
- maximum holds: 42 / 84 trading days
- mean-reversion direction only
- entry allowed only when trailing residual AR(1) phi is in (0, 0.98) and estimated half-life is 3-84 trading days
- entry-time OLS beta frozen for the trade
- both legs enter next common open and exit together
- 5 / 10 / 20 bps round-trip cost on total gross notional; primary 10 bps
- 126-calendar-day dependence folds
- four unique state hypotheses; BH-FDR is applied to those four hypotheses rather than duplicated exit/hold variants
- unhedged gold, equal-dollar gold-minus-silver, reversed-direction, and forced-max-hold controls
- both spread directions must contribute positively for promotion

## Canonical outcome

- unique state hypotheses: **4**
- state passes: **1**
- economic cells: **16**
- economic passes before neighborhood: **0**
- full development passes: **0**
- candidates frozen: **0**

### State result

The sole state pass was:

`lookback252__entryz1p5`

- state events: **254**
- scorable state folds: **13**
- median fold Spearman: **+0.368132**
- positive state folds: **12/13 = 92.31%**
- sign-flip p: **0.007850**
- BH-FDR q: **0.031398**

This is credible evidence that sufficiently large 252-day log-price residual dislocations predict subsequent normalized convergence of the hedged gold/silver relationship.

### Why the state-supported economic cells fail

The 42-day variants have enough observations to inspect but fail executable economics:

- exit z 0.25 / max hold 42: **22 trades**, median-fold net **+2.21 bps** at 10 bps, median PF **1.34**, but only **53.3%** positive folds and overall mean **-23.84 bps/trade**. Long-spread mean is **+51.17 bps**, short-spread mean **-113.85 bps**.
- exit z 0.50 / max hold 42: **23 trades**, overall mean **-30.63 bps/trade**, again with materially negative short-spread contribution.

The 84-day variants look attractive in aggregate but are too sparse and asymmetric:

- exit z 0.25 / max hold 84: **15 trades**, median-fold net **+162.22 bps**, mean **+74.93 bps/trade**, but long-spread mean **+164.85 bps** versus short-spread mean **-59.94 bps**.
- exit z 0.50 / max hold 84: **16 trades**, median-fold net **+123.72 bps**, mean **+62.66 bps/trade**, but long-spread mean **+162.09 bps** versus short-spread mean **-103.07 bps**.

They fail the frozen minimum 30-trade requirement and the requirement that both spread directions have positive mean net expectancy.

### Sparse 504-day cells are not promotion evidence

Several 504-day variants display very large raw returns, but they have only **7-13 trades**, fewer than the frozen trade requirement, and their state hypotheses do not meet the minimum scorable-fold gate. They are treated as sparse-sample diagnostics only.

## Decision

**Reject v2 as a promotable strategy.**

The positive result is narrower and important: a causal gold/silver residual contains durable convergence-state information. The current static rolling-OLS equilibrium and entry-time-frozen hedge do not convert that information into sufficiently broad, symmetric executable returns.

Therefore:

- do not open 2021-2023 locked validation;
- do not inspect 2024-2026 for this grid;
- do not test leverage;
- do not authorize future shadow or live execution;
- do not remove the short-spread requirement after observing its weakness;
- do not lower the trade-count gate around the sparse 84-day/504-day cells.

The next admissible mechanism is an **adaptive equilibrium** model, such as recursive/Kalman-style hedge estimation with innovation-based entry and exit, under a new predeclared protocol.

## Claims

- gold/silver convergence-state information: **yes**
- executable v2 development edge: **no**
- locked internal validation opened: **false**
- verified future OOS: **false**
- profitable edge established: **false**
- leverage authorized: **false**
- live enabled: **false**
