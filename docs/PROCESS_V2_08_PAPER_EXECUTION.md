# Paper execution and recovery v2

**Scope:** additive, offline, paper-only successors for the crypto blend replay and the local approval-bound manual paper engine. These modules **do not change** `paper_account.py`, `execution.py`, `approval.py`, legacy manual state/journal files, frozen research/configuration identities, active watches, or any promotion/research verdict.

> Neither local file hashes nor a passed v2 check establish provider completeness, independently durable storage, engine calibration, profitability, promotion authorization, or live order capability. Every v2 artifact retains the false `non_authority_claims` set from `contracts_v2`.

There are still **no** broker/exchange order methods, collector invocations, credentials, schedules, services, or live trading paths.

## Executable surfaces

The package dispatcher discovers the new module proxies when source is installed:

| Dispatcher command | Development/module command | Purpose |
|---|---|---|
| `orderflow-paper-replay-v2` | `python -m orderflow_edge_lab.paper_replay_v2` | Offline coverage gate, immutable replay-bundle build, and read-only verification |
| `orderflow-paper-execution-v2` | `python -m orderflow_edge_lab.paper_execution_v2` | Opt-in manual grid/lot, approval-term, flatten, anchor, and audit controls |

Examples (all input paths are operator-provided local JSON, and none fetches data):

```bash
python -m orderflow_edge_lab.paper_replay_v2 coverage --inputs frozen-inputs-v2.json
python -m orderflow_edge_lab.paper_replay_v2 build-bundle \
  --inputs frozen-inputs-v2.json --source-set frozen-source-set-v2.json \
  --output artifacts/paper-replay-v2.json
python -m orderflow_edge_lab.paper_replay_v2 verify-bundle --bundle artifacts/paper-replay-v2.json

python -m orderflow_edge_lab.paper_execution_v2 \
  --state runtime/paper-v2-state.json --journal runtime/paper-v2-journal.jsonl \
  --instruments frozen-instruments-v2.json --terms-policy frozen-terms-policy-v2.json init
python -m orderflow_edge_lab.paper_execution_v2 \
  --state runtime/paper-v2-state.json --journal runtime/paper-v2-journal.jsonl \
  --instruments frozen-instruments-v2.json --terms-policy frozen-terms-policy-v2.json audit \
  --trusted-anchor /operator-retained-location/paper-anchor.json --strict-unattended
```

The proxies are dispatcher-reachable because `cli/main.py` discovers new `cli/*.py` modules. **Packaging console-script entries are intentionally not edited by this stage**; integration should add the two named scripts after cherry-picking and test their installed help paths.

## Crypto replay v2

### Required frozen input shape

`paper_replay_v2` accepts a single normalized JSON input object with exactly:

- `config`: `initial_equity`, `start_utc`, `as_of_utc`, `slippage`, `min_fee`, and explicit `collection_failures`;
- `targets`: `{timestamp, symbol, weight}` records, where timestamp is the caller-declared rebalance/08:00 mark time;
- `marks`: `{timestamp, symbol, price}` records;
- `funding`: `{timestamp, symbol, rate}` settlement records;
- `funding_expectations`: caller-declared `{timestamp, symbol}` settlement schedule records;
- `specs`: per-symbol `{contract_size, min_contracts, taker_fee_rate}`;
- `coverage_policy_sha256`: a caller-frozen policy hash. The successor does **not** invent a venue schedule or coverage threshold.

A canonical v2 source set is also mandatory for `build_replay_bundle_v2`. It should bind the raw and normalized artifacts, replay configuration, and any relevant stage-05 funding/mark coverage artifacts. The source set proves only local identity/membership.

### Coverage and accounting behavior

For a nonzero target/held interval, v2 requires a finite, unique mark at each caller-declared timestamp and a caller-declared funding schedule for every held interval. For every expected settlement, it requires a finite, unique funding observation. It records all expected observation IDs and missing reasons through `contracts_v2`.

- An explicit funding `rate: 0.0` is **observed**, accepted, and charged as zero.
- Omitted settlement, empty schedule, missing current/prior mark, duplicate record, nonfinite mark/funding, invalid spec, or a collection failure fails closed.
- Missing/invalid market/funding coverage produces `DATA_GAP`; collection failures produce `INCOMPLETE_INPUT`.
- Both states have `summary: null`; no ordinary performance or `forward.paper` report is emitted.

A `COMPLETE` bundle embeds the immutable normalized input snapshot, canonical input hashes, source set, coverage result, generic manifest, and full self-financing lifecycle (mark P&L, every funding settlement, rebalances/fills, fee/notional, curve, positions, and totals). `validate_replay_bundle_v2` deterministically rebuilds the entire bundle and rejects any semantic mutation to inputs, policy, config, ledger, summary, source membership, or hashes. `write_replay_bundle_v2` uses exclusive create (`xb`) and never replaces a previous bundle.

This is a prospective `paper-replay-v2` artifact; do not use it to restate, relabel, rename, or backfill `paper-account-blend-v1` history.

## Manual approval-bound engine v2

`ApprovalBoundPaperEngineV2` subclasses/wraps `ApprovalBoundPaperEngine`; it is not a rewrite of legacy journaling. It uses a companion exclusive-created `*.paper_execution_v2.json` sidecar containing exact caller-supplied metadata and the approval-terms policy. Any later metadata/policy byte change blocks reopen.

### Caller-declared policy templates

No terms tolerance is silently enabled. A caller must pass this full policy object, frozen before prospective use:

```json
{
  "schema": "orderflow_edge_lab.approval_market_terms_policy.v2",
  "max_bid_move_ticks": 0,
  "max_ask_move_ticks": 0,
  "max_fill_move_ticks": 0
}
```

Zero is the conservative suggested initial template, not a default. A future nonzero tolerance is a **new policy** that must be independently reviewed/frozen before later evidence is viewed. The engine hashes this exact object into every v2 submission/approval binding.

Each instrument requires caller-declared, versioned metadata:

```json
{
  "schema": "orderflow_edge_lab.paper_instrument_metadata.v2",
  "symbol": "MNQ",
  "tick_size": "0.25",
  "tick_value": "0.50",
  "max_contracts": 20,
  "contract_increment": 2,
  "min_contracts": 2
}
```

Decimals are strings to make the grid exact. The engine checks bid, ask, entry, stop, target, modeled entry fill, and modeled exit fill on this grid **before a state mutation**. It rounds permitted sizing down to the declared contract increment and rejects a result below `min_contracts` as `risk_budget_too_small`; it does not guess unknown metadata.

A submitted proposal binds exact terms (quote, modeled fill, valid lot count, risk/reward/cost values, policy hash, metadata hash) into the already approval-bound token. At approval, a material one-tick movement under the zero template yields `APPROVAL_MARKET_TERMS_CHANGED`, journals submitted/current digest linkage, replaces the pending proposal with a fresh token, and opens no position. The old token cannot approve the refreshed proposal.

### State migration boundary

A pre-v2 manual state/journal pair is rejected by default. Migration requires all of the following:

1. explicit `migrate_reconciled_flat=True` (or CLI `init --migrate-reconciled-flat`);
2. no open position and no pending proposal;
3. complete successor metadata matching the persisted legacy engine registry/configuration; and
4. successful legacy recovery/config validation.

This does not rewrite existing journal records. Nonflat legacy positions/pending proposals remain read-only under their original engine/configuration and require operator reconciliation before a fresh successor run.

## Flatten lifecycle and recovery

`engage_kill_switch(..., flatten=True)` is a staged lifecycle, not a claim that every position is flat:

1. It validates snapshots for **every** starting position (presence, symbol, freshness, exact tick grid, and modeled exit fill) before closing anything.
2. On a preflight error it journals `kill_switch_flatten_preflight_failed`, keeps every position, clears pending proposals, and engages the entry kill switch.
3. On success it journals `kill_switch_flatten_requested` with the exact starting IDs, closes positions deterministically, then journals `kill_switch_flatten_completed` with expected/closed/remaining IDs.
4. If a durable write/restart failure happens after the request, the journal has no completion marker. `audit_paper_execution_v2` reports `flatten_incomplete`, recovery state, and the exact expected/closed/remaining IDs; it never marks it complete or mutates history.

`engage_kill_switch(flatten=False)` retains the legacy documented behavior: entry is blocked and existing positions remain visible for explicit close.

## Reconciliation anchors and incident procedure

`build_reconciliation_anchor_v2` reads an internally consistent local state/journal pair and emits a canonical anchor of exact state/journal byte identities, journal head, revision, caller-declared runtime identity, generation time, and optional prior-anchor hash. `write_reconciliation_anchor_v2` is exclusive-create only.

> A locally written anchor is **not rollback-proof** and never proves immutable/durable/external storage. `external_storage_verified` remains false.

For operational use, an operator must independently retain the output artifact outside the state/journal location and later pass that independently retained artifact as `trusted_anchor_path`. The code can compare it; it cannot verify a storage provider, retention duration, immutable controls, clock discipline, or external independence.

`verify_reconciliation_anchor_v2` is read-only:

- trusted anchor head/revision later than the restored current journal/state: `ROLLBACK_DETECTED`;
- trusted anchor still in journal but state is behind a durable journal: `RECOVERY_REQUIRED` (journal-ahead recovery remains supported);
- invalid/mutated/missing anchor: blocks; and
- no trusted anchor in `strict_unattended=True`: `TRUSTED_ANCHOR_UNKNOWN`, blocking unattended readiness.

### Incident response

1. **Stop manual paper operations. Do not retry, truncate, regenerate, or overwrite the journal/state/anchor.**
2. Preserve byte-for-byte copies of state, journal, v2 sidecar, all relevant anchors, and the audit output in a separately controlled incident location.
3. Run the read-only v2 audit against the operator-retained trusted anchor.
4. If `ROLLBACK_DETECTED`, compare the anchor chain and external retained records; manually reconcile the discrepancy. If `RECOVERY_REQUIRED`, reopen only through the normal hash-chain recovery path, then re-audit before issuing any new command.
5. Resolve `flatten_incomplete` by operator review of the reported expected/closed/remaining IDs; do not call it complete merely because a kill switch was engaged.
6. Create a new prospective anchor only after reconciliation. Never rewrite historic journal entries to make an old pair appear anchored.

## Finding coverage

| Finding | Runtime disposition | Main evidence |
|---|---|---|
| F1 missing crypto funding/marks | implemented | coverage gate; `DATA_GAP`; explicit observed-zero model; no summary on gap |
| F2 reproducible crypto lifecycle | implemented | frozen input snapshot/hashes/source set, self-financing lifecycle, exclusive writer, deterministic read-only verifier |
| F3 exact tick/lot manual checks | implemented | decimal-string metadata; pre-mutation grid checks; conservative valid-increment sizing; explicit flat migration |
| F4 term movement requires approval refresh | implemented | terms digest/policy bound to token; journaled fresh proposal/token on material movement |
| F5 rollback anchor | implemented in code; activation externally blocked | operator-supplied trusted anchor comparator, strict-unattended blocker; durable independent retention/rehearsal remains external |
| F6 flatten lifecycle | implemented | all-snapshot preflight, requested/preflight-failed/completed journal states, incomplete audit after durable failure |

## Required integration work

- Add installed package scripts for `orderflow-paper-replay-v2` and `orderflow-paper-execution-v2` in the integrator-owned packaging/registry step, then verify `--help` through both installed and unified dispatcher surfaces.
- Wire stage-05 qualified funding/mark source sets and the caller-frozen expected-settlement/coverage policy into any production prospective v2 invocation. Do not use a locally fabricated schedule.
- Obtain operator-approved, independently retained durable anchor/bundle storage and rehearse restore/anchor comparison. Until then, activation remains blocked and local hashes are only local-byte checks.
- Obtain/review authoritative frozen instrument metadata before a real manual v2 run. This implementation intentionally does not claim venue/contract provenance or execution calibration.
