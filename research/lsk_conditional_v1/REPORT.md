# LSK conditional-regime v1 — exploratory result

**Not promotable. The frozen rule produced no trades.** Across five retained independent replay clusters it classified all 234 eligible BTC-aligned signals as NO_TRADE. No thresholds or costs were relaxed after evaluation. Zero aggregate trading PnL from abstaining is not a profitable edge; per-trade mean and PF are undefined.

Frozen at **2026-09-30T09:00:06.334036+00:00**, before replay evaluation, in commit `9579f35`. Trial `LSK-CONDITIONAL-001`. All examined market captures predate the freeze and remain discovery/exploratory evidence. True forward clusters evaluated: **0**.

## Evidence coverage

The predeclared inventory includes all 17 successful Cross-Pair runs from #84 through #123 in the saved run listing. Twelve contain LSK. Five have retained full raw replays, each byte-hash matched to its original direction report; seven retain summaries only. The five replayable captures are #111, #114, #117, #122 and #123 (about 75 total capture minutes). No replay was selected by its returns. Artifact availability limits representativeness.

| Run | Classifier evidence | Source |
| --- | --- | --- |
| #84 | summary only; classifier not evaluable | [GitHub run](https://github.com/PKostur/orderflow_edge_lab/actions/runs/34788666286) |
| #85 | summary only; classifier not evaluable | [GitHub run](https://github.com/PKostur/orderflow_edge_lab/actions/runs/34794410955) |
| #86 | summary only; classifier not evaluable | [GitHub run](https://github.com/PKostur/orderflow_edge_lab/actions/runs/34808535539) |
| #87 | summary only; classifier not evaluable | [GitHub run](https://github.com/PKostur/orderflow_edge_lab/actions/runs/34811982986) |
| #88 | summary only; classifier not evaluable | [GitHub run](https://github.com/PKostur/orderflow_edge_lab/actions/runs/34820108474) |
| #89 | summary only; classifier not evaluable | [GitHub run](https://github.com/PKostur/orderflow_edge_lab/actions/runs/34834957272) |
| #111 | replay byte hash verified | [GitHub run](https://github.com/PKostur/orderflow_edge_lab/actions/runs/34861305890) |
| #114 | replay byte hash verified | [GitHub run](https://github.com/PKostur/orderflow_edge_lab/actions/runs/34877009239) |
| #115 | summary only; classifier not evaluable | [GitHub run](https://github.com/PKostur/orderflow_edge_lab/actions/runs/34881365016) |
| #117 | replay byte hash verified | [GitHub run](https://github.com/PKostur/orderflow_edge_lab/actions/runs/34883734982) |
| #122 | replay byte hash verified | [GitHub run](https://github.com/PKostur/orderflow_edge_lab/actions/runs/34889371904) |
| #123 | replay byte hash verified | [GitHub run](https://github.com/PKostur/orderflow_edge_lab/actions/runs/34895092974) |

Independent clusters merge overlapping or ≤300-second-adjacent capture intervals transitively. One representative is selected without PnL, by valid state count, earliest start, then source hash. The five retained replays form five independent clusters. This does not meet the inherited ten-cluster inference minimum. Summary-only captures were not assigned synthetic classifier decisions.

## Frozen hypothesis

ORIGINAL requires aligned pressure converting into efficient price movement with elevated participation and applied-depth activity, expanding range, moving but non-mature displacement, and stable spread. REVERSED requires sustained strong aligned pressure, collapsed/declining efficiency, mature displacement, activity deceleration, nonexpanding range, and non-improving spread within a fixed liquidity cap. Otherwise abstain.

The rule uses fixed five-second anchors, strictly prior 300-second state normalization, fixed quartiles, and existing discovery thresholds. It incorporates trade participation, quote updates, recent range, displacement/spread, range/spread, flow strength, price-response efficiency, spread change, range expansion/contraction, and BTC alignment. Resets require fresh warm-up; missing or stale state never defaults to a trade. Full definitions are in the accompanying protocol.

**Material censoring warning:** #111 loses three legacy interior fills under the stricter quality/epoch checks. Their legacy 4-bps original results were +11.00, -1,074.86 and -1,033.56 bps. The 49 common filled observations have exactly the same original 4-bps mean (+5.93 bps) in both implementations; the legacy full 52-event mean was -34.75 bps. Thus the apparent #111 direction flip comes from excluded observations, not a newly discovered regime edge. Missing fills are potentially informative and the complete-case control statistics cannot establish improved profitability. These legacy returns are preserved for reconciliation, not imputed as valid new fills.

## Results under all cost assumptions

Spread is embedded once through bid/ask execution. The earlier conversation’s extra snapshot-spread subtraction would double-count spread. Reversal uses opposite executable prices, not the negative of original PnL. Conservative = 8 bps round-trip fee + 250 ms entry/exit latency + 2 bps RT slippage + 2 bps RT adverse selection. Severe = 8 bps fee + 1000 ms latency + 4 bps RT slippage + 4 bps RT adverse selection. These are configurable pre-registered stresses, not verified account fee rates or measured fill guarantees.

| Cost | Strategy | Filled trades | Mean net bps/trade | PF | Positive clusters / 5 |
| --- | --- | --- | --- | --- | --- |
| fee4 | Frozen three-way | 0 | N/A | N/A | 0 |
| fee4 | Always original (BTC aligned) | 219 | -15.90 | 0.64 | 2 |
| fee4 | Always reversed (BTC aligned) | 219 | 1.90 | 1.06 | 3 |
| fee4 | Unconditional aligned (no BTC gate) | 474 | -16.35 | 0.60 | 1 |
| fee8 | Frozen three-way | 0 | N/A | N/A | 0 |
| fee8 | Always original (BTC aligned) | 219 | -19.90 | 0.57 | 2 |
| fee8 | Always reversed (BTC aligned) | 219 | -2.10 | 0.94 | 3 |
| fee8 | Unconditional aligned (no BTC gate) | 474 | -20.35 | 0.53 | 1 |
| conservative | Frozen three-way | 0 | N/A | N/A | 0 |
| conservative | Always original (BTC aligned) | 218 | -24.69 | 0.50 | 1 |
| conservative | Always reversed (BTC aligned) | 218 | -5.10 | 0.86 | 3 |
| conservative | Unconditional aligned (no BTC gate) | 473 | -24.90 | 0.45 | 0 |
| severe | Frozen three-way | 0 | N/A | N/A | 0 |
| severe | Always original (BTC aligned) | 217 | -29.41 | 0.45 | 0 |
| severe | Always reversed (BTC aligned) | 217 | -8.64 | 0.78 | 2 |
| severe | Unconditional aligned (no BTC gate) | 473 | -28.87 | 0.40 | 0 |

These are equal-notional overlapping-event economics, not portfolio returns. Always-original/reversed use the same BTC-aligned signal universe; unconditional-aligned omits BTC agreement and has a larger universe. All controls share the new quote-freshness and sequence guards, so they are not exact reproductions of legacy headline values.

### Missing execution and censoring

| Cost | BTC-aligned intended | Filled | Missing interior | Capture-tail censored |
| --- | --- | --- | --- | --- |
| fee4 | 234 | 219 | 4 | 11 |
| fee8 | 234 | 219 | 4 | 11 |
| conservative | 234 | 218 | 4 | 12 |
| severe | 234 | 217 | 4 | 13 |

The control means/PFs above are complete-case observations, not estimates for missing fills. In the conservative case, unconditional-aligned has 498 intended events, 473 fills, 9 missing interior fills and 16 tail-censored events. Missing selected interior execution blocks a successful screen. The classifier selected no events, so it has no missing selected fills.

## Cluster consistency and concentration

| Cluster / run | Original mean (conservative) | Reversed mean (conservative) | Unconditional mean (conservative) | Classifier trades |
| --- | --- | --- | --- | --- |
| cluster_1 / #111 | 0.95 | -32.63 | -23.88 | 0 |
| cluster_2 / #114 | -50.04 | 20.79 | -26.22 | 0 |
| cluster_3 / #117 | -33.36 | 3.04 | -30.20 | 0 |
| cluster_4 / #122 | -1.38 | -27.20 | -4.67 | 0 |
| cluster_5 / #123 | -41.81 | 13.33 | -39.68 | 0 |

| Strategy (conservative) | Positive clusters | Best share of positive-cluster net profits | Mean after removing best cluster |
| --- | --- | --- | --- |
| Frozen three-way | 0/5 | N/A | N/A |
| Always original (BTC aligned) | 1/5 | 100.00% | -31.93 |
| Always reversed (BTC aligned) | 3/5 | 53.11% | -10.57 |
| Unconditional aligned (no BTC gate) | 0/5 | N/A | -29.40 |

The candidate has no profits to attribute to any cluster. Both candidate branches have zero trades and zero active clusters. Relative improvement over a losing always-trade control comes entirely from abstention and does not validate either directional hypothesis.

## Why the candidate abstained

| Reason | Signals |
| --- | --- |
| warmup | 101 |
| missing_state | 34 |
| missing_lag | 10 |
| pressure_or_liquidity_veto | 16 |
| indeterminate | 73 |

Warm-up or unavailable/lagged state accounts for 145 signals; 16 fail direction/liquidity requirements and 73 have valid state but satisfy neither complete interaction. This is a low-coverage result, not evidence that absorption or efficient conversion never exists. No post-result simplification was made to obtain trades.

## Forward test prepared

The checked-in manual workflow and `scripts/lsk_forward_capture.py` verify the freeze, register an attempt before capture, collect a fixed 20-minute LSK/BTC batch, retain failures, and evaluate the unchanged rule. They do not place orders. Start times must be strictly after the September 30 freeze; all September 14 captures are rejected as forward evidence. The workflow is prepared, not a claim that a future capture has already run.

Retain every attempt and the raw replay; do not stop early on a winner. Audit the first ten independent clusters, including failed attempts in the chronology. Require at least 150 capture minutes before considering a revision. The frozen screen additionally requires ≥60 trades, ≥80% positive clusters, PF >1.20 under severe stress, positive median cluster expectancy, no more than 50% of positive-cluster profit in the best cluster, survival after removing that cluster, and at least 20 trades across three clusters from each branch.

Chronological cohort completeness, untouched provenance, candidate/holdout audit and formal holdout trial accounting remain mandatory. The runner explicitly refuses to certify screen success solely from an arbitrary supplied subset. The formal holdout ledger currently has zero accesses; the separate experiment freeze records one hypothesis. All live/promotion claims remain false.

## Reproducibility

Deliverables include the complete decision/fill ledger, compact result summary, protocol and freeze, capture inventory, tested source patch, and forward capture launcher. The 4.8 GB raw replays remain in the local work directory and are not duplicated in the delivery bundle. Each source SHA256 is in the inventory and report.

## Legacy baseline reconciliation (separate sample)

For transparency, the unchanged archived BTC-aligned 30-second baseline at 8 bps fee is shown below. These original reports already pay bid/ask spread, but lack the new latency/quality treatment. They are not pooled with the stricter five-replay comparison. All twelve historical captures remain exploratory.

| Run | Legacy N | Original mean / PF | Reversed mean / PF |
| --- | --- | --- | --- |
| #84 | 51 | 32.34 / 2.32 | -54.44 / 0.23 |
| #85 | 69 | 24.15 / 1.51 | -49.60 / 0.42 |
| #86 | 37 | -14.80 / 0.52 | -6.55 / 0.76 |
| #87 | 34 | -8.54 / 0.60 | -11.01 / 0.50 |
| #88 | 45 | -24.67 / 0.24 | -0.15 / 0.99 |
| #89 | 69 | -17.78 / 0.48 | -3.77 / 0.86 |
| #111 | 52 | -38.75 / 0.60 | 15.30 / 1.22 |
| #114 | 38 | -45.42 / 0.19 | 22.99 / 2.21 |
| #115 | 53 | 6.89 / 1.22 | -32.84 / 0.37 |
| #117 | 54 | -26.71 / 0.40 | 5.36 / 1.20 |
| #122 | 38 | 4.41 / 1.20 | -25.97 / 0.30 |
| #123 | 41 | -36.58 / 0.23 | 15.66 / 1.85 |

## Validation

353 repository tests passed, including 16 tests for the classifier and freeze contract. The deterministic release-manager gate is reviewable with zero errors; its two existing phrase-scan warnings concern the word "frictionless" elsewhere in the repository. No profitability or live-execution gate has passed.
