# Multi-Agent Hardening Control Plane

The project includes a local, zero-additional-cost multi-agent control plane for continuous refinement and hardening. It does not require an external LLM API. Specialist agents execute deterministic repository checks in parallel and a release manager aggregates their evidence into a tamper-evident JSON report.

## Roles

| Agent | Responsibility |
| --- | --- |
| `data_integrity` | DeepCharts/dxFeed and MEXC adapters, timestamps, sequences, data provenance, causal eligibility |
| `research_validity` | Discovery/validation/holdout separation, freezes, holdout evidence, trial accounting, promotion binding |
| `strategy_validation` | Costs, fills, backtest assumptions, OOS evidence, overfitting controls |
| `execution_safety` | Approval-bound paper execution, risk checks, state/journal integrity, kill switches |
| `reliability_ci` | Compilation, tests, deployment diagnostics, packaging readiness |
| `observability_deployment` | Logs, hashes, runtime identity, manifests, operator diagnostics and documentation |
| `adversarial_reviewer` | Cross-checks unsupported edge claims, hidden holdout reuse, fail-open behavior and live-execution creep |
| release manager | Aggregates evidence, blocks on errors, preserves safety claims and prioritizes next actions |

## Run locally

```bash
python -m pip install -e .
orderflow-multi-agent --output artifacts/multi_agent_report.json
```

For a fast static pass that skips compile, unit-test and deployment subprocesses:

```bash
orderflow-multi-agent --skip-heavy --output artifacts/multi_agent_report.json
```

`--strict` returns a nonzero exit code when the release manager is blocked by a specialist error.

## Continuous execution

`.github/workflows/multi-agent-hardening.yml` runs the control plane hourly, on relevant pull requests, and on manual dispatch. The report is uploaded as a GitHub Actions artifact for 14 days.

The scheduled run has read-only repository permissions. It cannot place trades, mutate the repository, access private trading credentials, or silently promote a strategy.

## Evidence semantics

A successful report means the configured engineering and safety checks passed. It does not mean a strategy has a profitable edge. Every report explicitly preserves:

```text
live_order_transmission_supported = false
profitable_edge_established = false
verified_out_of_sample_evidence = false
```

Those fields are also covered by the report manifest hash. Modifying them after generation invalidates verification.

## Human/ChatGPT refinement loop

The deterministic agents are the continuous sensing layer. The higher-level refinement automation can read the latest repository state and agent findings, select the highest-value non-blocked improvement, implement it in a branch, run CI, and merge only after the required checks pass. Work that depends on user-only inputs, such as a genuine DeepCharts/dxFeed export or legitimate entitlement details, should be reported as a single minimal blocking action while unrelated hardening continues.

## Safety boundary

The multi-agent system is intentionally limited to research, validation, software reliability, paper/approval execution and deployment readiness. Automatic live broker or exchange order transmission remains outside the current release boundary.
