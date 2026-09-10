# Orderflow Edge Lab

Research-first infrastructure for short-horizon order-flow strategy research and paper execution.

## Safety boundary

This repository does not contain live broker order transmission. The execution layer is limited to paper and explicit approval workflows. No strategy is considered to have a profitable edge unless it survives genuine out-of-sample validation after realistic costs on data that was not used for discovery or tuning.

## Current priorities

1. Use existing DeepCharts/dxFeed access where the entitlement permits external access.
2. Keep a zero-additional-cost data path wherever possible.
3. Preserve strict separation between discovery, validation, and final holdout data.
4. Fail closed on stale, malformed, incomplete, duplicated, crossed, or low-quality market data.
5. Make research runs reproducible with frozen configuration, input hashes, and run manifests.
6. Paper trade and approval-test before any future broker integration is considered.

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

Local export validation and all engineering tests require no paid API or external
service. Real market-data access and coverage still depend on your entitlement.

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

Live order transmission is deliberately absent. Any future live adapter should be introduced only after sufficient fresh out-of-sample evidence, paper/shadow reliability evidence, and broker reconciliation testing exist.
