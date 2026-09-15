# Best Bets Research Focus — 2026-09-15

## Objective

Concentrate future research effort on the few hypotheses that still have evidence behind them while preserving all existing forward clocks and avoiding post-hoc rescue of rejected families.

This document does **not** modify any frozen strategy specification. Existing forward candidates remain unchanged.

## Priority 1 — 30d/7d dollar-neutral cross-sectional momentum

Candidate: `mexc_xs_mom30_7_dn_v1`

Status: primary trading candidate under forward paper/shadow observation.

Why it remains active:

- selected from a pre-specified dollar-neutral family for stability rather than maximum headline return;
- uses a fixed 10-coin MEXC futures universe;
- long top quartile / short bottom quartile of trailing 30-day return;
- 7-day holding period;
- 1.0 gross exposure, 1x leverage;
- 20 bps round-trip modeled cost;
- actual public MEXC realized funding during held intervals;
- forward-only clock began before the currently observed period.

Primary evidence gate:

- do not review for edge before at least 10 completed forward rebalances/holding periods, as already frozen in the candidate specification;
- evaluate net performance after modeled costs and realized funding;
- retain dollar-neutrality and current rebalance phase;
- track period-by-period PnL, hit rate, max drawdown, turnover, funding contribution, long-side contribution, short-side contribution, and per-symbol contribution;
- compare against simple equal-timing controls without retuning the candidate.

No parameter changes are permitted before the frozen forward review gate.

## Priority 2 — transferable volatility-state prediction

Status: primary predictive-signal research track, not yet a trading strategy.

Frozen state result carried forward:

- feature: `local_range_to_spread_15s`;
- model: Ridge with median imputation and standard scaling;
- target: `volatility_expansion_ratio_60s`;
- training data: 12 pre-transfer ENA dependence batches only;
- corrected six-symbol forward transfer had positive Spearman rho on all six symbols and median rho about +0.352;
- the simultaneous six-symbol transfer batch counts as one dependence cluster, not six independent validation folds.

Research rule:

- do not retrain, reselect features, or alter the current state model using future transfer labels;
- accumulate additional genuinely later dependence clusters;
- report cluster-level and pooled rank correlation, sign consistency, calibration, and decay by horizon;
- keep state prediction evidence separate from trading PnL evidence;
- do not claim directional alpha from a volatility predictor.

The next strategy family, if any, should have a payoff mechanism explicitly linked to predicted volatility expansion. It must be versioned and frozen before its own untouched forward evaluation.

## Priority 3 — ENA 1h mean reversion

Candidate: `ena_bb40_rsi25_75_atr15_v1`

Status: passive high-value forward candidate.

Why it remains alive:

- development reference showed 40 trades, about +55.36 bps expectancy, PF about 1.356, and positive median fold statistics;
- tail-loss reduction from the hard-stop treatment was material;
- however broad cross-symbol robustness was not established, so this remains ENA-specific;
- no forward trade has yet completed.

Evidence gate:

- leave the candidate completely untouched;
- no edge review before 20 completed forward trades, as already frozen;
- do not use inactivity as evidence against the candidate;
- do not lower thresholds to force trades.

## Secondary watch — 10-coin 8h EMA/ATR trend

Candidate: `mexc_8h_ema24_96_atr025_v1`

Status: continue forward shadow collection, but do not allocate new research effort to optimizing this family.

Reason:

- the candidate was selected for parameter-neighborhood stability rather than peak in-sample PF;
- early forward mark-to-market moved from materially negative to strongly positive and back to negative, showing that a few favorable marks are not sufficient evidence;
- zero or very few completed trades means expectancy is not yet estimable.

Evidence gate:

- retain the exact frozen specification;
- wait for at least 20 completed forward trades before any edge review;
- no parameter rescue, regime retuning, or leverage changes.

## Retired / closed for rescue testing

The following families should not receive further tuning on already observed data unless a genuinely new hypothesis is defined and frozen first:

- discovery-v1 short-horizon directional order flow;
- liquidity-gated and volatility-gated rescue variants of discovery-v1;
- reversed-direction discovery-v1;
- stop/RR rescue variants of discovery-v1;
- Markov/Bollinger reconstruction variants that failed after realistic costs/gates;
- broad gold technical-strategy tournament families that failed promotion;
- gold/silver ratio momentum as a promotable live candidate after independent MT5 cash-source failure;
- same-window cross-symbol epoch selections that were invalidated by shared-period dependence.

These results remain valuable negative evidence and must stay in the audit trail.

## Resource allocation

Research effort should be concentrated approximately as follows:

1. Cross-sectional forward evidence and diagnostics: highest priority.
2. Independent future replication of the frozen volatility-state model: highest research priority.
3. ENA 1h forward observation: passive, no tuning.
4. 8h trend forward observation: passive, no tuning.
5. All rejected families: archive/audit only.

## Promotion boundary

No strategy is currently a proven persistent edge.

No candidate may move toward live execution unless the existing repository promotion framework is satisfied, including frozen specification, untouched holdout evidence, provenance binding, realistic economics, sufficient forward evidence, and explicit approval. Passing research or paper gates is not permission to transmit live orders.
