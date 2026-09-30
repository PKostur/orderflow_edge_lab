# DON8 formal review — pre-registered procedure addendum

- Research ID: `evidence_v2_cross_strategy_session_forward_v1` (DON8)
- Frozen watch definition: `config/evidence_v2_session_forward_watch_v1.json`
  (freeze commit `37ec950f1ff4420c877a3dc370e7d0d7419947ae`, frozen at
  2026-09-22T20:01:45Z, prospective start 2026-09-23T00:00:00Z)
- Review window opens: **2026-10-23T00:00:00Z**
- This document was written and committed on **2026-09-29**, while the prospective
  window was still open and before any forward result had been reviewed.

## Status of this document

This addendum **does not modify** the frozen watch definition, the hypothesis, the
symbol universe, the session buckets, the 20 bps round-trip cost, the metric list,
or the review date. It adds **no numeric pass/fail threshold**.

What it does: it fixes, in advance, the *procedural rules* the review record must
follow. These rules are the non-numeric parts of the frozen specification that were
previously only implicit in `docs/RESEARCH_PROTOCOL.md` and the standing stop rule
in `STATUS.md`. Writing them down now, before the window closes, means the review
cannot quietly choose its own procedure after seeing the outcome.

Recorded limitation, stated up front: the frozen config declares **which** metrics
to review but no numeric threshold for any of them. The review must therefore
record, for each metric, both the observed value and whether the rule used to judge
it was pre-registered here or chosen post-hoc at review time. This is a weakness of
this watch's pre-registration, not a licence to relax the rules below.

## Binding procedural rules

1. **Timing.** No verdict of any kind may be recorded before 2026-10-23T00:00:00Z.
   Partial-window numbers may exist in automated artifacts; they are progress
   observability, never evidence. A verdict recorded earlier is void.
2. **Single source of truth.** Only the report produced by
   `.github/workflows/evidence-v2-session-forward.yml` counts, and only a report
   whose `prospective_start_utc` is `2026-09-23T00:00:00+00:00`. Numbers
   recomputed by hand, from a different workflow, or from a partially recovered
   artifact are not admissible.
3. **Hypothesis first, as stated.** The primary hypothesis is evaluated exactly as
   frozen: DON8's after-cost contribution during 08:00–16:00 UTC, and that
   contribution relative to its own 00:00–08:00 UTC contribution. An all-session
   result may be reported alongside as context but **cannot substitute** for the
   primary hypothesis, and a favourable all-session number may not be presented as
   passing it.
4. **Missing input ⇒ INCONCLUSIVE, never PASS.** If a predeclared metric cannot be
   produced — including because a required artifact was no longer retrievable or a
   re-derivation horizon expired — the metric is `INCONCLUSIVE`. An inconclusive
   primary hypothesis is not a pass and does not authorise a follow-up watch that
   reuses this ID.
5. **Decision-rule transparency.** Before the verdict sentence, the record must
   print the rule that produced each verdict and label it `pre-registered` or
   `post-hoc`. A `post-hoc` rule may not be the basis for a *supported* verdict
   without saying so explicitly.
6. **Controls are context.** `EMA8`, `VOL8`, and `EMA4` are controls. Control
   outperformance can never convert a failed primary hypothesis into a pass, and
   control underperformance does not rescue one either.
7. **Economics are not renegotiable.** The frozen 20 bps round-trip cost stands.
   Spread, slippage, latency/freshness, and failure assumptions may not be weakened
   to improve the result, and leverage may not be introduced to rescue expectancy.
8. **Trial accounting.** This watch must be entered in the trial ledger before any
   promotion discussion, and the review must record the number of trials in the
   family it belongs to.
9. **Terminality.** If the outcome is not established, the ID is terminal: no
   retuning, re-siding, re-phasing, symbol exclusions, session-boundary changes, or
   cost changes under the same ID. A future attempt requires a new, separately
   frozen ID and a new prospective window.
10. **No implied authorisation.** A favourable review authorises nothing by itself.
    Promotion still requires candidate freeze, holdout audit, trial-ledger
    accounting, economics policy, and approval-bound paper/shadow reliability
    evidence. Live order transmission remains disabled.
11. **Recoverability is part of the evidence.** Any coverage finding for the inputs
    used (missing artifact, retention expiring before the required-through date, or
    an expired re-derivation horizon) must be listed as a limitation of the record.

## Lesson carried forward

Every future prospective watch should freeze, before its window opens:

- the numeric decision rule per metric (or an explicit statement that the outcome
  is descriptive only and cannot be called a pass), and
- the retention requirement for every input needed to reproduce it
  (`config/evidence_retention_requirements_v1.json` is the mechanised form of the
  second item).

## Sign-off

- Rules recorded by: _(name)_
- Date (UTC): 2026-09-29 (prospective window still open; no forward result reviewed)
- Supersedes: nothing. Adds: procedural rules for the review record only.
