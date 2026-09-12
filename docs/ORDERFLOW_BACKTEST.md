# Exploratory order-flow backtest

`orderflow-backtest` evaluates pre-specified short-horizon signals from the MEXC public feature stream. It is an exploratory screening tool, not a profitability certificate.

## Fixed first-pass signal families

- `cvd`: 10-second aggressive trade-flow ratio at least +/-0.25 with at least 5 prints.
- `book`: top-10 reconstructed book imbalance at least +/-0.25.
- `microprice`: normalized microprice displacement from mid at least +/-0.20 of half-spread.
- `aligned`: CVD, book imbalance, and microprice all point the same way.
- `aligned_btc`: `aligned` plus the latest causal BTC aggressive-flow sign agrees.

Signals have a 2-second same-family/same-direction cooldown. Initial forward horizons are 1, 5, 15, and 30 seconds. These values are frozen before the first fresh automated sample to reduce tuning-by-inspection.

## Execution model

Long signals cross the spread at the current ask and liquidate against a future bid. Shorts enter at the current bid and liquidate against a future ask. Reports show 0, 4, and 8 basis-point round-trip fee assumptions in addition to the paid spread. This deliberately penalizes very short-horizon signals.

## Evidence status

A fresh sample may tell us whether features and economics are behaving sensibly. A few minutes of data cannot establish an edge. Threshold changes made after inspecting a sample spend that sample for discovery and must be evaluated on later untouched data. Promotion still requires the repository's normal candidate freeze, holdout, trial-ledger, validation, and paper-execution controls.

No command in this path sends an order.
