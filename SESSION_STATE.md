# Session state (updated 2026-09-26 08:05Z)

## Branches
| Branch | Head | Status |
| --- | --- | --- |
| `fix/universal-existing-validation` | `0966172` | PR #113, draft; CI green 2026-09-25 18:42Z; no new runs |
| `research/payoff-geometry-v1-1` | see `git log` | v1.1 payoff geometry; CI green (last run 36196258328) |
| `main` | origin/main | scheduled workflows green through 07:54Z; 8h and D4 scheduler bridges active |

## Forward evidence (descriptive only)
| Watch | Last run | Status | DON8 / EMA8 / VOL8 completed · open |
| --- | --- | --- | --- |
| regime marginal pairwise shadow v1 (via 8h bridge, collector ref `0966172`) | 36220693322, 05:24Z | ACCUMULATING, day 0 | 0·0 / 0·0 / 0·0 |

- Coverage: 10 symbols × 805 8h bars, 2026-01-01 → 2026-09-26 00:00Z, no gaps. 92 contrasts frozen; anchors 0; inferential window closed.
- The bridge alternates jobs: 05:15Z run did session-alignment and VOL8 forward; 05:24Z run did the regime shadow.
- No runs yet of operational monitor, research control plane or jev-research-decision (they are not on `main` and are not bridged).

## Open findings (unresolved)
1. **Scheduled workflows (partly resolved).** Cron fires only from `main`. The user added
   `prospective-8h-evidence-scheduler-bridge-v1.yml` (cron 00/08/16 :25 and :40) and a D4 bridge on
   `main`; they run the regime shadow, VOL8 forward and session-alignment collectors from pinned
   ref `0966172`, and disable themselves once native workflows reach `main`. Operational monitor,
   control plane and jev decision are still unscheduled.
2. **Short-side accounting asymmetry.** The canonical ledger compounds shorts as
   constant-notional (`Π(1−r)`) and longs as fixed-quantity. DON8 short ledger-minus-static gap
   p50 −244 bps, p10 −1,029 bps. Fixed-quantity re-score: DON8 short PF 0.87→1.35, EMA8 short PF
   0.86→1.30, longs identical. Frozen; adopting it needs canonical v3.
3. **Effective N is about 16–31 per cell** even for thousands of trades. The raw
   N ≥ 20 sufficiency rule overstates the evidence.
4. **VOL8 excursion ordering:** 37% of episodes are `SAME_BAR`, so ordering is unobservable.

## Decisions
- Workstream D (`universal-market-state-labels-v1`) was not built (post-hoc re-cut of v1 thresholds).
- Monitor runs pick one action; 2026-09-26 08:05Z run = `collect_evidence` only, no code change.

## Next action candidates
- `collect_evidence`: after the 08:25/08:40Z bridge runs, report the first post-start trades.
- `ask_user`: whether to schedule operational monitor / control plane / jev decision (finding 1).
- `ask_user`: whether to start canonical accounting v3 (fixed-quantity shorts).
