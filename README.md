# Orderflow Edge Lab

Research-first infrastructure for short-horizon order-flow strategy research and paper execution.

**Version 1.0: research and manual paper release.** See the
[release guide](docs/RELEASE_1_0.md) for installation, verification, and operational boundaries.

## Safety boundary

This repository does not contain live broker or exchange order transmission. The execution layer is limited to paper and explicit approval workflows. No strategy is considered to have a profitable edge unless it survives genuine out-of-sample validation after realistic costs on data that was not used for discovery or tuning.

## Continuous multi-agent hardening

The repository includes a zero-additional-cost multi-agent control plane. The current deterministic checker IDs, count, compatibility groupings, and lead/release-manager responsibility are in the generated [Governance Map v2](docs/GOVERNANCE_MAP_V2.md). DeerFlow and Ruflo groupings are optional coordination labels; they do not equal the deterministic checker count or substitute for repository evidence.

```bash
orderflow-multi-agent --output artifacts/multi_agent_report.json
```

The legacy control plane remains historical evidence. Prospective v2 profiles distinguish an advisory/static report from a release profile: only a complete release profile may be `reviewable`. Both paths are read-only and do not place trades or promote a strategy. See [multi-agent hardening](docs/MULTI_AGENT.md) and [engineering governance v2](docs/PROCESS_V2_10_ENGINEERING_GOVERNANCE.md).

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

The versioned command registry declares whether each command is a flat script, dispatcher-only command, GUI exception, or internal surface. Flat scripts (for example `orderflow-multi-agent`) remain canonical; dispatcher-visible commands are available through a single dispatcher:

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
