# Multi-agent trial environment

This directory is an isolated research experiment. It is not imported by the production package and contains no broker/exchange transmission path.

## Why multi-agent?

A multi-agent system decomposes one trading decision into specialized, independently testable roles. The intended benefit is not that several language models are automatically smarter than one model. The benefit is separation of concerns, disagreement, vetoes, and an auditable record of why a candidate was accepted or rejected.

The trial mirrors the useful part of architectures such as TradingAgents while keeping safety-critical work deterministic and zero-cost:

- `PROBE`: volume/order-flow evidence.
- `PRISM`: spread/liquidity and higher-timeframe regime.
- `SCALE`: deterministic position sizing. No LLM is allowed to size risk.
- `LIMIT`: deterministic expectancy/risk constraints.
- `EINSTEIN`: independent skeptic/veto layer.
- Ledger: append-only structured record of every decision.

Every agent receives the same immutable point-in-time `MarketSnapshot`. No agent may fetch future data, mutate another agent's evidence, or transmit an order. The coordinator is fail-closed: any veto rejects the candidate, and hard vetoes are reserved for non-negotiable risk/data constraints.

## Important research rule

A higher rejection rate is not evidence of an edge. The experiment only becomes interesting if the gated system improves pre-registered out-of-sample metrics after fees/slippage relative to the same strategy without the agent gate. Rejected candidates must also be retained so counterfactual outcomes can be measured without survivorship bias.

## Zero-additional-cost plan

Phase 1 uses only Python's standard library and deterministic agents. This lets us test orchestration, causal snapshots, decision logging, disagreement, veto logic, and ablation analysis without paying for LLM calls.

Phase 2 can add an optional local-model adapter (for example Ollama) behind the same `Agent` protocol. LLM agents should only produce bounded structured assessments. They must never override hard risk limits or directly call a broker.

Phase 3 can feed point-in-time DeepCharts/dxFeed-derived features into the snapshot once the local data path is available. The feed remains a data source only; observing a DeepCharts endpoint does not establish independent dxFeed API entitlement.

## Running the isolated tests

From the repository root:

```bash
python -m unittest experiments.multi_agent_trial.test_engine -v
```

The experiment currently tests:

- deterministic pass/reject behavior,
- non-positive post-cost expectancy veto,
- adverse BTC-shock veto,
- wide-spread veto,
- deterministic risk sizing,
- snapshot provenance hashing,
- rejection of timezone-naive timestamps,
- structured append-only ledger output.

## What to measure next

For each historical candidate, run two paths using exactly the same causal snapshot:

1. Baseline strategy decision.
2. Baseline + multi-agent gate.

Store the decision before revealing the future outcome. Then compare OOS trade count, expectancy after costs, hit rate, drawdown, rejected-winner rate, rejected-loser rate, and performance by regime. Run agent ablations (`all`, `minus PROBE`, `minus PRISM`, etc.) so any incremental value can be attributed rather than assumed.
