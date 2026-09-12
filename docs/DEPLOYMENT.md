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

## Manual paper interface

Install the package with `python -m pip install -e .`, then run:

```text
python scripts/paper_control.py init --equity 10000
python scripts/paper_control.py status
python scripts/paper_control.py submit --intent intent.json --export trades.csv --validation-report validation.json --economics config/economics.json --candidate-freeze research/candidate-freeze.json --holdout-audit research/holdout-audit.json
python scripts/paper_control.py approve INTENT_ID --token APPROVAL_TOKEN --market market.json
python scripts/paper_control.py reject INTENT_ID --reason "operator declined"
python scripts/paper_control.py close INTENT_ID --market market.json --reason "operator close"
python scripts/paper_control.py kill
python scripts/paper_control.py release
```

Use global `--state`, `--journal`, and optional `--policy` before the command to
select files. Defaults live in ignored `runtime/`. Version 1.0 binds risk policy
and instrument assumptions into durable checkpoints. The CLI reuses the stored
policy unless supplied explicitly; changed settings fail closed rather than
repricing an existing run. Start a separately named, reconciled run for new settings.
`init` opens/reconciles existing state and never resets its equity. `migrate` is
the explicit legacy migration command after manual reconciliation. Older version 2
state without bound settings must be flat with an empty queue before migration.

Intent JSON contains `strategy_id`, `symbol`, `side`, `entry_reference`, `stop`,
`target`, and timezone-aware `signal_time`. Market JSON contains `symbol`, `bid`,
`ask`, and timezone-aware `timestamp`. Quotes and signals must be fresh at command
execution; saved examples become stale. The interface has no override for the
current clock.

`submit` is fail closed in three independent layers. First, it recomputes the
strategy promotion decision from the supplied validation report and economics
policy. Second, the exact validation report must bind to a valid candidate-freeze
manifest and a valid holdout audit. The candidate, registry hash, candidate
specification hash, holdout observations hash, frozen holdout partition, and
reverified source bytes must all agree. A positive validation report cannot enter
the paper queue by itself. Third, the supplied market export must contain at least
100 qualifying events, a fresh BBO, and a passing quality report.

The intent `strategy_id` must identify exactly one candidate in the validation
report and in the frozen candidate set. A blocked or malformed promotion or
provenance decision cannot enter the pending queue and does not mutate state or the
journal. The exact fresh export hash, recomputed promotion assessment, candidate
freeze file hash, holdout audit file hash, validation report file hash, and
economics file hash are stored in submission evidence. That evidence is included in
the approval binding, so an approval token cannot silently refer to a different
research provenance chain.

`approve` requires the integrity token returned by `submit` and rechecks a fresh
market snapshot before a paper fill. The token is an audit binding rather than an
authentication secret. It binds the operator-visible proposal to its submitted
intent, size, expiry, source evidence, execution configuration, and submission
market snapshot. Market movement that changes allowable size invalidates approval.

The low-level PaperEngine API remains available for engineering tests and assumes
upstream signal/data validation. The supported operator CLI is stricter and will
not accept research-only validation artifacts or validation artifacts detached
from their frozen holdout provenance. This does not prove profitability: paper
eligibility requires explicit upstream OOS certification and does not turn
historical results into new evidence.

`status` is read-only and does not recover state. It reports pending and open
positions even when the kill switch is engaged, if checkpoint integrity passes.
`kill` blocks entries but does not automatically close positions. Use explicit
paper closes with fresh quotes. It also cancels queued intents so releasing the
switch cannot revive old approvals. `expire` removes elapsed approvals and journals
their identities. Execution timestamps cannot move backward, including after
restart. Open positions reserve their modeled stop losses against the remaining
daily loss budget. A failed persistence operation has an uncertain
outcome until restart/reconciliation; do not retry blindly.

## Hardening limits and checks

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

For unbound pre-1.0 version 2 state, close positions and clear the queue using the
original version before migration, then supply the original policy to `migrate`.
Do not edit a checkpoint by hand to add configuration fields.

Operational readiness remains a limited diagnostic. Deletion or rollback of both
state and journal to a consistent older pair requires external backup/checkpoint
comparison to detect. A partial journal write is refused, not silently truncated.
Use a local filesystem with reliable flush and locking semantics; network shares
and storage-controller power-loss guarantees are outside these tests. Full state
checkpoints favor auditability at this paper-trading scale over log compactness.
