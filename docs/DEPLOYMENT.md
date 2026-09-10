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

Version 2 writes and flushes a full journal checkpoint before replacing the state
file. Startup verifies the hash chain and the state's exact checkpoint anchor,
then recovers a complete journal-ahead transition once. Persistence failures block
further operations until restart. Partial tails, state tampering, and journal
truncation behind the stored anchor fail closed. Readiness requires a reconciled
checkpoint. Windows and POSIX operating-system locks cover both state and journal;
the OS releases ownership after a process crash. Persistent `.lock` files are normal
and must not be deleted to bypass ownership.

Existing version 1 state requires explicit `migrate_legacy=True` after operator
reconciliation. Migration preserves a `.v1.bak` copy and appends a checkpoint to
the existing journal. It cannot retroactively establish the integrity of old
state/journal pairs. A migration interrupted after the checkpoint can be recovered
by restarting. Do not delete backups to retry a failed migration blindly.

Operational readiness remains a limited diagnostic. Deletion or rollback of both
state and journal to a consistent older pair requires external backup/checkpoint
comparison to detect. A partial journal write is refused, not silently truncated.
Use a local filesystem with reliable flush and locking semantics; network shares
and storage-controller power-loss guarantees are outside these tests. Full state
checkpoints favor auditability at this paper-trading scale over log compactness.
