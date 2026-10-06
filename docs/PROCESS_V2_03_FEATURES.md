# Causal features and targets v2 (opt-in)

`orderflow_edge_lab.features_v2` is an **additive, offline successor** for the
feature/market-state issues addressed in stage 03. It does not import, rewrite,
rerun, relabel, or replace legacy `market_state_scan`, `market_conditions`,
`btc_correlation`, frozen research configurations, open watches, or historical
reports.

> A successful v2 object verifies only deterministic local input structure and
> caller-declared byte identities. It does **not** establish provider
> completeness/authenticity, durable external storage, external policy-freeze
> approval, engine calibration, profitability, promotion, or live execution.

All v2 outputs carry the shared mandatory `non_authority_claims` with every
claim set to `false`.

## Policy lifecycle and activation blockers

The three v2 policy constructors require **all parameters from the caller**;
they never invent a freshness threshold, target boundary, gap allowance,
baseline, bootstrap setting, bar cadence, correlation cutoff, or PnL rule.

| Policy constructor | Required declared content | Runtime rule |
|---|---|---|
| `build_feature_policy_v2` | Quote sources/freshness/recovery handling, scan interval/cadence, target horizon/endpoint lag/interior gap/point count | Scan requires `FROZEN_FOR_NEW_EVIDENCE`; direct combined eligibility remains ineligible under `DECLARED_INACTIVE`. |
| `build_orthogonality_policy_v2` | Target-specific full baselines, complete candidate admission order, redundancy threshold, cluster-bootstrap settings | Full-baseline calculation requires `FROZEN_FOR_NEW_EVIDENCE`. |
| `build_btc_correlation_policy_v2` | Context, cadence, min samples and PnL-free panel composition thresholds | Closed-bar correlation input requires `FROZEN_FOR_NEW_EVIDENCE`. |

The `FROZEN_FOR_NEW_EVIDENCE` marker is still only a **caller-declared local
identity binding** (`freeze_evidence_sha256`), not a verified external freeze.
Activation requires a separately approved durable policy/config freeze before
new evidence is viewed, stored, or used. Durable external retention,
provider-authority/coverage evidence, and independent engine calibration remain
external blockers. No working defaults represent these unavailable facts.

## F1 — Quote provenance and freshness

`build_quote_provenance_v2` binds a feature-time reference to its **original**
accepted `snapshot` or `depth` event. It reports:

- source event type, original receipt time, optional exchange timestamp, and
  exact `quote_age_ns_at_feature`;
- original BBO-derived quote values, source set, policy hash, and self-hash;
- an explicit eligible/ineligible reason for stale quotes, missing receipt or
  exchange time, invalid BBO, unaccepted depth transition, recovered-book
  policy, and a trade echo.

A `trade` can be retained as a flow/trade reference by `scan_market_state_v2`,
but it **cannot** be added to the quote series, quote-update intensity, or
quote target points. A missing provenance reference fails closed.

`feature_eligibility_v2` requires a hash-bound `capture_pair` binding from the
capture/replay owner with exact source-set equality, `outcome=COMPLETE`, and
`replay_status=REPLAY_ELIGIBLE`. It also binds quote, optional context quote,
and optional target to the same feature policy/source set.

## F2 — Strictly future mature targets

`build_mature_target_v2` uses the explicit contract interval
**`(anchor, anchor + horizon]`**. The anchor is a return baseline only; it is
not a future liquidity sample. Per target it records:

- open/closed UTC interval, anchor/end/capture times;
- strictly post-anchor quote count, maximum interior gap, endpoint time and
  lag;
- maturity/eligibility and deterministic exclusion reason;
- future mid/spread/depth summaries, endpoint return, range, realized
  volatility, and directional efficiency only when mature.

The endpoint must be within caller-declared maximum lag. A capture ending before
the horizon, pending/truncated endpoint, endpoint omission/late endpoint,
interior quote gap, or too few genuine post-anchor points stays
`NOT_MATURE`/`INELIGIBLE`; it is never populated with a late substitute.

`scan_market_state_v2` creates coverage over every declared cadence anchor and
target, emits attrition/quality counts, and computes associations only on
feature-eligible rows with mature targets. Its manifest is incomplete when the
expected grid has missing/ineligible entries.

## F3 — Full-baseline, dependence-aware incremental information

`build_full_baseline_orthogonality_v2` accepts only exact-shape PnL-free,
quality-qualified evidence rows. For **every** candidate in a caller-declared
target admission order, including candidates outside all pairwise redundancy
clusters, it calls the existing descriptive rank incremental-information
machinery against the complete declared baseline and dependence cluster.

The report binds the source set, canonical evidence-table hash, policy hash,
cluster count, complete baseline, candidate order, bootstrap interval, pairwise
redundancy diagnostic, and leave-one-dependence-cluster-out values. It has no
admission verdict: `review_status=DESCRIPTIVE_HUMAN_REVIEW_REQUIRED` and
`automatic_feature_admission=false`.

## F4 — BTC bar quality and immutable `as_of`

`build_btc_correlation_input_v2` requires explicit `as_of_utc`, cadence, and
closed-bar flags. It records a canonical input payload hash, source set,
normalized as-of, per-symbol coverage ledger and return-pair drops. It only
forms a return when adjacent **common** closed bar timestamps differ by exactly
the caller-declared cadence. A gap cannot become a synthetic longer-duration
return. Duplicate/out-of-order rows mark the series/correlation invalid;
unclosed bars are dropped. Fewer than declared minimum valid pairs is
`INSUFFICIENT`, never filled.

`build_btc_correlation_panel_v2` accepts only candidates that explicitly say
`strategy_pnl_used=false`. Its canonical selection ordering is compatibility
rank then symbol (with PnL-free correlation-diversity fallback); it cannot
promote a panel.

## F5 — PnL barrier

`build_state_discovery_v2` produces a PnL-free discovery artifact from the v2
scan and optional full-baseline report. It has canonical target/candidate review
order and explicitly contains no PF ranking or state-hypothesis eligibility.

`build_pnl_stratification_v2` returns
`WAITING_FOR_FROZEN_STATE_HYPOTHESIS` with no PnL rows unless a caller supplies
a hash-bound lineage containing the state discovery, feature policy, frozen
state hypothesis, threshold mapping, trial-accounting identity, outcome-maturity
identity, effective freeze time, and exact PnL source set. With a valid lineage
it returns only `DESCRIPTIVE_NON_PROMOTING` rows, sorted by condition then arm.
It requires baseline and conditioned arms to have identical fee and gate
identities. It intentionally exposes no PF-ranked list, selection verdict, or
promotion result.

## Offline CLI development path

The stage deliberately does not alter global package scripts or the legacy
command dispatcher. Until stage 10 registers a package command, the runnable
module path is:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /home/ubuntu/orderflow-implementation/venv/bin/python \
  -m orderflow_edge_lab.features_v2 --help
```

| Subcommand | Purpose |
|---|---|
| `feature-policy`, `orthogonality-policy`, `btc-policy` | Canonicalize a caller declaration into a hash-bound, non-authoritative policy. |
| `scan` | Hash a local JSONL raw source, compare it to the supplied capture-pair binding, and run the genuine-quote/mature-target scan. |
| `orthogonality` | Hash a local PnL-free evidence table and test every declared candidate against its full baseline. |
| `btc-input` | Hash a local bar payload and create reproducible closed-bar cadence/correlation evidence. |
| `discovery` | Build a PnL-free discovery artifact. |
| `pnl-stratification` | Build waiting output or a frozen-lineage-gated descriptive report. |

Each write is a newly named caller-selected output. No command contacts a
provider, collector, scheduler, durable-storage service, broker, or exchange.

## Required integration contract extension

Stage 02/integrator must provide a canonical `capture_pair` object accepted by
this module (or an adapter that produces the exact shape):

```json
{
  "schema": "orderflow_edge_lab.capture_pair_binding.v2",
  "analysis": "capture_pair_replay_eligibility",
  "source_set": {"...": "shared contracts_v2 canonical source set"},
  "outcome": "COMPLETE",
  "replay_status": "REPLAY_ELIGIBLE",
  "capture_start_utc": "timezone-aware UTC ISO-8601",
  "capture_end_utc": "timezone-aware UTC ISO-8601",
  "non_authority_claims": {"all shared claims": false},
  "capture_pair_sha256": "canonical SHA-256 of the preceding fields"
}
```

Stage 10/integration owns adding an installed console-script/dispatcher entry
for `features_v2`; this stage intentionally only supplies the tested `python
-m` path. Before any PnL-conditioned artifact is activated, the research/trial
owner must produce a durable, independently reviewable lineage and freeze
record. Those later assertions remain caller-declared in this module, never
verified facts.
