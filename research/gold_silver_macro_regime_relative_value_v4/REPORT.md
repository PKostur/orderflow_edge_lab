# Gold/Silver Macro-Regime Relative Value v4 — Development Result

## Evidence boundary

Post-observation retrospective mechanism study. The protocol was frozen before scoring at `0bb703c492df8c855ddcc5aa7ec4ad893bb21b78`.

Canonical run: `34970055204`.
Canonical source head: `134cf4bdaa5bbe3bc94b62f9948b94e03a037d64`.
Artifact: `gold-silver-macro-regime-relative-value-v4` (`10396657440`).
Artifact digest: `sha256:15171434cfd381b86539e8a21447cb76a6c6e523a05c73667b3fa374f980257d`.

2021-2023 locked validation and 2024-2026 retrospective extension remained unopened. No leverage was tested.

## Frozen question

v1-v3 repeatedly found gold/silver relative-state convergence information but failed executable two-sided economics. v4 asked whether a pre-existing exogenous macro regime explains that directional asymmetry before any conditioned PnL is considered.

Macro inputs were lagged by one metals trading bar and used a fixed 20-bar lookback:

- rising VIX = risk-off +1
- rising broad USD = risk-off +1
- falling 10-year real yield = risk-off +1
- composite risk-off score in {-3,-1,+1,+3}
- spread-side alignment = side * risk-off score

Only the composite hypothesis was allowed to authorize economic promotion. Individual macro components were diagnostic only.

## Canonical state result

- development rows: **2,834**
- complete macro rows: **2,811**
- dislocation state rows: **290**
- state hypotheses: **4**
- state passes: **0**

Composite alignment:

- scorable folds: **13**
- median fold Spearman: **+0.2523**
- positive folds: **61.54%**
- sign-flip p: **0.1680**
- BH-FDR q: **0.3361**
- frozen state gate: **FAIL**

Component diagnostics also fail promotion:

- VIX alignment: median rho **0.000**, 9 folds, q **1.0**
- USD alignment: median rho **+0.0280**, 7 folds, q **0.6631**
- real-yield alignment: median rho **+0.3081**, 9 folds, q **0.3361**

The real-yield component is suggestive but was not the predeclared promotable hypothesis and is statistically insufficient under the frozen breadth/FDR rules.

## Economic diagnostics

Because the composite state gate failed, none of these cells can promote regardless of PnL.

Broad alignment (`alignment >= 1`):

- max hold 21: 19 trades; median-fold net **+57.0 bps**, mean **-27.3 bps/trade**; long spread **+290.0**, short spread **-111.9**
- max hold 42: 13 trades; median-fold net **+140.7 bps**, mean **+31.0 bps/trade**; long spread **+302.7**, short spread **-89.8**

Strict alignment (`alignment == 3`):

- max hold 21: **7 trades**, mean **+81.46 bps/trade**, median-fold net **+90.08 bps**, long **+90.08**, short **+80.02**
- max hold 42: **6 trades**, mean **+38.32 bps/trade**, median-fold net **+110.36 bps**, long **+140.71**, short **+17.84**

The strict cells are interesting but far below the frozen 30-trade minimum and arise under a failed macro-state hypothesis. They are therefore treated as tiny-sample diagnostics, not edge evidence.

## Decision

**Reject v4 as a promotable strategy and do not open validation.**

Do not lower the state-significance gate, reduce the trade minimum, or promote the strict-alignment cells after seeing their PnL.

The repeated gold/silver line now has a clear conclusion: relative dislocations contain state information, but the tested ratio, static residual, adaptive residual, and macro-conditioned translations have not produced a robust executable two-sided edge.

The next gold experiment should change return source rather than continue conditioning the same convergence mechanism. The next lane is a separately frozen **gold macro-shock event study** testing whether large causal shocks in the dollar, real yields and volatility predict short-horizon gold continuation or reversal.

## Claims

- macro explanation of gold/silver asymmetry established: **no**
- executable development edge: **no**
- locked validation opened: **false**
- verified future OOS: **false**
- leverage authorized: **false**
- live enabled: **false**
