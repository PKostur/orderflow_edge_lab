# Session state (updated 2026-09-26)

## Branches
| Branch | Head | Status |
| --- | --- | --- |
| `fix/universal-existing-validation` | `0966172` | PR #113, draft; CI green 2026-09-25 18:42Z |
| `research/payoff-geometry-v1-1` | see `git log` | v1.1 payoff geometry; CI and workflow green (runs 36195553039 and 36195553117) |

## Open findings (unresolved)
1. **Scheduled workflows never fire.** The prospective shadow, research control
   plane, operational monitor, payoff-geometry forward and VOL8 forward
   workflows exist only on the PR branch. Cron runs only from the default branch
   (`main`), so all past runs were push-triggered. A scheduler workflow on `main`
   was blocked by the permission classifier (persistence), so the user must
   decide or add it. The prospective shadow
   (start 2026-09-26T00:00Z) is not running. Fixing this needs a `main` change,
   which is the user's decision.
2. **Short-side accounting asymmetry.** The canonical ledger compounds shorts as
   constant-notional (`Π(1−r)`) and longs as fixed-quantity. The ledger-minus-static
   gap for DON8 shorts has p50 −244 bps and p10 −1,029 bps. Re-scored with fixed
   quantity (`short_convention_comparison`): DON8 short PF 0.87→1.35 and EMA8 short
   PF 0.86→1.30, with longs identical. Frozen; adopting it needs canonical v3.
3. **Effective N is about 16–31 per cell** even for thousands of trades. The raw
   N ≥ 20 sufficiency rule overstates the evidence.
4. **VOL8 excursion ordering:** 37% of episodes are `SAME_BAR`, so ordering is
   unobservable for them.

## Decisions
- Workstream D (`universal-market-state-labels-v1`) was not built. It only
  re-cuts v1 thresholds after v1 occupancy had been seen (post-hoc). The
  prospective shadow already applies the v1 labels forward.
- The comparison against the 2026-09-24 snapshot is impossible: there have been
  no scheduled runs since (finding 1). The shadow status is PRE_START with 0 trades.

## Next action candidates
- `ask_user`: move or add the forward workflows on `main` (finding 1).
- `ask_user`: whether to start canonical accounting v3 (fixed-quantity shorts) and re-bind dependent protocols.
- `collect_evidence`: once the shadow is running, report the first post-start trades descriptively.
