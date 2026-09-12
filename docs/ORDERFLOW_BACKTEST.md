# Exploratory order-flow backtest

`orderflow-backtest` evaluates pre-specified short-horizon signals from the MEXC public feature stream. It is an exploratory screening tool, not a profitability certificate.

## Fixed first-pass signal families

- `cvd`: 10-second aggressive trade-flow ratio at least +/-0.25 with at least 5 prints.
- `book`: top-10 reconstructed book imbalance at least +/-0.25.
- `microprice`: normalized microprice displacement from mid at least +/-0.20 of half-spread.
- `aligned`: CVD, book imbalance, and microprice all point the same way.
- `aligned_btc`: `aligned` plus the latest causal BTC aggressive-flow sign agrees.

Signals have a 2-second same-family/same-direction cooldown. Initial forward horizons are 1, 5, 15, and 30 seconds. These values are frozen in `config/orderflow_discovery_v1.json`; scheduled discovery must not tune them batch by batch.

## Execution model

Long signals cross the spread at the current ask and liquidate against a future bid. Shorts enter at the current bid and liquidate against a future ask. Reports show 0, 4, and 8 basis-point round-trip fee assumptions in addition to the paid spread. This deliberately penalizes very short-horizon signals.

Causality follows local observation order (`received_at_ns`). Exchange timestamps remain evidence fields but are not allowed to reorder independently arriving WebSocket channels after the fact.

## Continuous discovery

`Continuous Order-Flow Discovery` runs hourly on the public repository. Each run records 15 minutes of fresh ENA/BTC public MEXC order flow, applies the unchanged discovery-v1 rules, and stores a compact report. The first four successful scheduled runs therefore accumulate one hour of market observation without retuning thresholds.

`orderflow-discovery-aggregate` combines recent reports only when their configuration exactly matches the frozen protocol and their source hashes are unique. It treats each capture batch as the primary dependence cluster. Event-weighted means are reported only as descriptive values because signals inside one capture can be highly correlated.

The aggregate reports batch mean and median return, the fraction of positive batches, batch standard error, and an approximate 95% interval. The protocol requires at least 10 independent batches before those interval summaries are marked inference-ready. That remains discovery evidence, not untouched holdout evidence.

Raw and feature evidence are retained briefly to limit artifact storage, while compact reports remain longer. Every backtest keeps the source SHA-256, and every aggregate hashes its component reports and carries a tamper-evident manifest.

## Evidence status

A fresh sample may tell us whether features and economics are behaving sensibly. Discovery batches can identify which signal families deserve a later frozen candidate, but they cannot establish an edge. Any candidate revision after inspecting discovery data must be frozen and evaluated on later untouched data through the repository's candidate-freeze, holdout-audit, trial-ledger, validation, promotion, and approval-bound paper controls.

No command in this path sends an order.
