# Gold/Silver Trend Exhaustion v6 — Temporal Validation Result

## Evidence boundary

This is a post-observation temporal validation on 2021-2023, not future OOS.

Protocol freeze: `18e6620fdc028056028fb02823c5284e89e403fe`
Canonical scored head: `c6c402732ddfb4b77e5a60b6fa56be97a7363c9b`
Canonical workflow run: `34971253689`
Artifact: `gold-silver-trend-exhaustion-v6` (`10397218635`)
Artifact digest: `sha256:d40c79bcf03a14f6e6cfe51ebb74e2906a16f29aa8aab7c80f461b280f3ce015`

## Frozen hypothesis

v5 generated one post-observation sign-reversed hypothesis: at an extreme adaptive XAU/XAG dislocation, a trailing pair trend aligned with the current dislocation may represent trend exhaustion and therefore support mean reversion; an opposing trend may support continuation.

v6 froze that one hypothesis before looking at 2021-2023.

## Result

State test:

- qualifying events: **18**
- positive-score fraction: **100%**
- negative-score fraction: **0%**
- scorable folds: **2**
- fold Spearman values: **+0.8601**, **+0.9000**
- median fold Spearman: **+0.8801**
- positive folds: **100%**
- 20,000-epoch sign-flip p-value: **0.24899**
- frozen state pass: **false**

The point estimate is attractive, but the test fails because the period contains too few qualifying observations, only two scorable dependence folds, no negative-score regime observations, and no permutation significance.

Economic diagnostic (cannot pass because state failed):

- non-overlapping trades: **3**
- median fold net @10 bps: **+94.77 bps**
- mean net @10 bps: **+123.99 bps/trade**
- high-cost median fold net @20 bps: **+84.77 bps**
- original-v5-sign control mean: **-143.99 bps/trade**
- long-gold/short-silver trades: **0**
- short-gold/long-silver trades: **3**, all profitable
- reversion decisions: **3**
- continuation decisions: **0**

The economic sample is therefore too sparse and one-sided to establish an edge.

## Decision

**Reject v6 as a promotable hypothesis.**

- no future shadow authorization;
- no leverage testing;
- no live trading;
- do not weaken event-count, fold-breadth, score-balance or directional-breadth gates around three winning trades.

This closes the gold/silver convergence/regime lineage for now. The next gold lane is structurally orthogonal: scheduled CPI, Employment Situation and FOMC reaction/continuation versus reversal using intraday XAU data with event definitions frozen before PnL.

## Claims

- temporal state confirmation: **no**
- executable temporal edge: **no**
- verified future OOS: **false**
- profitable edge established: **false**
- leverage authorized: **false**
- live enabled: **false**
