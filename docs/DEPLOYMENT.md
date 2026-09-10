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
# Hardening limits and checks

Paper sizing uses the current anticipated fill, adverse stop slippage, and
round-trip commissions. It also caps planned loss at the remaining daily loss
allowance. These are modeling assumptions: gaps can exceed the planned loss.
Approval revalidates the market; manual `PaperEngine.reject` persists the decision
and its reason in the hash-chained journal. Exit snapshots must be fresh, and
overnight closes book P&L to the closing UTC day.

Readiness and engine startup share state-value validation. Nonfinite balances,
malformed pending intents and positions, invalid counters, and invalid dates
fail closed. A killed engine is not reported as paper-ready.

Operational readiness is a limited diagnostic, not an unattended-deployment
certification. The current state and journal writes are separate; crash-atomic
reconciliation remains unfinished. The lock uses a persistent exclusive file;
an abnormal process exit can require operator recovery. A valid hash chain alone
does not prove that no trailing records were deleted. Keep state and journal
backups and reconcile both before restarting after an interrupted write.
