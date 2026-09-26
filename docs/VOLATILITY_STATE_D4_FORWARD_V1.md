# Volatility-state D4 forward replication v1

## Purpose

This watch prospectively tests the strongest PnL-independent state signal carried forward from the self-improvement research:

- causal feature: `local_range_to_spread_15s`;
- primary future-state target: `volatility_expansion_ratio_60s`;
- historical frozen model: one-feature Ridge with median imputation and standard scaling trained only on 12 pre-transfer ENA dependence batches.

The watch does **not** test a trading strategy, direction, session filter, leverage rule, or PnL condition.

## Clean prospective boundary

A provisional 21:00 UTC boundary was drafted, but its commit landed at 21:03:10 UTC. It was therefore superseded before any eligible capture or scoring occurred.

The clean boundary is:

`2026-09-24T21:30:00Z`

The boundary-fix commit `78dd280a48cdad1b37e2433e696f9eb6426e2f97` landed at `2026-09-24T21:03:51Z`.

No observation before 21:30 UTC is eligible for D4 evidence.

## Dependence structure

Each capture records these transfer symbols simultaneously:

- ARB_USDT
- ETH_USDT
- FIL_USDT
- NEAR_USDT
- SOL_USDT
- UNI_USDT

BTC_USDT is recorded only as the existing causal context stream used by the market-state scanner.

All six transfer symbols from one simultaneous capture count as **one dependence cluster**, never six independent trials.

## What is frozen

The primary relation is fixed before D4 collection:

`local_range_to_spread_15s -> volatility_expansion_ratio_60s`

No retraining, feature redefinition, target redefinition, symbol reselection from forward outcomes, threshold tuning, or PnL conditioning is permitted.

The historical Ridge model used only one feature. For a positive one-feature coefficient, rank ordering is invariant to positive affine scaling, so this watch directly measures the feature-to-target rank relationship rather than reconstructing numeric model coefficients. This validates the rank-information mechanism only; it is not an exact numerical-model calibration claim.

## Per-cluster reporting

Every eligible later capture reports:

- per-symbol Spearman correlation for the primary 60-second target;
- median primary Spearman across eligible symbols;
- positive-symbol fraction;
- pooled within-symbol rank correlation;
- target behavior across feature-rank quartiles;
- secondary 30-second and 300-second horizon correlations.

The pooled metric rank-normalizes within symbol before combining observations so symbol-level scale differences do not masquerade as transfer information.

## Review gate

Formal interpretation remains withheld until both are satisfied:

- at least 5 eligible independent later capture clusters;
- at least 3 distinct UTC dates.

An eligible cluster requires at least 20 valid observations for at least 4 of the 6 transfer symbols.

If a transfer symbol exhausts strict public-MEXC depth-snapshot validation, the recorder may mark that symbol unavailable for that cluster and continue capturing the remaining simultaneous panel. The invalid snapshot is never accepted, the frozen symbol set is not changed, and the ordinary recorder remains fail-fast by default. Cluster eligibility is still determined only by the pre-existing 4-of-6 rule.

There is no early pass/fail.

## Evidence boundary

This lane is state prediction only.

It cannot establish:

- directional alpha;
- profitable trading edge;
- strategy promotion;
- live-trading authorization;
- leverage authorization.

If the rank relationship survives genuine future clusters, a later strategy family may be designed around a volatility-expansion payoff mechanism. That strategy would require its own new specification, economics, freeze, and future validation.


## First prospective cluster

Workflow run:

`36146173561`

Artifact:

`volatility-state-forward-ledger-v1`

Artifact digest:

`sha256:ef09f54ddf2947acc7efa7a0f5b6d9e8d020373df31a4fb9ad1535e433a7a560`

Capture window:

- first scored observation: `2026-09-25T14:17:40+00:00`
- last scored observation: `2026-09-25T14:27:35+00:00`

All six frozen transfer symbols were eligible. The MEXC native transport alias `FIL_USDT -> FILECOIN_USDT` allowed FIL to remain in the frozen logical panel without changing the research symbol identity.

Primary frozen relationship:

`local_range_to_spread_15s -> volatility_expansion_ratio_60s`

| Symbol | Observations | 60s Spearman |
| --- | ---: | ---: |
| ARB_USDT | 120 | -0.1011 |
| ETH_USDT | 120 | -0.0089 |
| FIL_USDT | 120 | -0.0654 |
| NEAR_USDT | 120 | -0.3571 |
| SOL_USDT | 119 | -0.0691 |
| UNI_USDT | 120 | -0.2394 |

Cluster diagnostics:

- eligible symbols: 6 / 6
- median primary Spearman: **-0.0851**
- positive-symbol fraction: **0 / 6**
- pooled within-symbol rank correlation: **-0.1402**

This first genuinely later cluster is directionally inconsistent with the frozen positive historical rank relationship. It is not a formal failure because the preregistered review gate requires at least five eligible independent clusters across at least three UTC dates.

Current review progress after this cluster:

- eligible independent clusters: 1 / 5
- distinct UTC dates: 1 / 3
- cluster progress: 20%
- date progress: 33.3%
- formal verdict: `WITHHELD`

No strategy PnL, directional-alpha claim, promotion, live-trading authorization, or leverage authorization is attached to this state-prediction result.


## Ledger accumulation hardening

A post-start infrastructure audit found that the artifact restore step expected a top-level `history/` directory, while uploaded artifacts preserve the repository-relative path `artifacts/volatility_state_forward/history/`. As a result, each successful run preserved its own immutable cluster correctly, but later runs did not restore earlier clusters into the cumulative aggregate.

This is an accumulation bug only. It does not change any captured observation, symbol, feature, target, prospective boundary, eligibility threshold, or review threshold.

The hardening does three things:

- scans every non-expired prior `volatility-state-forward-ledger-v1` artifact;
- restores and deduplicates cluster reports by `cluster_id`, failing closed if the same ID has conflicting payloads;
- prevents ordinary code-push workflow runs from collecting new D4 evidence. Push runs now rebuild the existing ledger only. New capture remains limited to scheduled or explicitly dispatched runs.

No already collected prospective cluster is discarded or re-scored. The four preserved pre-hardening cluster artifacts remain part of the v1 evidence record. Formal interpretation remains withheld until the original 5-cluster and 3-UTC-date gate is satisfied.


## Recovered cumulative checkpoint

Ledger-recovery workflow run:

`36156646988`

Recovered artifact:

`volatility-state-forward-ledger-v1`

Recovered artifact SHA-256:

`6713e32ff57a21115ce4d42993bb9255ce17fd43931db6c6fc3827dab1d3dbc1`

The restore-only push run collected no new market observations. It recovered four distinct immutable prospective clusters that had already been preserved in earlier workflow artifacts:

| Cluster | First observation UTC | Eligible symbols | Median 60s Spearman | Positive-symbol fraction | Pooled within-symbol rank correlation |
| --- | --- | ---: | ---: | ---: | ---: |
| `gha-36144801023-attempt-1` | 2026-09-25 14:04:15 | 6 / 6 | -0.0302 | 33.3% | -0.0061 |
| `gha-36146173561-attempt-1` | 2026-09-25 14:17:40 | 6 / 6 | -0.0851 | 0.0% | -0.1402 |
| `gha-36147836217-attempt-1` | 2026-09-25 14:37:40 | 6 / 6 | -0.3853 | 0.0% | -0.3832 |
| `gha-36153161274-attempt-1` | 2026-09-25 15:18:00 | 6 / 6 | -0.1567 | 16.7% | -0.1773 |

Recovered aggregate:

- eligible independent clusters: 4 / 5;
- distinct UTC dates: 1 / 3;
- median of cluster median primary Spearman: `-0.1209`;
- fraction of clusters with positive median primary Spearman: `0 / 4`;
- median pooled within-symbol rank correlation: `-0.1588`;
- formal verdict: `WITHHELD`;
- ready for review: `false`.

All four observed cluster medians are negative and therefore directionally inconsistent with the frozen positive historical relationship. This remains an interim observation only. The preregistered gate requires both five eligible independent clusters and three distinct UTC dates, so no early pass/fail or model decision is permitted.
