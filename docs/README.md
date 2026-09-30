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
- [DON8_REVIEW_RUNBOOK](DON8_REVIEW_RUNBOOK.md) — operational steps for the 2026-10-23 DON8 review (packet generation, robustness context, coverage audit, record and archive).
- [VALIDATION_TOOLING](VALIDATION_TOOLING.md) — validation statistics, pre-registration contract, frozen hash manifest and workflow/artifact contract.

### Wait-window observability commands

Aggregation and reporting only; none of these counts evidence, computes a verdict, or promotes anything.

| Command | Purpose |
|---|---|
| `orderflow review-clock` | Elapsed days and remaining days for each preregistered watch. |
| `orderflow capture-health` | Descriptive inventory of recorded captures; `--fail-on-stoppage` exits 3 when captures have stopped. |
| `orderflow review-packet` | Hash-pinned review skeleton from a frozen counting report; every verdict cell is left empty. |
| `orderflow artifact-coverage` | Whether the artifacts a predeclared review needs are still retrievable, against `config/evidence_retention_requirements_v1.json`. |
| `orderflow ops-digest` | One daily digest of clock + capture health + ledger batch count + coverage findings. |

Scheduled runs: `prospective-review-clock-v1.yml` (daily), `capture-health-watch-v1.yml` (daily, alarms on stoppage), and `wait-window-ops-digest-v1.yml` (daily, publishes the digest artifact).

### Validation statistics and research hygiene

See [VALIDATION_TOOLING](VALIDATION_TOOLING.md) for the rules (cluster resampling, post-hoc
labelling, caller-declared thresholds) and the contract every new watch must satisfy.

| Command | Purpose |
|---|---|
| `orderflow robustness` | Descriptive robustness of a frozen forward report: cluster bootstrap interval, minimum detectable effect at the frozen gate, concentration, friction sensitivity, control arms and negative controls. |
| `orderflow research-hygiene` | Pre-registration audit, frozen-definition hash check, workflow-to-artifact contract, inspection registry. Exits 2 at or above the chosen severity. |
| `orderflow discovery-screen` | Discovery-time economics screen: does the candidate clear the declared break-even multiple, and does the declared cost match measured friction? |
| `orderflow orthogonality` | Redundancy clusters, incremental information against existing regime variables, and leave-one-out stability. |

Scheduled run: `research-hygiene-v1.yml` (weekly and on demand).

## Command aliases and deprecation

Several research commands exist as a superseding pair or trio of frozen generations. The older name is kept so published workflows and historical records continue to run; it is **deprecated** for new work and must not be reinterpreted as a different specification.

| Deprecated alias | Prefer | Note |
|---|---|---|
| `orderflow-market-state-aggregate` | `orderflow-market-state-aggregate-v1-1`, then `-v1-2` | Each version reads its own frozen protocol; they are not interchangeable. |
| `orderflow-state-promotion-report` | `orderflow-state-promotion-report-v1-2` | Same rule: versioned protocol, frozen separately. |
| `orderflow-strategy-conditioning-freeze` | `orderflow-strategy-conditioning-freeze-v1-1` | Historical freezes must keep using the version they were frozen under. |
| `orderflow-sentiment-monitor` | `orderflow-sentiment-monitor-v1-1` | Versioned protocol, frozen separately. |

Removing an alias is a separate, explicitly-approved change: a deprecated name may still appear in a frozen record, and deleting it would make that record unreproducible. Flat `orderflow-<name>` scripts remain canonical alongside the `orderflow <name>` dispatcher.

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
