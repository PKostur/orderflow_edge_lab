# Research protocol

## Local future-observation audit

Run `python scripts/validate_future.py --observations observations.jsonl
--observed-through 2026-09-10T00:00:00Z --output audit.json` with actual audited
coverage. The report is created exclusively and will not overwrite an old report.

Each JSONL row requires `observation_id`, `candidate_id`, `timeframe`,
`setup_family`, `direction`, `path`, and `numeric_filters` matching the registry
exactly, plus `features` satisfying its numeric filters, timezone-aware
`event_time` and `outcome_time`, `gross_return_r`, nonnegative `cost_r`, and
`source_kind: "real_market"`. The source label is an operator declaration, not
proof. Input must be chronological; duplicate identities, unfrozen observations,
unfinished outcomes, unsupported filters, and nonfinite values are rejected.

The report hashes the exact parsed bytes, retains empty and unfinished windows,
and computes descriptive net returns after supplied costs. It always sets
`deployment_eligible` and `verified_out_of_sample_evidence` to false. It cannot
verify export authenticity, missing observations, outcome calculation, execution
horizons, freeze provenance, or independence. Those require independently audited
market data and a predeclared protocol; a successful audit is not edge evidence.

## Evidence boundary

Any observation inspected while selecting, filtering, tuning, or modifying a
candidate is discovery data. The frozen registry records the last spent-data
timestamp for each candidate. Evidence for that candidate must occur strictly
after that timestamp.

The future-only boundary is the later of `spent_through` and `frozen_at`.
`sequential_windows` requires an explicit `observed_through` coverage timestamp
before any window can be complete. Event counts alone cannot establish that
the window has ended. Empty windows are retained and incomplete tails remain
incomplete. Coverage is caller-supplied and must come from audited data coverage,
not the time of the latest selected signal.

Readiness reports do not accept a manifest's self-reported freeze flag as
verified out-of-sample evidence. Dataset hashes, timestamps, and freeze provenance
need independent verification; paper readiness remains separate from this gate.

Changing timeframe, path, direction, setup family, horizon, or a numeric filter
creates a new candidate and a new future-only eligibility boundary.

## Sequence

1. Define the response variable and executable horizon.
2. Freeze candidate rules and all thresholds.
3. Hash configuration and input data.
4. Run complete chronological future windows.
5. Mark windows incomplete when the predeclared minimum event and active-day
   counts are not met.
6. Report raw directional returns and, where applicable, market/beta-adjusted
   and matched-control excess returns.
7. Adjust families of hypothesis tests for multiplicity.
8. Keep a final holdout inaccessible to ordinary discovery output.
9. Use trade-level or sub-minute data when a bar can hit stop and target in the
   same interval.
10. Treat paper/shadow execution evidence as separate from statistical edge
    evidence.

## No profitability claim

A positive in-sample result, a synthetic test, or one positive future window
does not establish a profitable edge. Live transmission remains outside this
repository.
