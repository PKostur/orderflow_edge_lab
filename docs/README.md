# Documentation index

Start here, in order:

1. [README](../README.md) — project overview, priorities, safety boundary.
2. [RELEASE_1_0](RELEASE_1_0.md) — what shipped, install, verification, operational boundaries.
3. [DEPLOYMENT](DEPLOYMENT.md) — operator and migration instructions for the paper execution lifecycle.
4. [MEXC_ORDERFLOW](MEXC_ORDERFLOW.md) — the primary zero-cost market-data path: recorder, replay, depth schema.
5. [RESEARCH_PROTOCOL](RESEARCH_PROTOCOL.md) — discovery/validation/holdout separation and audit rules.

Install note: backtest/tournament/session-research commands additionally require the
optional research extra — `python -m pip install -e ".[research]"` (numpy, pandas,
scikit-learn). CI installs it; data recording, replay, paper execution, and the
engineering tests do not need it.

## Research validity and promotion

- [PROMOTION_GATE](PROMOTION_GATE.md) — what a promotion requires: freeze, holdout audit, trial ledger, economics, reliability.
- [REGIME_RESEARCH](REGIME_RESEARCH.md) / [REGIME_RESEARCH_V1_3](REGIME_RESEARCH_V1_3.md) — market-state research principle and pre-registered families.
- [STRATEGY_CONDITIONING](STRATEGY_CONDITIONING.md) — conditioning strategies on market state without PnL leakage.
- [PRICE_STRATEGY_TOURNAMENT](PRICE_STRATEGY_TOURNAMENT.md) — tournament framework and robustness rules.

## Data paths

- [DXFEED](DXFEED.md) — DeepCharts/dxFeed adapter and entitlement probe.
- [DXFEED_CONNECTION_SAFETY](DXFEED_CONNECTION_SAFETY.md) — credential handling and connection safety.
- [DATA_LINEAGE](DATA_LINEAGE.md) — provenance, hashes, and lineage of research inputs.
- [ENDPOINT_CAPTURE](ENDPOINT_CAPTURE.md) — endpoint capture and discovery mechanics.
- [ZERO_COST_DATA_PATH](ZERO_COST_DATA_PATH.md) — zero-additional-cost data strategy.

## Reliability and operations

- [MULTI_AGENT](MULTI_AGENT.md) — the deterministic hardening control plane and its report semantics.
- [SESSION_AUDIT](SESSION_AUDIT.md) / [SESSION_METRICS](SESSION_METRICS.md) — session audit and metrics.
- [DEADLINE_RELEASE_RUNBOOK](DEADLINE_RELEASE_RUNBOOK.md) — standalone install/run/release without external services.

## Research records

- Research lanes, watches, and terminal states are indexed in [`research/INDEX.md`](../research/INDEX.md).
- The current operational state (decision dates, stop rules, watches) is [`STATUS.md`](../STATUS.md) at the repository root.

## Remaining protocol documents

The following documents record specific frozen methodologies or trials; read them
in the context of the lane they belong to (see `research/INDEX.md`):

BEST_BETS_RESEARCH_FOCUS_2026-09-15 · DEADLINE_RELEASE_RUNBOOK ·
GAMMA_EXPOSURE_TRIAL_V1 · MARKOV_PRICE_DIAGNOSTICS_V1 ·
METHODOLOGY_EXPANSION_V1 · MULTI_COIN_NEWS_RESEARCH ·
ORDERFLOW_BACKTEST · SELF_IMPROVEMENT_V1_REPORT
