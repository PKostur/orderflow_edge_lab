# Research protocol

## Local future-observation audit

Run:

```bash
python scripts/validate_future.py \
  --observations observations.jsonl \
  --source-data deepcharts_export.csv \
  --observed-through 2026-09-10T00:00:00Z \
  --output audit.json
```

Repeat `--source-data` when observations reference more than one raw export. The
CLI hashes every supplied file locally and rejects an observation whose declared
`dataset_sha256` does not match one of those exact byte streams. The report is
created exclusively and will not overwrite an old report or any input file.

Each JSONL row requires `observation_id`, `candidate_id`, `timeframe`,
`setup_family`, `direction`, `path`, and `numeric_filters` matching the registry
exactly, plus `features` satisfying its numeric filters, timezone-aware
`event_time` and `outcome_time`, `source_provenance`, `gross_return_r`,
`return_provenance`, positive `cost_r`, `cost_model_id`, `cost_components_r`, and
`source_kind: "real_market"`.

`source_provenance` must contain the SHA-256 of the raw source dataset and a stable
record identifier from that dataset. Within one frozen candidate, the same
`dataset_sha256` plus `record_id` pair cannot be counted twice, even when the
caller changes `observation_id`. This reduces accidental duplicate evidence and
makes reuse of raw DeepCharts/dxFeed exports visible in the report. The CLI also
verifies that each declared dataset hash matches a supplied local raw export.
This proves byte identity with that local file, not that the export itself is
complete or authentic.

`return_provenance` must contain positive `entry_price`, `exit_price`, and
`initial_stop_price` values. For a long candidate the initial stop must be below
entry; for a short candidate it must be above entry. The auditor recomputes gross
R as directional price change divided by the absolute entry-to-initial-stop
distance and rejects a row when the reported `gross_return_r` does not match that
calculation. This catches arithmetic and direction errors but does not prove that
the supplied prices were executable fills.

`cost_components_r` must contain nonnegative `fees`, `slippage`, `spread`, and
`other` values whose sum equals `cost_r`. An observation that declares no
transaction costs is rejected because cost-free observations are not acceptable
evidence for this execution-oriented research. A candidate may use only one transaction-cost model
within a validation audit. Materially different execution assumptions require a
separately frozen candidate so incompatible cost regimes cannot be pooled into one
return summary. The source, price, and cost labels remain operator declarations,
not independent proof.

Input must be chronological. Duplicate identities, duplicate raw source records
within a candidate, unfrozen observations, unsupported filters, nonfinite values,
missing or malformed source provenance, source hashes not backed by a supplied raw
file, missing or inconsistent return provenance, invalid stop placement, missing
cost provenance, inconsistent cost decomposition, mixed transaction-cost models,
zero or negative transaction costs, and outcomes that finish at or before their
event time are rejected. Every outcome must finish within the caller-supplied
audited coverage timestamp.

The report hashes the exact parsed observation bytes, records the locally verified
source file hashes, retains empty and unfinished windows, exposes all source
dataset hashes used by each candidate, recomputes directional gross R from
supplied prices, and computes descriptive net returns after supplied costs. It
always sets `deployment_eligible` and `verified_out_of_sample_evidence` to false.
It cannot verify export completeness or upstream authenticity, missing market
records, price/fill authenticity, execution horizons, freeze provenance, fill
realism, cost calibration, or independence. Those require independently audited
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
verified out-of-sample evidence. Dataset hashes, raw record identities,
timestamps, return provenance, cost provenance, and freeze provenance need
independent verification; paper readiness remains separate from this gate.

Changing timeframe, path, direction, setup family, horizon, a numeric filter, or
material execution assumptions creates a new candidate or cost-model version and
requires a new future-only evaluation boundary where appropriate.

## Sequence

1. Define the response variable and executable horizon.
2. Freeze candidate rules and all thresholds.
3. Hash and retain the raw source export before deriving observations.
4. Freeze the return convention, including entry, exit, initial stop, and the
   precise outcome horizon used to derive R.
5. Freeze and identify the transaction-cost model, including fees, spread,
   slippage, and any additional cost component.
6. Hash configuration and derived observation data.
7. Run complete chronological future windows.
8. Mark windows incomplete when the predeclared minimum event and active-day
   counts are not met.
9. Report raw directional returns and, where applicable, market/beta-adjusted
   and matched-control excess returns.
10. Adjust families of hypothesis tests for multiplicity.
11. Keep a final holdout inaccessible to ordinary discovery output.
12. Use trade-level or sub-minute data when a bar can hit stop and target in the
    same interval.
13. Treat paper/shadow execution evidence as separate from statistical edge
    evidence.

## Required review methods (added 2026-10-09)

Every pre-registration written from this date names, before its data exists, how
items 9 and 10 above are carried out. The helpers live in
`src/orderflow_edge_lab/review_methods.py`. Registrations made before this date
keep their own rules unless a separate, stricter review is registered before
their first forward day.

1. **Action-matched null.** Compare the strategy with randomised books that make
   the same decisions in kind: the same number of longs and shorts, the same
   gross and the same dates, on randomly chosen available assets (or, for event
   studies, the same number of events per coin and month at random times). Use at
   least 999 draws and a fixed seed. Report the empirical p-value, not only the
   t-statistic against zero.
2. **One declared test family, Benjamini-Hochberg corrected.** List every
   hypothesis test in the registration, and declare a q level (default 0.10). A
   test counts only if it passes its own threshold and its BH q-value is at or
   below q.
3. **Masking for any LLM step.** Inputs to a language model have tickers, asset
   names, dates, weekdays and years replaced by placeholders. Before the model's
   output is used, a masked versus unmasked comparison on a held-back sample must
   show no material difference.
4. **Single look.** No hypothesis statistic is computed before the review date.
   Code enforces this with `assert_single_look`, and the review date is not moved
   after any data has been collected.
5. **Anti-gaming checks on any optimised or selected rule.** Report whether the
   improvement is only position size (scale invariance), whether one day
   carries more than half the gain (concentration), whether a chosen parameter
   sits on the edge of its grid (boundary), and the round-trip cost at which the
   edge disappears (cost wall). Each flag is reported, never silently fixed.

## No profitability claim

A positive in-sample result, a synthetic test, or one positive future window
does not establish a profitable edge. Live transmission remains outside this
repository.
