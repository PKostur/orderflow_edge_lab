# Validation statistics and research hygiene

This page covers the analysis and contract tooling that sits **between** the frozen
pipelines and the human review. Nothing here scores a strategy, changes a frozen
definition, or produces a verdict.

The rules in one place:

- a watch is only as good as what it fixed *before* its window opened, so the
  tooling **reports** a pre-registration gap and never patches one;
- the resampling unit is the **dependence cluster** (capture batch, bar, or day),
  never the row;
- every number produced on an already-open watch is labelled
  `post_hoc_descriptive` and may not be used as that watch's decision rule;
- thresholds are supplied by the caller or not at all.

## Commands

| Command | Question it answers | Preconditions |
|---|---|---|
| `orderflow robustness` | Given a frozen forward report, how wide is the uncertainty, what could this design ever resolve, does one symbol carry it, is the mirror arm also positive? | a frozen forward report; `--design-clusters` for the power line |
| `orderflow research-hygiene` | Are the watch contracts, frozen hashes, workflow/artifact graph and inspection registry intact? | a checkout |
| `orderflow discovery-screen` | Would this candidate clear the declared round-trip cost, and does the declared cost match measured friction? | `--declared-round-trip-cost-bps` and `--minimum-break-even-ratio` |
| `orderflow orthogonality` | Is the proposed indicator already carried by the existing regime variables, and does the result survive dropping a symbol or cluster? | `--redundancy-threshold` |

## Robustness layer

`orderflow robustness <report.json>` reads the interval rows a frozen forward
report already retains and adds:

- **Cluster bootstrap interval.** Clusters are resampled whole, so correlated
  rows move together. The point estimate is the frozen report's own statistic;
  only the interval is new.
- **Minimum detectable effect.** From the observed cluster-level dispersion and
  the cluster count the frozen gate implies, this says what the design could ever
  conclude at its own gate size. A gate that cannot resolve the effect it is
  looking for is important to know *before* the window matures.
- **Concentration**, reused from `discovery_v2_evaluation`: best-symbol share of
  positive PnL, top-5 share, and leave-one-symbol-out means.
- **Friction sensitivity**, reused from the same module: the cost surface and the
  break-even-to-paid-cost ratio.
- **Control arms** as Paired cluster differences against any variant the config
  declares a `CONTROL`. Controls are context; they are not a selection family.
- **Negative controls**: a side-reversed mirror arm (`-gross - cost`; a sign flip
  leaves turnover, and therefore cost, unchanged), bucket means with a rotated
  assignment, and single-symbol baskets. The report states plainly when a
  control is *not* computable — an hour-level phase shift is impossible from 8h
  interval rows, and that is reported rather than papered over.
- **Multiplicity**: the Bonferroni bound for a declared trial family, or an
  explicit `family_not_declared`.

Family-selection diagnostics (deflated Sharpe, PBO, reality check) run only when
at least two **non-control** variants exist. Treating a config's controls as a
variant family would invent a selection procedure the frozen config does not
contain.

## Pre-registration audit

`orderflow research-hygiene` describes, mechanically, which shape of decision rule
each registered watch fixed:

| Shape | Meaning |
|---|---|
| `canonical_decision_rule` | A complete `decision_rule` block: metric, direction, threshold, inconclusive trigger. |
| `review_rule_numeric_thresholds` | A `review_rule` with numeric bounds and requirement flags plus a declared metric list. |
| `dependence_gates_only` | Numeric gates on how much data must accumulate (batches, days, signals) plus metrics — guards, not a decision rule. |
| `declared_metrics_only` | Metrics declared with nothing numeric attached. |
| `incomplete_decision_rule` / `absent` | Partial or missing. |

Severity depends on whether the watch is already frozen. A gap in a **frozen**
watch cannot be repaired without changing the frozen definition, so it is a
documented warning. The same gap in a watch that is **not yet frozen** is still
fixable and fails the gate.

### Requirements for watches frozen from this version onwards

A new watch config must declare:

```json
{
  "decision_rule": {
    "metric": "net_mean_bps",
    "direction": ">",
    "threshold": 0.0,
    "inconclusive_when": "the clustered interval includes zero"
  },
  "trial_family": "family_name",
  "design": {
    "dependence_cluster": "capture batch",
    "design_effect_bps": 8.0,
    "design_units": "batches at the frozen gate"
  }
}
```

Existing frozen watches keep their own shapes; the audit records them as
acknowledged gaps rather than retrofitting a rule.

## Frozen definition hash manifest

`config/frozen_manifest_v1.json` records `(path, sha256)` for the definitions
whose numeric content must not move silently: `discovery-v1` thresholds, the
pre-registered `regime-research` families, the frozen conditioning blocks, the
state-threshold freeze, and the prospective watch definitions.

A mismatch is an error. Changing one of those files means either restoring it or
moving to a versioned successor with a fresh freeze record, then updating the
manifest **in the same reviewed change**. There is deliberately no write mode:
rewriting the recorded hash is the operation the manifest exists to make visible.

Documentation and navigation (`STATUS.md`, `README.md`, `docs/`) are expected to
change and are not listed.

## Workflow to artifact contract

Artifacts in this repository are consumed two ways: `actions/download-artifact`
and the REST API inside shell steps (`gh api .../artifacts ... startswith("...")`).
Both are scanned. The second path matters: `capture-health-watch-v1.yml` could
only ever report "directory absent" because it read a path CI never populated,
and a contract test that only understood the action form would have missed it.

Errors: a consumer with no producer anywhere; a retention requirement whose
declared producer does not upload the artifact; a duplicate or invalid manifest
entry. Warning: a workflow that reads the artifact REST API without naming any
artifact filter, so no producer can be verified for it.

## Inspection registry

`config/hypothesis_inspection_registry_v1.json` records one entry per inspected
lane: what was asked, over which window, against which dependence clusters, and
in what state it ended. It is an accounting layer — the canonical record of each
lane remains the authority and no number is recomputed from it.

Two invariants: a `FALSIFIED` or `CLOSED` identifier sets `id_reusable` false
(reopening it would convert inspected data into apparent confirmation), and
`data_spent` must be true once a lane is evaluated, falsified or closed.

## Discovery-time economics

Screen on economics before spending a validation window. `orderflow
discovery-screen` requires a declared round-trip cost and a caller-declared
break-even multiple, then reports whether the candidate clears it and whether the
declared cost matches friction measured from recorded quotes. A declared cost
**below** the measured estimate is an error: realistic friction assumptions must
not be weakened. Tightening one is allowed and encouraged.

## Wiring into a review

For a watch that has met its gate, in order:

1. `orderflow review-clock` — confirm the window matured.
2. `orderflow review-packet` — hash-pinned skeleton with empty verdict cells.
3. `orderflow robustness` — descriptive context over the same frozen report, with
   `--design-clusters` set from the frozen gate.
4. `orderflow artifact-coverage` — confirm every declared input is still
   retrievable.
5. `orderflow research-hygiene` — contracts and hashes intact before the record
   is written.

In the written record, each reported rule is labelled `pre-registered` or
`post-hoc`, and no post-hoc number may be used as the watch's decision rule.
