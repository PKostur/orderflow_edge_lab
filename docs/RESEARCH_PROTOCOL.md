# Research protocol

## Local future-observation audit

Run `python scripts/validate_future.py --observations observations.jsonl
--observed-through 2026-09-10T00:00:00Z --output audit.json` with actual audited
coverage. The report is created exclusively and will not overwrite an old report.

Each JSONL row requires `observation_id`, `candidate_id`, `timeframe`,
`setup_family`, `direction`, `path`, and `numeric_filters` matching the registry
exactly, plus `features` satisfying its numeric filters, timezone-aware
`event_time` and `outcome_time`, `gross_return_r`, `return_provenance`, positive
`cost_r`, `cost_model_id`, `cost_components_r`, and `source_kind: "real_market"`.
`return_provenance` must contain positive `entry_price`, `exit_price`, and
`initial_stop_price` values. For a long candidate the initial stop must be below
entry; for a short candidate it must be above entry. The auditor recomputes gross
R as directional price change divided by the absolute entry-to-initial-stop
distance and rejects a row when the reported `gross_return_r` does not match that
calculation. This catches arithmetic and direction errors but does not prove that
the supplied prices were executable fills.

`cost_components_r` must contain nonnegative `fees`, `slippage`, `spread`, and
`other` values whose sum equals `cost_r`. A zero-cost real-market observation is
rejected because frictionless observations are not acceptable evidence for this
execution-oriented research. A candidate may use only one transaction-cost model
within a validation audit. Materially different execution assumptions require a
separately frozen candidate so incompatible cost regimes cannot be pooled into one
return summary. The source, price, and cost labels remain operator declarations,
not independent proof.

Input must be chronological. Duplicate identities, unfrozen observations,
unsupported filters, nonfinite values, missing or inconsistent return provenance,
invalid stop placement, missing cost provenance, inconsistent cost decomposition,
mixed transaction-cost models, zero or negative transaction costs, and outcomes
that finish at or before their event time are rejected. Every outcome must finish
within the caller-supplied audited coverage timestamp.

The report hashes the exact parsed bytes, retains empty and unfinished windows,
recomputes directional gross R from supplied prices, and computes descriptive net
returns after supplied costs. It always sets `deployment_eligible` and
`verified_out_of_sample_evidence` to false. It cannot verify export authenticity,
missing observations, price/fill authenticity, execution horizons, freeze
provenance, fill realism, cost calibration, or independence. Those require
independently audited market data and a predeclared protocol; a successful audit
is not edge evidence.

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
verified out-of-sample evidence. Dataset hashes, timestamps, return provenance,
cost provenance, and freeze provenance need independent verification; paper
readiness remains separate from this gate.

Changing timeframe, path, direction, setup family, horizon, a numeric filter, or
material execution assumptions creates a new candidate or cost-model version and
requires a new future-only evaluation boundary where appropriate.

## Sequence

1. Define the response variable and executable horizon.
2. Freeze candidate rules and all thresholds.
3. Freeze the return convention, including entry, exit, initial stop, and the
   precise outcome horizon used to derive R.
4. Freeze and identify the transaction-cost model, including fees, spread,
   slippage, and any additional cost component.
5. Hash configuration and input data.
6. Run complete chronological future windows.
7. Mark windows incomplete when the predeclared minimum event and active-day
   counts are not met.
8. Report raw directional returns and, where applicable, market/beta-adjusted
   and matched-control excess returns.
9. Adjust families of hypothesis tests for multiplicity.
10. Keep a final holdout inaccessible to ordinary discovery output.
11. Use trade-level or sub-minute data when a bar can hit stop and target in the
    same interval.
12. Treat paper/shadow execution evidence as separate from statistical edge
    evidence.

## No profitability claim

A positive in-sample result, a synthetic test, or one positive future window
does not establish a profitable edge. Live transmission remains outside this
repository.
