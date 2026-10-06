# Data integrity and replay v2 process

## Scope and preservation boundary

This is an **additive, opt-in** successor implemented in:

- `orderflow_edge_lab.data_integrity_v2`
- `orderflow_edge_lab.data_lineage_v2`

It does **not** modify legacy capture/replay behavior, existing raw files, frozen v1 manifests, capture-quality v1 diagnostic semantics, state reports, research verdicts, scheduling, collection, credentials, or trading behavior. Existing evidence remains legacy/unverified for this successor unless a new v2 completion marker and local verification exist.

## Capture-pair completion

`CapturePairWriterV2` is the prospective local writer contract.

1. It creates distinct raw and feature `*.partial` diagnostic files.
2. It writes and fsyncs exactly one terminal `session_summary` for each stream.
3. It renames each partial file to its final name.
4. **Only then** it writes and fsyncs `<capture_id>_capture_pair_v2.json`.

> Two individual renames are not an atomic pair. The final pair JSON marker is the authoritative completion record. Strict consumers reject partial files, absent markers, mismatched files, duplicate summaries, summaries that are not final, cross-capture pairs, and any byte/terminal-record mismatch.

An exception or unfinalized context preserves only fsynced `*.partial` diagnostic bytes and emits neither a final data filename nor a pair marker. A kill between the two renames can leave a final-looking orphan, but it has no marker and is therefore ineligible.

`build_capture_pair_manifest_v2(...)` and `verify_capture_pair_v2(...)` bind:

- caller-declared `capture_id` and explicit UTC interval;
- raw and feature basenames, local byte count and SHA-256;
- session schemas and exact symbol list;
- record count plus canonical terminal-summary hash/index/end time;
- canonical raw/features source set, generic complete coverage, false authority claims, and self-hash.

A verification success means only **current local bytes and terminal structure matched**. It never establishes provider authenticity/completeness or durable external retention.

## Predeclared eligibility

`build_capture_eligibility_policy_v2(...)` creates a caller-declared structural policy. The caller must freeze it before the capture start. It has an exact self-hash and requires declaration of:

- accepted raw and feature session schema versions;
- expected symbols;
- allowed raw and feature record types;
- whether feature receipt timestamps must be monotonic;
- whether a quality report is required, and its allowed analysis/status values.

The policy shape intentionally has **no PnL field, quality threshold default, strategy parameter, or retrospective selection rule**. `replay_eligibility_v2(...)` first verifies the complete pair; only then it emits `ELIGIBLE` or an explicit retained `INELIGIBLE` result with deterministic structural reasons. Missing, partial, malformed, or byte-mismatched pairs raise before an eligibility result can be published.

A v2 companion state-report binding is available through `build_state_report_integrity_binding_v2(...)`. It binds a newly written state report to raw, feature, quality (when supplied), pair marker, eligibility-policy, and eligibility hashes. It does not rewrite v1 state reports.

## Replay selection and availability

`build_replay_selection_policy_v2(...)` accepts only one of these deterministic scopes:

- `ALL_SCHEDULED_BATCHES`; or
- a sorted predeclared `CAPTURE_IDS` list.

It contains no outcome/PnL selection field. `build_replay_availability_record_v2(...)` produces one record per batch, including those without retained inputs. A record is `REPLAYABLE_LOCAL_BYTES` only if the selected raw, feature, and final marker all exist and verify together now. Otherwise it is `NONREPLAYABLE` and records explicit causes such as unavailable raw/features or a missing/unverifiable pair marker.

The record retains a caller-supplied retention deadline and optional artifact name/identifier but keeps `external_storage_verified: false`. A local file, artifact identifier, or configured deadline is not evidence of external durable storage.

## Strict and inspection CLI paths

These module commands are offline and have no network, collector, scheduler, service, secret, purchase, broker, exchange, or live-order path:

```bash
# Test a final marker and its exact local raw/features bytes.
python -m orderflow_edge_lab.data_integrity_v2 verify-pair \
  --manifest CAPTURE_capture_pair_v2.json --raw CAPTURE_raw_v2.jsonl --features CAPTURE_features_v2.jsonl

# Publish a retained eligible/ineligible decision. A missing/mismatched pair fails.
python -m orderflow_edge_lab.data_integrity_v2 eligibility \
  --manifest CAPTURE_capture_pair_v2.json --raw CAPTURE_raw_v2.jsonl --features CAPTURE_features_v2.jsonl \
  --policy frozen_capture_eligibility_policy_v2.json --output CAPTURE_eligibility_v2.json

# Strictly verify marker + local bytes + policy eligibility BEFORE opening OUTPUT.
python -m orderflow_edge_lab.data_integrity_v2 strict-replay \
  --manifest CAPTURE_capture_pair_v2.json --raw CAPTURE_raw_v2.jsonl --features CAPTURE_features_v2.jsonl \
  --policy frozen_capture_eligibility_policy_v2.json --output CAPTURE_strict_replay_v2.jsonl

# Explicitly permitted read-only legacy inspection: output is legacy_unverified and aggregation-ineligible.
python -m orderflow_edge_lab.data_integrity_v2 legacy-inspect \
  --raw OLD_raw.jsonl --output OLD_legacy_inspection_v2.jsonl

# Emit an availability/nonreplayability row for every batch.
python -m orderflow_edge_lab.data_integrity_v2 availability \
  --capture-id CAPTURE --selection-policy frozen_replay_selection_policy_v2.json \
  --retention-deadline-utc 2026-10-15T00:00:00Z --output CAPTURE_availability_v2.json
```

`strict-replay` runs the existing deterministic replay engine only into a non-final work file after verification; it publishes an atomic v2 output whose first record carries `verification_status: "verified"`, exact raw/feature identities, pair-marker hash, eligibility hash, replay parameters, source set, and false authority claims. There is no silent fallback.

`legacy-inspect` is intentionally separate and labels its output `verification_status: "legacy_unverified"` and `prospective_aggregation_eligible: false`. `require_prospective_aggregation_eligible_v2(...)` refuses this status and every v2 eligibility decision that is not explicitly eligible.

## Exact CSV lineage successor

`profile_csv_export_v2(...)` uses `data.parse_timestamp_ns`, which is Decimal-based, and stores exact `first_ns`, `last_ns`, `minimum_ns`, and `maximum_ns`. Ordering/regression comparisons use those integer UTC nanoseconds rather than floats. Human-readable ISO fields are projections only.

`verify_csv_export_v2(...)` accepts v1 manifests through the untouched v1 verifier. For v2 manifests it validates the manifest self-hash and recomputes byte identity, schema, row chain, and exact timestamp diagnostics. It does not rewrite old lineage manifests.

## Frozen retention operational correction

The only edit to `.github/workflows/high-cadence-evidence-capture-v1.yml` changes the selected raw/features replay artifact from `retention-days: 7` to **`retention-days: 14`**. This aligns the existing artifact retention with the frozen `raw_artifact_retention_days` and `features_artifact_retention_days` declaration in `config/high_cadence_evidence_capture_v1.json`.

It does **not** alter cadence, duration, symbols, selection timing, evidence counts, capture method, quality v1 diagnostic policy, strategy parameters, or aggregation semantics. The existing selected-subset retention behavior remains a blocker: callers must freeze a v2 replay-selection policy before using new prospective records as replayable analytic inputs.

## Activation blockers

The code is complete for offline local verification but cannot activate any claim of durable/prospective evidence without all of the following external/operator actions:

1. A separately frozen capture-eligibility policy and replay-selection policy before relevant new capture windows.
2. An operator-approved durable storage/retention design, immutable copy evidence, and retrieval/rehearsal evidence through the required horizon. **Do not treat local files or GitHub artifact configuration as verified durable storage.**
3. Workflow/aggregation owner wiring that emits eligibility and availability records for every future batch and consumes only explicit `ELIGIBLE`/locally replayable records. This stage does not modify the frozen v1 aggregation path.
4. Stage 10 package/dispatcher registration for a public console-script name. Module CLIs are currently executable with `python -m` and covered by focused tests; this stage intentionally avoids global packaging edits.
5. Separate provider/authenticity/completeness and independent-engine calibration evidence. All generic authority claims remain false.
