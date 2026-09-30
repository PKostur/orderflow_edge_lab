# DON8 formal review runbook

Operational procedure for the review of the frozen cross-strategy session forward
watch `evidence_v2_cross_strategy_session_forward_v1` (DON8), whose review window
opens **2026-10-23 00:00:00 UTC**.

This runbook changes nothing. It does not add a criterion, move a boundary, alter a
cost, or authorise a promotion. See
[`research/DON8_FORMAL_REVIEW_CRITERIA_2026_10_23.md`](../research/DON8_FORMAL_REVIEW_CRITERIA_2026_10_23.md)
for the pre-registered procedural rules that apply to the review record itself.

## Authority (read-only)

| Input | Path / workflow | Role |
|---|---|---|
| Frozen watch definition | `config/evidence_v2_session_forward_watch_v1.json` (freeze commit `37ec950f1ff4420c877a3dc370e7d0d7419947ae`) | the only definition of the hypothesis, horizon, costs, symbols, and metrics |
| Frozen counting/forward authority | `.github/workflows/evidence-v2-session-forward.yml` | produces the cumulative report and enforces the boundary |
| Priority freeze | `research/VALIDATION_PRIORITY_FREEZE_2026_09_23.md` | DON8 is priority 1 while the window is open |
| Current state | `STATUS.md` | navigation only; a frozen artifact always wins |
| Pipeline evidence | ledger manifest + `session_watch_report.json` inside the `orderflow-discovery-ledger-v1` artifact | frozen counting for the session watches |

Nothing in this runbook may be used to justify an earlier verdict. `reporting.no_early_pass_fail`
is `true` in the frozen config.

## Step 0 — confirm the window has matured

```bash
orderflow review-clock --output artifacts/prospective_review_clock.json
```

The DON8 entry must show `review_window_matured: true` and
`earliest_review_utc: 2026-10-23T00:00:00Z`. If it does not, **stop**: no review
body may be written.

## Step 1 — collect the frozen forward report

The report is produced three times daily by `evidence-v2-session-forward.yml`
(`cron: 20 0,8,16 * * *`) and uploaded as the artifact
`evidence-v2-cross-strategy-session-forward` (30-day retention). Take the newest
run **at or after** the review date:

```bash
gh run list --workflow evidence-v2-session-forward.yml --limit 5
gh run download <run-id> --name evidence-v2-cross-strategy-session-forward --dir artifacts/don8
python - <<'PY'
import json
r = json.load(open('artifacts/don8/report.json', encoding='utf-8'))
assert r['prospective_start_utc'] == '2026-09-23T00:00:00+00:00', 'boundary changed'
assert r['claims']['candidate_promoted'] is False
assert r['claims']['live_trading_authorized'] is False
assert r['claims']['leverage_authorized'] is False
print(r['watch_id'], r['status'], r['as_of_utc'], r['days_elapsed'])
PY
```

## Step 2 — build the review skeleton (no verdicts)

```bash
orderflow review-packet artifacts/don8/report.json \
  --output artifacts/don8/review_packet.json \
  --markdown artifacts/don8/review_packet.md
```

The packet copies pipeline numbers verbatim, pins the SHA-256 of the report it
read, and leaves every verdict cell empty. It reports `AWAITING_REVIEW_WINDOW` if
the window has not matured, and in that case renders no review body.

## Step 3 — descriptive robustness of the same frozen report

```bash
orderflow robustness artifacts/don8/report.json \
  --watch-config config/evidence_v2_session_forward_watch_v1.json \
  --design-clusters 90 \
  --output artifacts/don8/robustness.json \
  --markdown artifacts/don8/robustness.md
```

This reads the interval rows the frozen report already retains and adds context
the report itself does not carry: a cluster bootstrap interval, the smallest
effect the frozen 30-day gate could ever resolve (`--design-clusters 90` is 30
days x three 8h bars), concentration and leave-one-symbol-out shares, friction
sensitivity, the paired difference against each declared control, and negative
controls (side-reversed mirror, bucket means, single-symbol baskets).

Three rules for using it in the record:

1. it is labelled `post_hoc_descriptive` and is **not** pre-registered for this
   watch; the frozen config declares metrics without numeric thresholds, so the
   review is descriptive rather than pass/fail;
2. no number from it becomes the decision rule, and no threshold is derived from
   it after the fact;
3. it never overrides the frozen report. Where they disagree, the frozen report
   wins.

## Step 4 — check that the evidence was still retrievable

```bash
gh api "repos/${GITHUB_REPOSITORY}/actions/artifacts?per_page=100" --paginate \
  --jq '.artifacts[] | {name, id, created_at, expires_at, size_in_bytes, expired}' \
  > artifacts/artifact_inventory.jsonl
orderflow artifact-coverage \
  --inventory artifacts/artifact_inventory.jsonl \
  --repo-root . \
  --output artifacts/coverage.json \
  --markdown artifacts/coverage.md
```

## Step 5 — confirm the contracts before writing the record

```bash
orderflow research-hygiene --repo-root . \
  --output artifacts/hygiene.json \
  --markdown artifacts/hygiene.md
```

This verifies that the frozen definitions still match `config/frozen_manifest_v1.json`,
that every watch's pre-registration status is recorded, that every artifact the
pipeline consumes still has a producer, and that the hypothesis-inspection
registry is intact. Exit code 2 means an error-severity finding: resolve it or
record why not before writing a verdict.

Any `artifact_missing`, `artifact_expires_before_required_through`, or
`rederivation_horizon_exceeded` finding must be recorded in the review as a
provenance limitation. A missing input makes the affected metric **INCONCLUSIVE**,
never a pass.

For the session watches that share the counting pipeline, extract the frozen
counting report from the ledger artifact rather than recomputing anything:

```bash
gh run download <continuous-discovery-run-id> --name orderflow-discovery-ledger-v1 --dir /tmp/ledger
python -c "import json,glob;print(glob.glob('/tmp/ledger/**/session_watch_report.json',recursive=True))"
orderflow review-packet /tmp/ledger/artifacts/orderflow/session_watch_report.json \
  --output artifacts/session_watch_packet.json --markdown artifacts/session_watch_packet.md
```

## Step 6 — write the review record

Create `research/DON8_FORMAL_REVIEW_2026_10_23.md` containing, in this order:

1. the review date and that it is at or after the frozen review date;
2. the exact source artifact, run id, and SHA-256 of the report that was reviewed;
3. the frozen hypothesis statement quoted verbatim from the config;
4. the per-metric table with the pipeline's numbers, each flagged
   *pre-registered* or *post-hoc* in its own column per the criteria addendum;
5. the verdict for each predeclared metric, then one overall verdict;
6. explicit limitations (including every coverage finding and the fact that the
   frozen config declares metrics but no numeric thresholds);
7. the sign-off block from the packet.

## Step 7 — archive the evidence with the record

Commit, alongside the review record:

- `review_packet.json` (contains the pinned report hash) and `review_packet.md`;
- `robustness.json` and `robustness.md`, labelled post-hoc in the record;
- `hygiene.json`;
- `coverage.json` and the artifact inventory listing used;
- the review clock report showing the window had matured.

Never recompute counts by hand and never quote a partial-period endpoint. If a
number in the record disagrees with the frozen artifact, the artifact wins.

## Step 8 — state the consequence

- **Not established / falsified**: the ID is terminal — no retuning, re-siding,
  re-phasing, re-symboling, or session-boundary changes under the same ID. Record
  it in `research/INDEX.md` and `STATUS.md`.
- **Supported**: promotion still requires candidate freeze, holdout audit,
  trial-ledger accounting, economics policy, and approval-bound paper/shadow
  reliability evidence (`docs/PROMOTION_GATE.md`). A favourable review alone
  authorises nothing.

Live order transmission remains disabled throughout. The review is a research
decision, not a deployment.

## Checklist

- [ ] Window matured per the review clock.
- [ ] Forward report fetched from a run at or after 2026-10-23T00:00:00Z; boundary and claims asserted.
- [ ] Review packet generated; every verdict cell filled by a named human.
- [ ] Descriptive robustness run and labelled post-hoc in the record; no threshold derived from it.
- [ ] Coverage audit run; limitations recorded.
- [ ] Hygiene report clean (or every error-severity finding explained in the record).
- [ ] Report SHA-256 recorded in the review document.
- [ ] Procedure addendum rules applied (no early verdict, no control substitution, no cost renegotiation).
- [ ] `research/INDEX.md` and `STATUS.md` updated to the terminal state.
- [ ] No promotion, no leverage, no live execution implied.
