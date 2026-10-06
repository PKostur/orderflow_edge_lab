# Discovery Governance v2 — Prospective Family Closure and Graduation

**Status:** additive, offline, opt-in successor implementation for stage 04.  It does **not** alter `trial_ledger.py`, `candidate_freeze.py`, frozen discovery reports/configurations, or `research/discovery_v2/` artifacts.  A successful local verification remains **non-authoritative**: it does not establish provider completeness, durable external retention, independent-engine calibration, a profitable edge, promotion approval, or live-order capability.

## Purpose and boundaries

`orderflow_edge_lab.discovery_governance_v2` turns the prospective D0 route into a series of content-hashed objects:

1. immutable `build_family_declaration_v2(...)` before runs;
2. `append_family_ledger_event_v2(...)` snapshots with an event hash chain;
3. `close_family_v2(...)` over every declared sibling;
4. caller-declared `build_economics_eligibility_v2(...)`;
5. provenance-bound `build_cluster_matrix_v2(...)` and `build_cluster_inference_v2(...)`;
6. aligned `build_benchmark_assessment_v2(...)`;
7. `build_graduation_binding_v2(...)`; and only then
8. `build_candidate_freeze_v2(...)`.

The v2 API intentionally has **no registry-path input** for a freeze.  It rejects a graduation unless it is exactly `ELIGIBLE` and `REPLICATION_PENDING`; it rejects an incomplete, failed, or tampered graduation.  `REPLICATION_PENDING` is still D0 discovery evidence—not validation, promotion, a profitability claim, or a trading authorization.

## Ledger and closure procedure

The family declaration binds caller-provided scope, variant axes, cost cases, adaptive decision rules, source-set membership, policy identity, and family creation time.  Each candidate identity contains a stable candidate ID, specification digest, and creation time.

A ledger event is one of:

- `RUN_DECLARED`: contains no result information; or
- `RUN_TERMINAL`: references the exact preceding declaration, preserves its declared run scope, and must carry a recorded-at UTC time strictly **before** the declared result-inspection time.

Terminal statuses are `COMPLETED`, `FALSIFIED`, `ABANDONED`, and `INVALID_DATA`. `COMPLETED` and `FALSIFIED` require a result digest. `zero_trade` is explicit and remains in the closure member matrix.  A candidate cannot have a duplicate declaration or terminal event; a terminal event cannot appear without a declaration.

Each CLI successor ledger is written with exclusive creation (`"x"`) to its output path. It never edits its input ledger. `verify_family_closure_v2(closure, family_ledger=later_ledger)` rejects a closure against a ledger with post-closure additions, altered entries, or a changed head hash.

> **Activation blocker:** A local hash chain cannot prove that an operator did not run an unlogged experiment or that local files satisfy durable retention. Activate this procedure only with an approved prospective operating policy and durable, append-only external retention/retrieval evidence. Do not relabel historical/open family completeness as verified.

## Economics eligibility

`build_friction_policy_v2(...)` requires the caller to freeze the quantile, usable coverage fraction, maximum skipped fraction, required strata, quotes-per-stratum, execution horizon, and fee-provenance digest. Quantiles below the median are rejected as non-conservative.

`build_economics_eligibility_v2(...)` distinguishes:

- `report_integrity_ok`: report-shape/integrity information; from
- `friction_evidence_eligible`: complete usable measured evidence; and
- `economics_eligible`: the graduation gate.

Any failed/indeterminate screen, incomplete coverage, insufficient usable coverage, excessive skips, missing required stratum, declared cost below the required quantile floor, or nonpositive post-floor headroom is **ineligible**. Observed zero remains available through the shared coverage contract; missing is never converted to zero.

The module CLI supports report-only output and `--require-clear`; the latter returns exit code **3** for ineligible economics while still allowing the output artifact to be archived.

## Cluster and benchmark safeguards

A cluster contract binds a caller-declared cluster definition, dataset-manifest digest, source set, minimum effective cluster count, and all selection-diagnostic parameters. `build_cluster_matrix_v2(...)` accepts only exact family members, rejects mixed definitions/datasets and non-rectangular candidate-by-cluster matrices, and aggregates raw subevents only within a cluster. Adding duplicate subevents cannot increase `effective_cluster_count`.

The inference artifact calculates DSR-style, CSCV/PBO (where the required dimensionality exists), and Reality-Check-style diagnostics from that **cluster-level** matrix. Insufficient declared cluster count stays `inference_eligible: false`.

A required benchmark must supply exactly one aligned observation for every selected-candidate completed cluster. Its candidate return must equal the verified cluster-matrix value. Each aligned record binds common accounting, cost, and funding identities. Positive standalone return that is fully benchmark-explained cannot pass a policy requiring positive incremental return. A caller may record `NOT_APPLICABLE_WITH_FROZEN_RATIONALE`, but v2 graduation keeps that assessment ineligible rather than silently treating it as a pass.

> **Activation blocker:** External data provenance/completeness, cost/funding truth, and calibrated execution are not verified by these local records. The caller must freeze those policies and provide the future authorized evidence; this module never invents defaults or claims calibration.

## Offline executable CLI

Development surface (available now without package/dispatcher edits):

```bash
python -m orderflow_edge_lab.discovery_governance_v2 --help
python -m orderflow_edge_lab.discovery_governance_v2 append-ledger ledger-v2.json event.json --output ledger-v2-0001.json
python -m orderflow_edge_lab.discovery_governance_v2 close-family ledger-v2-0001.json candidate.json \
  --selection-rule-sha256 <64-hex> --closure-policy-sha256 <64-hex> --output closure-v2.json
python -m orderflow_edge_lab.discovery_governance_v2 economics economics-input.json --require-clear
python -m orderflow_edge_lab.discovery_governance_v2 graduate graduation-input.json --require-eligible
python -m orderflow_edge_lab.discovery_governance_v2 freeze freeze-input.json --output candidate-freeze-v2.json
python -m orderflow_edge_lab.discovery_governance_v2 validate graduation graduation-v2.json
```

All input objects are ordinary JSON. `append-ledger`, `close-family`, and `freeze` require new `--output` paths and fail rather than overwrite a file. `economics` and `graduate` print the artifact and optionally write it exclusively. Error exit is **2**; the explicit selection failure exit for `--require-clear` / `--require-eligible` is **3**.

## Required integration after stage merge

Stage 10/integration owns global package and dispatcher registration. Add a thin CLI module/entry point for `orderflow-discovery-governance-v2` that delegates to `orderflow_edge_lab.discovery_governance_v2:main`, and add an integration test for `orderflow discovery-governance-v2 --help`. Do not wire this command into legacy `candidate_freeze` or mutate legacy results. Future sprint producers should emit the declared event, evaluation binding, cluster observations, and benchmark-aligned observations rather than bypassing v2 artifacts.
