# Deployment readiness

Current target: research, replay, paper execution, and manual approval only.

## Required before unattended paper/shadow operation

- pinned Python environment
- CI passing on supported Python versions
- persistent state directory
- append-only journal retained off process
- single state owner
- restart test with an open paper position
- stale data rejection test
- duplicate intent rejection test
- approval-expiry test
- kill-switch flatten test
- clock synchronization
- market-data entitlement confirmed
- alerting for process death and data staleness

## Required before any future live adapter is even considered

- multiple complete fresh out-of-sample windows
- cost and slippage sensitivity
- sufficient event counts and active-day coverage
- paper/shadow reconciliation against actual market prints
- explicit broker/exchange reconciliation design
- protective-stop failure handling
- independent capital/risk caps
- a separate reviewed live adapter

This repository deliberately fails a deployment scan if common live-order
method markers appear in `src/`.
