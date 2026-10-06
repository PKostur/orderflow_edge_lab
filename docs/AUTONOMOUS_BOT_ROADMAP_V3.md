# Autonomous Bot Roadmap v3 — Research, Paper Engineering, and the Closed Live Boundary

## Purpose and non-goal

This roadmap answers how Orderflow Edge Lab can progress from its **current research-only state** toward increasingly capable *non-live* workflows. It does **not** authorize a strategy change, a strategy promotion, an account action, deployment, credentials, a schedule, a transaction payload, or broker/exchange order transmission.

> **Standing invariant:** `actual_live_capability=false` and `live_order_transmission_supported=false`.
>
> A green local engineering check is not a profitable-edge finding, a promotion decision, or a live-trading permission.

The added `bot_readiness_v3` reporter is an offline, deterministic JSON assessor. It hashes and self-validates caller-declared provenance objects, fails closed on unknown/missing/stale evidence, and keeps every authority claim false. It does not contact a venue or storage service, run a daemon, place an order, or decide a frozen study.

Unattended **read-only** feeds, analysis, reporting, and services over recorded or public data are not categorically forbidden by this roadmap; they are simply not implemented or deployed in this repository now. This is distinct from a persistent order-generating bot, including one that automatically generates paper-execution actions: that remains outside the boundary. Actual transaction-automation code remains prohibited by the finance-execution safety boundary, and all actual-live flags remain false.

## Current repository position

The repository is **not ready for live trading**, and it has no promoted strategy:

```text
profitable_edge_established       = false
verified_out_of_sample_evidence   = false
live_order_transmission_supported = false
```

### Repository-specific blockers that remain real

| Blocker | Current evidence | Implication |
|---|---|---|
| No established edge | `STATUS.md` explicitly holds both edge and verified-OOS claims false. | Paper-engineering completeness cannot be described as alpha or promotion. |
| DON8 / W3 are frozen prospective work | DON8 is governed by its frozen workflow; W3 has its own frozen data-volume and review procedure. | This roadmap and v3 reporter issue **no verdict** and cannot issue an early verdict. |
| W1/W2 terminal outcome | Formal Review 1 falsified both W1 and W2 in every predeclared cell. | Do not retune side, phase, boundary, cost, or parameters to rescue either ID. A successor must be new and frozen before later data. |
| D4 not directionally replicated | The D4 formal record reports 11/11 negative prospective clusters and forbids a reversed-sign rescue on the same sample. | D4 is not a strategy foundation and cannot be relabeled as a positive result. |
| Forward-operations partials | The v2 handoff records absent immutable-copy configuration, retrieval/recovery rehearsal, source checkpoint adoption, and qualified producer health; it recorded a stale ledger heartbeat. | Do not call storage, recovery, data freshness, or unattended operations verified without fresh qualified evidence. |
| Paper path is bounded | Existing paper execution is approval-bound. | A future no-human simulation is a finite offline replay test, not an unattended live service. |
| Live path absent by design | `AGENTS.md` and `docs/PROMOTION_GATE.md` retain a closed live boundary. | Broker integration/conformance is only a future **design prerequisite**, never executable transmission in this repository or skill. |

### Time is not one October 23 switch

The generated v3 report records the supplied assessment clock and the known frozen calendars without interpreting their outcomes. For example, DON8 has an earliest review date of **2026-10-23 UTC**, while several long-horizon forward watches have earliest review dates in **March and April 2027**. A report generated in March 2027 must use its actual supplied clock; it must not pretend every review matures on October 23.

Neither passing time nor this report creates a verdict. The corresponding frozen workflow is the only place a review calculation can occur.

## Operating principles for strategy changes and next tests

This is **not** a programme of nonstop parameter tuning. The preferred loop is:

1. State an executable **versioned causal rule** and its rationale.
2. Freeze the candidate, decisions, costs, universe, portfolio limits, and trial family **before** inspecting the evidence intended to test it.
3. Carry a benchmark and a no-trade control beside the candidate; do not select a rule because it had the best inspected PnL.
4. Model non-zero spread, fees, slippage, latency/staleness, and the venue's funding convention. Do not weaken friction to rescue expectancy.
5. Use point-in-time-qualified data and purged chronological, regime-aware cross-validation. Keep dependence clusters and trial accounting explicit.
6. Preserve risk controls: portfolio concentration/exposure limits and a positive, currency-denominated loss budget with a declared breach action.
7. Freeze again before new evidence. Later evidence can reject a rule; it cannot silently alter it.

This preserves the repository's existing protocol: first ask whether a feature has incremental causal information about a future market state, then test whether a separately frozen strategy survives executable friction. No alpha is assumed at any stage.

## Staged path

The stages are cumulative controls, not escalating permissions. The v3 tool can report locally self-consistent readiness for S1 or S2, but its authority claims remain false. S3 records whether review evidence exists; it does not issue a promotion decision.

| Stage | Scope | Required gates (in addition to earlier stages) | Explicitly excluded |
|---|---|---|---|
| **S0 — Research** | Reproducible research and strategy-change evaluation. | Frozen governance and trial ledger; executable versioned causal rules; candidate freeze before new evidence; point-in-time-qualified data; benchmark/no-trade controls; non-zero friction and funding convention; purged chronological regime cross-validation; portfolio limits and loss budget. | Claims of established edge, a DON8/W3 verdict, a W1/W2/D4 rescue, paper/live activation. |
| **S1 — Finite autonomous paper replay** | The implemented `paper_bot_v3` is a bounded, offline **simulated** replay that may make simulated decisions without a person approving each simulated decision. | Fixed start/end interval; no order routing; restart/replay exactly-once recovery rehearsal; stale-source rejection; fail-closed unattended fault controls; loss-budget halt and human escalation; detached storage/recovery/clock evidence. | Persistent order-generating/paper-execution service, schedule, credentials, deployment, broker API, transaction payload, live/paper order transmission, alpha claim. |
| **S2 — User-operated read-only analysis / qualified recording** | The current readiness-assessor contract covers a person deliberately running read-only market analysis and recording data under declared qualifications. | Explicit read-only/no-submission capability; point-in-time-qualified recording; retained provenance and freshness checks. | Order entry, account action, promotion. This assessor contract does not prohibit a separately designed future unattended read-only analysis or service. |
| **S3 — Independent review** | Separate promotion, operational, risk, and security review inputs are assembled. | Independent review record; operational/risk/security review; broker/venue integration and conformance **design** with `design_only=true`, `executable_transmission=false`, and no transaction payloads. | A review record becoming a promotion, implementation of a transmitter, credentials, deployment, or live orders. |
| **Outside this skill — user-controlled live-platform programme** | If the user later elects to explore a live platform, it is a separate engineering/governance programme under the user's control. | The user must independently choose the platform, authorization process, compliance/legal review, account/risk ownership, implementation team, conformance testing, rollback, monitoring, and final go/no-go. | Any claim that this repository, this roadmap, or `bot_readiness_v3` built or authorized live capability. |

### S0: research gate and next study definition

A strategy change is eligible to enter a future study only when its versioned rule is executable and frozen. It must declare at least:

- causal inputs, feature availability time, decision time, action/no-trade outcome, and exact version;
- intended universe, benchmark, and no-trade controls;
- declared non-zero round-trip costs plus fee, spread, slippage, latency/staleness, and funding conventions;
- portfolio limits and a loss-budget breach action;
- dependence cluster, purged chronological folds, regime split, holdout boundary, and trial-family accounting;
- source provenance, point-in-time qualification, and immutable candidate/protocol identities.

The next test is **not** “try another parameter.” It is a separately frozen hypothesis with the controls above, evaluated only on new qualified evidence. Existing frozen studies and all original frozen `config/` and `research/` bytes remain untouched.

### S1: finite autonomous paper replay gate

The phrase “no human per simulated decision” is intentionally narrow. It can mean an offline replay consumes a presealed input and evaluates a fixed decision algorithm for a finite interval without an operator clicking approval for each **simulated** event. It cannot mean a persistent unattended bot.

An S1 evidence object must substantively bind:

- `finite_replay.bounded_start_utc` and `bounded_end_utc`, with end after start;
- `finite_replay.no_order_routing=true` and `simulated_decisions_no_human=true`;
- restart/replay `exactly_once_verified=true` and a recovery rehearsal;
- unattended controls for `fail_closed`, stale-source rejection, loss-budget halt, and human alert/escalation;
- detached-copy verification, recovery rehearsal, and synchronized clock evidence;
- a fresh maximum source age. A stale or future-dated source fails closed.

A finite replay can demonstrate replay-engineering behavior. It cannot establish live fill realism, venue authenticity, durable external storage, profitable edge, promotion, or live order capability.

### S2: current user-operated read-only market analysis and recording contract

S2 currently records a user-operated read-only analysis or recording contract. Its evidence must say both:

```json
{
  "user_operated_read_only": true,
  "order_submission_capability": false,
  "qualified_recording": true,
  "recording_point_in_time_verified": true
}
```

This does not create an unattended collector or scheduler **in the present implementation**. It is not a policy prohibition on a separately designed future unattended read-only collector, analysis, reporting service, or monitoring service over recorded/public data. Such work must remain read-only and cannot generate paper-execution actions or transaction automation. A recorded data source still needs provenance, source self-hash, explicit observation time, freshness evaluation, and point-in-time qualification before it can be considered by a later research study.

### S3: independent review gate

S3 is an evidence-assembly and review stage, not an authorization stage. Its independent review records should challenge:

- promotion evidence, candidate freeze/holdout/trial accounting, and the distinction between statistical edge and paper engineering;
- operational fault containment, loss budget, reconciliation, rollback/recovery, storage retention, source freshness, and clocks;
- risk limits, portfolio concentration, funding/cost assumptions, and behavior under data gaps;
- security/privacy boundaries, credential handling (which this module does not implement), least privilege, auditability, and incident response;
- future broker/venue API conformance as a **design**. The design must explicitly state `executable_transmission=false` and `transaction_payloads_present=false` in any v3 provenance evidence.

No collection of S3 booleans can forge a strategy promotion or live opening. The report holds every non-authority claim false by schema and self-validation.

## `bot_readiness_v3` JSON contract

### Provenance source object

A source is a local self-consistency envelope. The hash covers its identifier, type, observation timestamp, assertions, and facts. It does not prove that the source is authentic or independent.

```json
{
  "schema": "orderflow_edge_lab.bot_readiness_source_provenance.v3",
  "source_id": "finite-replay-2027-03-28",
  "source_type": "paper_replay",
  "observed_at_utc": "2027-03-28T12:00:00Z",
  "evidence": {
    "finite_autonomous_paper_replay": "PASS",
    "restart_replay_exactly_once": "PASS",
    "unattended_fault_controls": "PASS",
    "detached_storage_recovery_clock": "PASS"
  },
  "facts": {
    "finite_replay": {
      "bounded_start_utc": "2027-03-27T00:00:00Z",
      "bounded_end_utc": "2027-03-28T00:00:00Z",
      "no_order_routing": true,
      "simulated_decisions_no_human": true
    },
    "restart_replay": {
      "exactly_once_verified": true,
      "recovery_rehearsed": true
    },
    "unattended_fault_controls": {
      "fail_closed": true,
      "stale_source_reject": true,
      "loss_budget_halt": true,
      "human_alert_escalation": true
    },
    "detached_storage": {
      "detached_copy_verified": true,
      "recovery_rehearsed": true,
      "clock_synchronized": true
    }
  },
  "source_sha256": "<canonical SHA-256 produced by the CLI>"
}
```

A source assertion is considered only if it is `PASS`, its self-hash is correct, it is not stale relative to the assessment clock and `max_source_age_seconds`, and its required structured facts are present. `FAIL`, `UNKNOWN`, missing facts, unknown check names, stale sources, and future timestamps fail closed.

### Assessment input

The caller must supply nonempty `required_checks`; the evaluator merges them with the immutable checks required by the selected target stage. A caller cannot omit a baseline check to bypass it. Unknown caller checks remain `UNKNOWN`.

```json
{
  "schema": "orderflow_edge_lab.bot_readiness_input.v3",
  "assessment_id": "s1-replay-readiness-2027-03-28",
  "target_stage": "S1_FINITE_AUTONOMOUS_PAPER_REPLAY",
  "as_of_utc": "2027-03-28T12:00:00Z",
  "max_source_age_seconds": 86400,
  "required_checks": ["finite_autonomous_paper_replay"],
  "source_provenance": []
}
```

An empty source list is valid input but will generate `MISSING` gaps. It cannot be used to infer a pass.

### Offline CLI

The CLI reads and writes only local JSON. It does not use network, storage-provider, broker, exchange, credentials, scheduler, or order APIs.

```bash
# Create a source envelope from an unsigned object (the command computes source_sha256).
python -m orderflow_edge_lab.cli.bot_readiness_v3 build-source --input unsigned_source.json > source.json

# Insert source.json into source_provenance[] in the input, then report readiness.
python -m orderflow_edge_lab.cli.bot_readiness_v3 assess \
  --input readiness_input.json \
  --output artifacts/bot_readiness_v3.json

# Rebuild and validate every report field and hash.
python -m orderflow_edge_lab.cli.bot_readiness_v3 validate \
  --input artifacts/bot_readiness_v3.json
```

The output includes `stage_state`, per-check states, `gaps`, `next_steps`, static repository blockers, calendar context, source/input/report hashes, and the exact all-false non-authority claims. It explicitly records that it did **not** issue DON8/W3 verdicts and that W1/W2/D4 are not rescindable through this tool.

## Implemented scope versus user-facing future roadmap

| Topic | Implemented now in this repository change | Future user-facing roadmap only |
|---|---|---|
| Research governance | Hash-bound readiness reporting of declared source facts, strict no-authority claims, documentation of current frozen-study boundaries. | Freeze a new candidate/protocol before new evidence and run the existing research workflows. |
| Finite paper replay | `paper_bot_v3` implements a finite offline simulated replay with checkpoint/replay validation and no service. | A separately reviewed replay with sealed inputs and additional fault-injection/operational evidence. |
| Read-only analysis | S2 readiness criteria only; no collector, polling loop, scheduler, or unattended read-only service is implemented or deployed. | User-operated qualified recording, or a separately designed future unattended read-only analysis/reporting/monitoring service with no paper-execution or transaction automation. |
| Independent review | S3 readiness criteria only. | Independent promotion, operational, risk, and security review records evaluated under their own governance. |
| Broker/venue integration | Design-only conformance prerequisite flag requiring no executable transmission. | A separately user-controlled live-platform engineering programme, outside this skill and after independent decisions. |
| Live orders | **Nothing.** | **Nothing is promised or authorized by this roadmap.** |

## Preservation and release discipline

This change is additive. It must preserve the raw-byte identities of all frozen studies and the original frozen `config/` and `research/` files (the v2 handoff records **535/535** protected identities unchanged). It must not alter DON8, W3, W1, W2, D4, discovery thresholds, review calendars, study definitions, or evidence artifacts.

Before merging an implementation that touches this roadmap, run focused unit tests and Ruff. A passing test suite verifies code behavior, not research promotion, source authenticity, storage durability, or live readiness.
