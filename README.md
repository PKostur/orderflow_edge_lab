# Orderflow Edge Lab

Research-first infrastructure for short-horizon order-flow strategy research and paper execution.

**Version 1.0: research and manual paper release.** See the
[release guide](docs/RELEASE_1_0.md) for installation, verification, and operational boundaries.

## Safety boundary

This repository does not contain live broker or exchange order transmission. The execution layer is limited to paper and explicit approval workflows. No strategy is considered to have a profitable edge unless it survives genuine out-of-sample validation after realistic costs on data that was not used for discovery or tuning.

## Continuous multi-agent hardening

The repository now includes a zero-additional-cost multi-agent control plane. Seven specialist agents independently review data integrity, research validity, strategy validation, execution safety, reliability/CI, observability/deployment, and adversarial safety. A release manager aggregates their findings into a hashed report.

```bash
orderflow-multi-agent --output artifacts/multi_agent_report.json
```

The same control plane runs hourly in GitHub Actions with read-only repository permissions. It does not place trades or promote a strategy. See [multi-agent hardening](docs/MULTI_AGENT.md).

## Current priorities

1. Use MEXC public Futures trades and price-level depth as the primary zero-additional-cost data path for ENA/BTC crypto research.
2. Preserve DeepCharts/dxFeed as an optional path where the entitlement permits supported export or external API access.
3. Keep strict separation between discovery, validation, and final holdout data.
4. Fail closed on stale, malformed, incomplete, duplicated, crossed, sequence-gapped, or low-quality market data.
5. Make research runs reproducible with frozen configuration, immutable raw inputs, hashes, and run manifests.
6. Paper trade and approval-test before any future broker or exchange integration is considered.

## Current state

- [STATUS.md](STATUS.md) — active prospective watches, next scheduled decision dates, stop rules, and closed lanes.
- [research/INDEX.md](research/INDEX.md) — navigational index of every research lane and its terminal state.
- [docs/README.md](docs/README.md) — documentation map.

## Commands

Every installed command is available as a flat script (for example `orderflow-multi-agent`) and through a single dispatcher:

```bash
orderflow --list          # grouped command table
orderflow --list-json     # machine-readable
orderflow paper --help    # same implementation as orderflow-paper
orderflow review-clock     # daily elapsed-time report for preregistered watches
orderflow capture-health   # descriptive MEXC capture inventory and gap report
orderflow review-packet    # hash-pinned review skeleton from a frozen counting report
orderflow artifact-coverage # are the artifacts a predeclared review needs still retrievable?
orderflow ops-digest       # one daily digest of clock + captures + ledger + coverage
orderflow robustness       # cluster interval, design power, concentration, negative controls
orderflow research-hygiene # pre-registration, frozen hashes, workflow/artifact graph, inspection registry
orderflow discovery-screen # does a candidate clear the declared friction before a window is spent?
orderflow orthogonality    # redundancy clusters, incremental information, leave-one-out stability
```

The wait-window observability commands are aggregation only: they count no evidence, compute no
verdict, and promote nothing. The validation commands analyse an already-frozen report or check a
contract; they add no threshold to an open watch and label every number they produce as post-hoc.
See [docs/README.md](docs/README.md) and [docs/VALIDATION_TOOLING.md](docs/VALIDATION_TOOLING.md).

## Public strategy transfer (development only)

The [25-implementation public source survey](docs/PUBLIC_STRATEGY_SOURCE_SURVEY_2026_10_10.md) and [three-family causal spot shadow protocol](docs/PUBLIC_STRATEGY_SHADOW_PROTOCOL_V1.md) provide an offline, no-order research evaluator (`orderflow-public-strategy-shadow`). Its candidate config is **draft, not frozen**; development outputs are spent data, and prospective mode refuses an unfrozen config. No existing frozen watch is changed.

The [Binance Spot 8h development review](docs/PUBLIC_STRATEGY_SPOT_8H_DEVELOPMENT_2026_10_10.md) reports the first exact v1 historical run, source hashes, path and control diagnostics, and decisions. No candidate was frozen for prospective observation.

The [failed-downside replication feasibility audit](docs/PUBLIC_FAILED_DOWNSIDE_REPLICATION_FEASIBILITY_2026_10_10.md) independently reproduces the spent-data ledger and quantifies the sample needed for the +5 bps hurdle. A future freeze remains unjustified because of precision, source-access and executable-cost gaps.

## MEXC Futures order flow

The repository can record public MEXC Futures `push.deal` and incremental `push.depth` streams for `ENA_USDT`, `BTC_USDT`, or other Futures symbols without API keys.

```bash
python -m pip install -e .
orderflow-mexc-record --symbol ENA_USDT --symbol BTC_USDT
```

The recorder maintains a synchronized local L2 book using full snapshots, depth versions, commit recovery, and fail-closed snapshot fallback. Raw JSONL is exclusive-create and receives a SHA-256 manifest on clean close. A separate feature stream contains rolling CVD, buy/sell volume, trade velocity, spread, microprice, top-N book imbalance, liquidity adds/pulls, and depth-flow imbalance.

Replay an existing raw capture without touching the network:

```bash
orderflow-mexc-replay data/mexc_orderflow/<raw-file>.jsonl
```

See [MEXC Futures order-flow recorder](docs/MEXC_ORDERFLOW.md).

## dxFeed and DeepCharts

Credentials must remain local. Never commit them or paste them into chat.

The repository supports two paths using existing access:

1. A normalized adapter for DeepCharts or dxFeed trade/BBO exports.
2. An entitlement probe scaffold for external dxFeed access without assuming a DeepCharts login automatically grants API entitlement.

The probe supports HTTPS Basic or bearer authentication when provided by the
existing subscription. A platform-issued username does not determine API rights.
See [data access and quality checks](docs/DXFEED.md).

## Operator tools

- [Manual paper control and checkpoint recovery](docs/DEPLOYMENT.md): inspect,
  submit, approve, reject, close, and halt paper execution.
- [Future-observation audit](docs/RESEARCH_PROTOCOL.md): verify supplied records
  against frozen rules and produce hashed, descriptive reports without certifying
  out-of-sample evidence or deployment eligibility.

Local export validation, MEXC public market-data collection, replay, and engineering tests require no paid API or external service beyond the user's existing network access. Real market-data availability and exchange coverage remain vendor-controlled.

## Research validity

- Previously inspected data is considered spent for independent validation.
- Parameters are frozen before a validation window is opened.
- A final holdout is not exported by an unrevealed research run.
- Transaction costs, spread, slippage assumptions, and ambiguous same-bar outcomes must be explicit.
- Attractive synthetic or in-sample results are engineering evidence only.
- One positive validation window is not enough for deployment.

## Execution lifecycle

```text
signal -> TradeIntent -> data/risk checks -> approval queue -> paper fill -> paper close -> journal
```

The manual submission interface blocks failed data-quality or risk checks.
Direct PaperEngine callers must supply upstream data/signal validation.

## Live trading

Live order transmission is deliberately absent. Any future live adapter should be introduced only after sufficient fresh out-of-sample evidence, paper/shadow reliability evidence, and broker/exchange reconciliation testing exist.

Descriptive venue replication: [KuCoin failed-downside study](docs/PUBLIC_KUCOIN_REPLICATION_2026_10_10.md).

Monthly momentum state study: [fixed-definition rejection](docs/PUBLIC_MONTHLY_MOMENTUM_STATE_2026_10_10.md).

Public-strategy lane: [final development closure and completion audit](docs/PUBLIC_STRATEGY_FINAL_COMPLETION_2026_10_11.md). All three original candidates are rejected for promotion; the later eight-hour volume hypothesis also failed its declared gates. This report links every retained study, clarifies session clocks/overlaps and historical diagnostic limitations, and preserves all frozen protocols.

Fresh public bot research: [six new adaptations across batches 2–4](docs/PUBLIC_BOT_BATCH2_3_RESULTS_2026_10_11.md). All six fail their frozen screening gates. Source provenance, complete events, risk/cost controls and cumulative signal/model versus trading-cell counts are retained. This is spent historical development evidence; no viable candidate or native bot replication is claimed.

Protective simulator foundation: [minute primitives and pinned indicator audit](docs/PROTECTIVE_MINUTE_ENGINEERING_V1.md). Its original audit covers synthetic execution only; subsequent market screening is reported below. Untouched future confirmation remains required.

Protective bot batch5: [MAGen and Ichimoku Spot adaptation results](docs/PUBLIC_PROTECTIVE_BATCH5_RESULTS_V1.md). Both fail their pre-outcome screening gates. The committed evaluator retains minute execution uncertainty, inventory cutoff marks, funded BTC bounds and full cost/control diagnostics. No viable candidate or untouched confirmation pass is claimed.

Protective bot batch6: [SAR and signed money-flow adaptation results](docs/PUBLIC_PROTECTIVE_BATCH6_RESULTS_V1.md). Both fail the frozen historical gates. Primary source/default audits, independent synthetic mechanics checks, minute-close ROI timing, full event ledgers and cost/control diagnostics are retained. Untouched future confirmation remains required for any eventual candidate.

Public Candle batch7: [frozen design](docs/PUBLIC_CANDLE_BATCH7_DESIGN_V1.md), [results](docs/PUBLIC_CANDLE_BATCH7_RESULTS_V1.md), and [conditional research prospects](docs/PUBLIC_STRATEGY_CONDITIONAL_PROSPECTS_20261011.md). Historical screens do not establish viability; untouched future confirmation is required.

### Public trend batch 8

Frozen Supertrend default-intent research and its rejection are recorded in [results](docs/PUBLIC_TREND_BATCH8_RESULTS_V1.md), with [conditional prospects](docs/PUBLIC_STRATEGY_CONDITIONAL_PROSPECTS_BATCH8_V1.md). No candidate is promoted; future confirmation remains required.


### Public Dual Thrust batch 9

[Frozen design](docs/PUBLIC_DUAL_THRUST_BATCH9_DESIGN_V1.md), [results](docs/PUBLIC_DUAL_THRUST_BATCH9_RESULTS_V1.md) and [conditional prospects](docs/PUBLIC_STRATEGY_CONDITIONAL_PROSPECTS_BATCH9_V1.md) retain the independently audited rejection. No viable candidate or future confirmation pass is claimed.

## Public Vortex state research batch 10

[Design](docs/PUBLIC_VORTEX_BATCH10_DESIGN_V1.md), [results](docs/PUBLIC_VORTEX_BATCH10_RESULTS_V1.md), and [conditional prospects](docs/PUBLIC_STRATEGY_CONDITIONAL_PROSPECTS_BATCH10_V1.md). The frozen Spot adaptation was rejected on seven gates: 509 completed trades plus one cutoff, negative 80 bps stress mean and 70.3798% drawdown. Full lossless evidence, trial ledger and independent accounting review are retained. No viable candidate or future confirmation; frozen lanes preserved.

## Public NVI state research batch 11

[Design](docs/PUBLIC_NVI_BATCH11_DESIGN_V1.md), [results](docs/PUBLIC_NVI_BATCH11_RESULTS_V1.md), [conditional prospects](docs/PUBLIC_STRATEGY_CONDITIONAL_PROSPECTS_BATCH11_V1.md). Frozen volume-conditioned state rejected: 127 completed trades plus two cutoff marks; both uncertainty intervals and 60.06% drawdown failed. Full lossless evidence, trial ledger and independent accounting review retained. No viable candidate or future confirmation; frozen lanes preserved.
