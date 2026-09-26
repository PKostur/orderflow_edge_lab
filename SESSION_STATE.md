# Session state (updated 2026-09-26 08:05Z)

## Branches
| Branch | Head | Status |
| --- | --- | --- |
| `fix/universal-existing-validation` | `0966172` | PR #113, draft; CI green 2026-09-25 18:42Z; no new runs |
| `research/payoff-geometry-v1-1` | see `git log` | v1.1 payoff geometry; CI green (last run 36228586717) |
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
   ref `0966172`, and disable themselves once native workflows reach `main`. PR #114 (open, awaiting
   user merge) schedules the rest: payoff-geometry forward, jev decision, operational monitor,
   control plane, and the v3 forward companion.
2. **Short-side accounting asymmetry.** The canonical ledger compounds shorts as
   constant-notional (`Π(1−r)`) and longs as fixed-quantity. DON8 short ledger-minus-static gap
   p50 −244 bps, p10 −1,029 bps. Fixed-quantity re-score: DON8 short PF 0.87→1.35, EMA8 short PF
   0.86→1.30, longs identical. `canonical_v3` (fixed quantity between target changes) is implemented
   and reproduces this; v2 stays bound to frozen protocols. `universal-canonical-v3-forward-companion-v1`
   is pre-registered (start 2026-09-27T00:00Z): DON8/EMA8/VOL8 forward trades under v2 and v3.
3. **Effective N is about 16–31 per cell** even for thousands of trades. The raw
   N ≥ 20 sufficiency rule overstates the evidence.
4. **VOL8 excursion ordering:** 37% of episodes are `SAME_BAR`, so ordering is unobservable.

## Decisions
- Workstream D (`universal-market-state-labels-v1`) was not built (post-hoc re-cut of v1 thresholds).
- Monitor runs pick one action; 2026-09-26 08:05Z run = `collect_evidence` only, no code change.
- 08:05Z (second pass): no new PR #113, bridge or target-workflow runs; monitor only.

## Next action candidates
- `collect_evidence`: after the 08:25/08:40Z bridge runs, report the first post-start trades.
- `ask_user`: merge PR #114, then dispatch it once with `all`.
- `collect_evidence`: after 2026-09-27, report the v3 companion's first trades descriptively.
