# MEXC Capture Quality v1

## Purpose

This layer audits the integrity of public MEXC order-flow captures used by the high-cadence market-state research. It is a data-quality diagnostic only. It does not select strategies, change state thresholds, alter previously frozen evidence, or authorize live trading.

Protocol: `config/mexc_capture_quality_v1.json`.

## Per-capture checks

For every expected symbol the audit records:

- feature-row and event-type counts;
- fraction of rows with a valid uncrossed best bid/ask;
- first/last local receipt timestamps and capture duration;
- local receipt timestamp regressions;
- observed depth-message count;
- compressed depth-range count;
- recovered true depth-gap count;
- stale depth-message count;
- gap/stale fractions;
- session reconnect count.

The exact feature JSONL byte stream is bound by SHA-256.

## Status semantics

`FAIL` means a structural capture problem was observed, currently including a missing expected symbol, malformed feature rows, or a receipt-time regression.

`WARN` means the capture completed but diagnostics such as a recovered depth gap, reconnect, unknown symbol, or reduced valid-book coverage were observed.

`PASS` means no configured structural defect or warning was observed.

A warning or failure is **not** permission to retroactively remove inconvenient market-state evidence. The report is preserved so later validity review can make an explicit, preregistered decision about data usability.

## Cumulative health

Each new quality report is stored beside its corresponding state-report batch. A cumulative quality aggregate reports:

- PASS/WARN/FAIL batch counts;
- reconnect totals;
- total hard-fail and warning reasons;
- per-symbol median valid-book coverage;
- aggregate true-gap and stale-update rates.

This makes deterioration in source quality visible across time rather than inspecting only whichever batch produced an interesting result.

## Artifact provenance

Cumulative high-cadence ledger recovery is branch-isolated.

A workflow run may restore a previous `high-cadence-state-ledger-v1` artifact only when that artifact's workflow run:

1. completed successfully; and
2. has the same GitHub `head_branch` as the current run.

Cleanup is also branch-aware. A PR validation artifact is therefore not eligible to become the parent of the `main` evidence ledger, and PR cleanup cannot delete the retained `main` ledger.

## Research boundary

The quality layer uses no strategy PnL and cannot:

- change strategy definitions;
- change capture cadence;
- change market-state thresholds;
- promote or reject a candidate by itself;
- exclude historical evidence retroactively;
- authorize leverage or live execution.
