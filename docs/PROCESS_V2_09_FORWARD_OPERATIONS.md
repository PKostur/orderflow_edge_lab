# Forward Operations v2 — Inventory, Availability, and Provenance

## Purpose and authority boundary

`forward_operations_v2` is an **opt-in operational overlay** for existing prospective watches. It derives an inventory from frozen clock IDs, records evidence-availability facts, and reports stopped/stale child-report conditions. It does **not**:

- modify frozen strategies, configurations, starts, decision dates, expected returns, symbol weights, report bytes, or review gates;
- collect market data, call GitHub, create schedules/services, dispatch workflows, backfill an interval, calculate PnL, count prospective evidence, make a verdict, promote a strategy, or submit an order;
- verify provider completeness, external storage durability, engine calibration, profitability, or promotion authority.

All v2 objects use local-byte/source identities from `contracts_v2`; their `non_authority_claims` remain false. A locally generated JSON file or SHA-256 is **not** an immutable external copy.

## Surfaces

| Surface | Purpose | Safe behavior |
|---|---|---|
| `build_retention_inventory_v2(...)` | Derives one inventory row for every nonterminal frozen clock watch. | Requires REPORT, SOURCE_CHECKPOINT, and HASH_MANIFEST declarations; returns external retention as blocked/unverified. |
| `audit_retention_producer_contract_v2(...)` | Checks local workflow upload declarations against an emitted inventory. | Fails declared-but-unuploaded checkpoints and omitted/short retention declarations; does not inspect Actions. |
| `build_universe_availability_ledger_v2(...)` | Appends a hash-bound per-symbol frozen-universe overlay. | Any missing price/funding source, warm-up, or completed boundary becomes `DATA_INCOMPLETE`; no reweighting/recalculation. |
| `build_source_checkpoint_v2(...)` | Binds report/config/code/source identities to closed-bar grid observations. | Excludes still-open bars, records `DATA_GAP` / `REVISED_SOURCE`, preserves predecessor linkage. |
| `locate_checkpoint_by_report_sha256_v2(...)` | Finds retained checkpoint references for formal review. | Lookup only; never replaces an original source/report. |
| `build_forward_operations_registry_v2(...)` | Validates exactly one no-PnL monitoring row per nonterminal watch. | Pre-start rows have no freshness SLO. |
| `assess_forward_operations_heartbeat_v2(...)` | Separates missing child, stale artifact, stale `as_of`, and nonadvancing boundary. | An active child suppresses duplicate dispatch; this module has no dispatch capability. |
| `orderflow_edge_lab.ops_digest.build_ops_digest(...)` | Adds inventory acquisition and ledger heartbeat evidence to the existing reporting-only digest. | A failed inventory acquisition, failed coverage, malformed ledger, or stale declared heartbeat sets `operational_check_conclusion=FAIL`; warning-only attention remains `PASS`. |

## Caller-declared templates

- [`config/forward_retention_overlay_v2.json`](../config/forward_retention_overlay_v2.json) maps all **15 nonterminal** clock IDs to exact current report paths plus required future checkpoint/hash-manifest artifacts. It requests `400` upload-retention days as a template value only. It **does not claim** that GitHub/account policy accepts it.
- [`config/forward_operations_registry_template_v2.json`](../config/forward_operations_registry_template_v2.json) maps the same IDs to producer/ref/dispatcher/artifact/parser/cadence/grace/boundary fields. Its parser value intentionally states `forward-report-envelope-v2-required`, because legacy reports do not yet emit this envelope.

The templates are deliberately inert caller-declared operational policy inputs, not silent defaults. Changing their cadence, grace, retention margin, retention duration, immutable-copy location, revision-use decision, or escalation policy requires an approved successor policy before activation.

## Safe local CLI

The development path is executable without package-registry changes:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /home/ubuntu/orderflow-implementation/venv/bin/python \
  -m orderflow_edge_lab.cli.forward_operations_v2 --help

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /home/ubuntu/orderflow-implementation/venv/bin/python \
  -m orderflow_edge_lab.cli.forward_operations_v2 retention-inventory \
  --clock config/prospective_review_clock_v1.json \
  --overlay config/forward_retention_overlay_v2.json \
  --generated-at 2026-10-06T12:00:00Z \
  --output /new/path/retention_inventory_v2.json
```

Other local-only subcommands are `availability-ledger`, `source-checkpoint`, `registry`, `heartbeat`, and `producer-contract`. `--output` uses exclusive creation, so a pre-existing result cannot be overwritten. `heartbeat` and `producer-contract` return nonzero for their respective operational failure; diagnostic construction itself does not alter any watch.

**Integration requirement:** Stage 10/integration must add an `orderflow-forward-operations-v2` console-script entry in the package dispatcher after cherry-picking this stage. Until then, the documented `python -m` path is the tested executable interface.

## Existing digest workflow, without new scheduling

Only the existing [`wait-window-ops-digest-v1.yml`](../.github/workflows/wait-window-ops-digest-v1.yml) was adjusted. Its existing schedule was not created or changed.

1. It records `inventory_acquisition.json` as `ACQUIRED` or `FAILED`; a failed `gh api` call is no longer converted into a deceptive successful empty inventory.
2. It retains partial/error diagnostics, retrieves the newest unexpired discovery-ledger artifact when inventory acquisition succeeds, and passes artifact/retrieval facts to the digest.
3. It passes caller-declared ledger heartbeat cadence/grace (currently 1h + 0.5h in that existing workflow), uploads diagnostic artifacts, then has an `if: always()` health gate fail only after upload for confirmed `error` conditions.
4. Warnings remain attention-only. This CI/manual check makes no research verdict and starts no collector/dispatcher.

The workflow requires the already-declared GitHub `actions: read` permission and an available `gh` token. These cannot be proved by offline tests.

## Activation blockers

| Blocker | Why the code does not fake completion | Required activation evidence/action |
|---|---|---|
| Durable immutable retention | Local files and Actions declarations do not prove durable, immutable storage or retrievability through review plus margin. | Operator-approved external immutable-copy policy/location, provider/account retention confirmation, copy identities, and retrieval/rehearsal evidence. |
| Producer adoption | Most current forward workflows do not upload the newly named v2 source checkpoint/hash manifest, and several have no explicit retention setting. | Each owner must emit the sidecars append-only, set/verify retention consistent with the declared policy, and pass `producer-contract`. |
| Account/platform retention ceiling | `400` is a template request, not verified against any account/platform maximum. | Confirmed platform policy or approved immutable external copy; retain the blocked result if unavailable. |
| Report envelope/parser fields | Existing reports do not uniformly emit v2 `as_of` / completed-boundary / source coverage envelope facts. | Producer-side successor envelope integration, with one fixture per active watch. |
| Ledger heartbeat source | Digest can check a retrieved manifest timestamp but cannot establish that upstream collection ran successfully from local code alone. | Upstream discovery owner must emit/retrieve the latest hash-bound heartbeat artifact and CI must retain it. |
| Revision-use policy | This stage records a revision; it does not decide whether revised historical provider data may be used. | Freeze a prospective successor policy before any later use in formal review. |
| GitHub Actions/API actuality | Offline workflow/text tests cannot verify inventory access, artifacts, retention, or scheduler execution. | Authorized CI/manual run with `actions: read`, retained diagnostics, and human review. |

## Finding disposition and evidence

| Finding | Disposition | Executable evidence | Remaining activation boundary |
|---|---|---|---|
| F1 retention coverage | **partial** | All 15 nonterminal IDs are derived/mapped; missing mappings fail; producer-contract exposes missing checkpoint uploads/retention. | External immutable copy/rehearsal and each producer’s sidecar/retention adoption. |
| F2 frozen-universe availability | **implemented** | Per-symbol append-only availability ledger; partial source/warmup state is `DATA_INCOMPLETE`; recovery chains without mutation. | Forward producer/data-adapter must emit source identity inputs to activate on existing runs. |
| F3 unmasked inventory health | **implemented** | Digest explicitly records acquisition `FAILED`; existing digest workflow uploads diagnostics then fails confirmed operational errors. | Actual Actions permissions/API run remains external. |
| F4 watch child heartbeat | **partial** | Registry requires exactly one active row; heartbeat differentiates missing/stale/nonadvance and never dispatches. | Existing reports must adopt v2 operational envelopes; live Actions run required. |
| F5 stale valid ledger | **implemented** | Hash-bound manifest heartbeat validates aware timestamp and cadence+grace, independent of batch count. | Upstream/latest artifact availability and caller-approved cadence/grace for deployment. |
| F6 source checkpoint/revision chain | **partial** | Append-only checkpoint excludes open bars, records gaps/revisions, preserves predecessor, and supports report-hash lookup. | Data adapters/producers and durable store must provide/retain raw identities; revision-use policy remains external. |

Focused offline evidence: `tests/test_v2_09_forward_operations.py` exercises all six cases, including failed inventory, stale/malformed timestamps, missing symbols, missing closed bars, source revision, pre-start watch, active-run dispatch suppression, exact clock mapping, exclusive CLI output, and current producer contract failures.
