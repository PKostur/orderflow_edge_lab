# Process v2 — ingestion acquisition, readiness, and completion

## Scope and safety boundary

`orderflow_edge_lab.ingestion_v2` is an **additive, opt-in successor** to the legacy MEXC recorder and historical readers. It does not rewrite a legacy raw file, frozen watch, manifest, strategy result, or historical report. It has **no network client invocation, service, scheduler, credential, purchase, or order capability**. Its CLI only reads caller-provided local JSON/raw files and creates a new JSON result path.

A passing local source identity proves only that bytes currently match a SHA-256 and size. Every v2 object keeps the shared `non_authority_claims` false: this module does **not** verify provider completeness, provider entitlement/authenticity, external durable storage, independent-engine calibration, profitable edge, promotion authority, or live order transmission.

## Executable entry points

The CLI module is discoverable by the existing package dispatcher without a registry edit:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python -m orderflow_edge_lab.cli.ingestion_v2 --help

# Existing dispatcher discovery resolves this as orderflow-ingestion-v2:
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m orderflow_edge_lab.cli.main --list
```

All commands require `--input` and a **new** `--output`; an existing output is refused rather than overwritten.

| Command | Input contents | Exit 0 | Exit 1 | Exit 2 |
|---|---|---|---|---|
| `terminal` | `build_session_terminal_v2` keyword object | completion-bound `COMPLETE` terminal | terminal written as `INCOMPLETE` | malformed/contradictory evidence or output collision |
| `historical` | `build_historical_acquisition_manifest_v2` keyword object | full expected grid, all pages successful, no rejected/invalid rows | valid incomplete or diagnostics-only manifest | malformed provenance/policy/path |
| `readiness` | `build_provider_readiness_manifest_v2` keyword object | strict complete panel | explicit degraded diagnostics | malformed/unsupported capability or policy |
| `capability` | `capability_path`, `source_id` | hash-bound nonsecret declaration written | not applicable | malformed artifact/path |
| `funding-admissibility` | `acquisition_manifest`, `required_settlement_ids` | complete required settlement coverage | `INADMISSIBLE_DATA_GAP` | malformed input |
| `capture-pair-input` | `terminal` | validated terminal facts emitted for stage 02 | not applicable | invalid terminal |
| `simulate` | bounded offline `capacity`, `required_symbols`, `frames` | all simulated queued frames processed | overflow is explicitly incomplete | malformed simulation |

The CLI writes JSON before returning exit 1 so that partial/ineligible evidence remains auditable. Exit 2 does not manufacture an output artifact.

## Caller-supplied policies (no hidden defaults)

Every policy must contain `policy_id`, its exact canonical `policy_sha256`, and the applicable fields. The SHA-256 is the canonical JSON hash of the object **excluding** `policy_sha256`.

1. **Readiness/capture policy:** exactly `max_symbol_idle_seconds`, `required_streams` (`snapshot`, `depth`, `trade`), `require_subscription_ack: true`, and `allow_degraded_diagnostics`. It governs only a new prospective capture. It cannot be inferred from legacy code or retroactively attached to a raw file.
2. **Retry policy:** exactly `max_attempts`, `base_backoff_seconds`, and `retry_http_statuses`. Only caller-authorized `429` and `5xx` statuses may be transient; `401`, `403`, payload/schema, and configuration failures never retry.
3. **Historical acquisition policy:** exactly `allow_diagnostic_only`. It has no silently selected listing-gap, cadence, or research eligibility exception.

A caller must retain the independently frozen policy artifact and its approval context. This module checks the supplied hash relation; it does not claim the policy is approved.

## Completion, liveness, and receipt processing

`build_session_terminal_v2` produces a generic hash-bound manifest with `manifest_type: ingestion.session_terminal.v3`. It is `COMPLETE` only when all of the following are true:

- strict provider readiness is complete with the exact same logical/native symbol mappings;
- every symbol has acknowledgement, snapshot, depth, trade, and liveness coverage;
- receipt is within the caller’s monotonic idle bound and there is no `feed_silence` event;
- terminal UTC reaches the requested `[start, end)` end;
- `terminal_cause` is `REQUESTED_INTERVAL_COMPLETE`;
- overflow count and open recovery-barrier count are zero.

All other states stay `INCOMPLETE`; their completion status is `degraded` or (for known fatal cause) `failed`. A schema-v1/v2 capture can be labelled using `legacy_terminal_status_v2`; it remains `unknown_legacy`, not complete.

`BoundedOrderedCaptureV2` is the raw-first receiver/processor interface for a caller-owned transport adapter:

- `receive()` timestamps UTC and monotonic receipt and passes the raw frame to a caller-provided sink before queueing it;
- `process_next()` preserves receipt order and records nonnegative processing delay;
- overflow records both the raw receipt and `queue_overflow`, and cannot qualify a terminal as complete;
- recovery barriers, bounded queue-age sample percentiles, and bounded REST-duration records are telemetry facts;
- exchange latency is `unavailable` unless a caller supplies an explicitly labelled comparable-clock basis. It is never presented as calibrated latency.

The included simulation command exercises this path **offline only**; it is not a collector.

## Historical/funding provenance and coverage

`build_historical_acquisition_manifest_v2` requires a locally readable `raw_path` for every page. It binds the raw page identities to the source set and records noncredential requested/resolved URLs, cursor, retry outcome, parser version, HTTP outcome, retrieval UTC/monotonic time, page status, accepted rows, rejected raw rows, and validation issues.

It generates the expected `[start, end)` grid from the caller-declared cadence. Missing, duplicate, off-grid, unconfirmed, failed, early-exhausted, or max-pages evidence cannot produce `COMPLETE`. `diagnostic_only` is available only when the caller policy explicitly permits it and is still non-eligible.

For `FUNDING_SETTLEMENT`, exact `0.0` is represented as an observed value, never an implicit missing cash flow. `funding_economics_admissibility_v2` requires a caller-provided nonempty required-settlement schedule and rejects incomplete manifests or missing settlement IDs before funding-inclusive economics. Price-only diagnostics are intentionally outside this API and cannot use the admissible result as a funding-performance claim.

## Provider capability and readiness

`build_provider_capability_contract_v2` hashes a caller-provided **nonsecret** JSON artifact with provider, route, event types, one-to-one mappings, optional permitted historical interval, delayed status, export time zone, and redistribution restriction. It rejects credential-like URL query values and embedded URL credentials. It does not infer rights from a successful probe.

`validate_capability_request_v2` fails before normalization if an event type, instrument mapping, or requested historical range lies outside that declaration. `build_provider_readiness_manifest_v2` then requires acknowledgement, snapshot, depth, and trade observation for every mapping. `DEGRADED_DIAGNOSTIC` is an explicit non-complete mode, never a partial panel pass.

## Capture-pair integration edge (stage 02)

Stage 02 should consume `capture_pair_input_v2(session_terminal)` only after calling `validate_session_terminal_v2`. The emitted object contains:

- `session_terminal_manifest_sha256`;
- the exact canonical source set;
- completion and coverage status; and
- terminal cause with all non-authority claims false.

Stage 02 must bind its raw/features identities and verify source-set equality itself. This stage does not build or validate a capture-pair manifest and does not modify `data_integrity_v2.py`.

## Activation blockers

The code is complete as a local/offline successor implementation. Activation of a future prospective acquisition still requires all applicable external action/evidence:

1. an operator-approved, separately frozen retry/readiness/acquisition policy before collection;
2. provider-supplied nonsecret capability/entitlement facts for each provider/panel and future preflight observations;
3. a durable external retention configuration plus immutable-copy/retrieval rehearsal evidence; local page identities are insufficient;
4. a caller-declared venue, contract, settlement schedule, and complete observed settlement sources before funding-inclusive economics;
5. independent execution/engine calibration if a later owner needs calibrated costs or latency;
6. separate future authorization for any live collection, schedule, service, or trading capability. None is enabled here.
