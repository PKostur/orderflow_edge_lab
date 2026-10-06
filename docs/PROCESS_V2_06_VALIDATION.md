# Process v2 — Validation and promotion evidence binding

## Scope and safety boundary

`orderflow_edge_lab.validation_binding_v2` is an **additive, opt-in, offline** successor surface. It does not import, alter, replay, rename, or reclassify legacy holdout audits, forward formal reviews, trial ledgers, registries, robustness reports, frozen configurations, or promotion outcomes.

It can establish only canonical object consistency and **local byte identity** of caller-selected files. Its `non_authority_claims` remain false for durable external storage, provider completeness, independent-engine calibration, profitability, promotion authorization, and live-order support. It has no network, collection, schedule, secret, broker, or trading path.

A successful non-temporal check is emitted as `DIAGNOSTIC_ONLY`, not `COMPLETE`, because the foundation contract correctly requires caller-declared temporal coverage for a generic `COMPLETE` result. A formal cohort uses its caller-frozen expected calendar as actual coverage and becomes `COMPLETE` only when every expected return and scheduled run is present and valid.

## Executable successor surfaces

| Finding | Public surface | Fail-closed behavior |
|---|---|---|
| F1 source-set binding | `verify_validation_source_set_v2(...)` | Requires canonical equality between sealed holdout and report source sets and an exact source-id/path bijection. Missing, extra, mismatched, or altered local bytes set `source_files_reverified=false`; no implicit derivation exception exists. |
| F2 formal cohort | `build_formal_cohort_definition_v2(...)`, `build_forward_report_evidence_v2(...)`, `build_run_ledger_v2(...)`, `build_formal_cohort_v2(...)` | Exact normalized UTC return dates, report schema/producer/root identities, and scheduled run IDs/times/conclusions are checked before any metrics exist. Gaps, normalized duplicates, off-calendar returns, missing/extra runs, identity changes, and immature horizons return `INCOMPLETE` with `scoring_permitted=false`. Observed `0.0` is valid. |
| F3 multiplicity family | `build_family_freeze_v2(...)`, `create_family_ledger_v2(...)`, `append_family_trial_v2(...)`, `validate_family_ledger_v2(...)` | Family commitment and ledger genesis must predate the holdout boundary. Candidate membership, planned order, alpha allocations, candidate freeze/spec identity, evidence root, and append hash chain are enforced. |
| F4 registry hygiene | `build_watch_inventory_v2(...)` | Requires a bijective exact mapping for every `SUCCESSOR` inventory record. Duplicate IDs, unmapped successor watches, extra registry watches, and config/path/artifact/state aliases fail. Existing unmatched records remain visible as `legacy_unregistered`; they are not retrofitted. |
| F5 evaluator identity | `build_evaluation_identity_v2(...)`, `build_evaluation_input_manifest_v2(...)`, `bind_evaluation_identity_v2(...)` | Requires frozen pre-window implementation version, commit/tree, evaluator source allowlist, dependency lock, config source set, runtime, command, and local re-verification. It binds an input-manifest hash to a deterministic evidence-graph root. |
| F6 cluster/power design | `build_cluster_power_design_v2(...)`, `powered_mde_v2(...)`, `qualify_legacy_precision_v2(...)` | Uses caller-frozen cluster construction, alpha/tail, desired power, expected cluster count, variance source/assumption, family digest, missing-cluster policy, and source identity. Powered MDE includes `z_alpha + z_power`. Legacy MDE-style values are only relabeled `post_hoc_precision_half_width_bps`, `DIAGNOSTIC_ONLY`, and `promotion_usable=false`. |

The non-authorizing composition surface, `bind_validation_promotion_v2(...)`, receives the F1/F2/F3/F5 products plus the Stage 04 family/graduation manifests. It verifies their exact graph roots and hashes and returns a non-authorizing evidence binding. It never returns a promotion authorization.

## Offline CLI module path

Until the package command registry is wired by Stage 10/integration, use the development module entry point:

```bash
python -m orderflow_edge_lab.validation_binding_v2 --help
python -m orderflow_edge_lab.validation_binding_v2 verify-source-set \
  --holdout-source-set sealed_sources_v2.json \
  --report-source-set report_sources_v2.json \
  --reverification-paths source_paths_v2.json \
  --policy-sha256 <frozen-policy-sha256> --output validation_source_gate_v2.json

python -m orderflow_edge_lab.validation_binding_v2 formal-cohort \
  --definition formal_cohort_definition_v2.json --report forward_report_evidence_v2.json \
  --run-ledger run_ledger_v2.json --as-of-utc 2027-01-01T00:00:00Z \
  --output formal_cohort_gate_v2.json

python -m orderflow_edge_lab.validation_binding_v2 bind-evaluator \
  --identity evaluation_identity_v2.json --input-manifest input_manifest_v2.json \
  --evaluator-paths evaluator_paths_v2.json --dependency-lock requirements.lock \
  --config-paths config_paths_v2.json --execution-context execution_context_v2.json \
  --output evaluator_binding_v2.json

python -m orderflow_edge_lab.validation_binding_v2 watch-inventory \
  --inventory watch_inventory_v2.json --registry watch_registry_v2.json \
  --source-set registry_sources_v2.json --policy-sha256 <frozen-policy-sha256> \
  --output registry_hygiene_v2.json

python -m orderflow_edge_lab.validation_binding_v2 power-mde \
  --design cluster_power_design_v2.json --output powered_mde_v2.json
```

The commands exit `0` only for a generic `COMPLETE` cohort (or a fully covered future implementation that supplies coverage); they exit `1` for `INCOMPLETE` or `DIAGNOSTIC_ONLY`, and `2` for malformed inputs. This makes an unreviewed output fail a CI/pipeline gate rather than look like a passing review.

## Required activation evidence and integration wiring

1. **Pre-register a new successor watch before its window opens.** Caller must freeze policy hashes, source identities, a formal cohort calendar/run schedule, family membership/order/allocation, evaluator identity, cluster/power design, and stopping/missing-data policies. The module does not choose numbers, alpha, desired power, variance, cluster rule, or tolerance.
2. **Stage 04 must publish canonical generic manifest results** for `build_family_ledger_v2(...)`/family closure and `build_graduation_binding_v2(...)`. Their exact `manifest_sha256` values must be inserted into `family_freeze_v2` as `discovery_family_manifest_sha256` and `graduation_binding_sha256`; `bind_validation_promotion_v2` validates them via `validate_manifest_result`.
3. **Stage 03/05/forward producers must emit v2 source sets and reports** with the exact forward-report evidence shape used above, retain every expected run conclusion, and call `build_formal_cohort_v2` before any legacy/successor metric evaluator. A non-`COMPLETE` cohort must prevent scoring.
4. **Stage 10/integration must register each module CLI subcommand** in the package/dispatcher command registry and add an integration test invoking the registered command—not just `python -m`. The registry should treat exit `1` as an ineligible evidence state, never as a passing promotion result.
5. **The promotion integration must call `bind_validation_promotion_v2`** before any successor assessment, pass the exact candidate ID, and require its `promotion_binding_complete` attribute. This only binds evidence; an independent, user-approved promotion policy remains necessary.
6. **Durable external retention and external build authority remain blockers.** A local file rehash is not durable-storage proof; caller-declared commit/tree context is not proof of an externally immutable checkout. Activation requires separately approved durable storage/retrieval evidence, published/immutable build provenance, future prospective evidence, and independent calibration where applicable.

## Deliberate limitations

- A local family-ledger hash chain detects altered/removal/reorder evidence supplied to the verifier, but it cannot prove exclusive append or durable external anchoring by itself. That requires an approved external immutable store and review procedure.
- The normal-approximation powered MDE reports the caller-provided variance assumption; it does not assert that the variance source is representative, calibrated, or independently verified. A frozen simulation may be integrated later as a separately named successor method.
- Existing v1 robustness metrics and watches remain untouched. This module neither changes their numbers nor upgrades their evidentiary status.
