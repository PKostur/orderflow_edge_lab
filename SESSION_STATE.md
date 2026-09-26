# Session state (updated 2026-09-26 ~10:00Z)

## Branches
| Branch | Head | Status |
| --- | --- | --- |
| `fix/universal-existing-validation` | `0966172` | PR #113, draft; CI green 2026-09-25 18:42Z; no new runs |
| `research/payoff-geometry-v1-1` | see `git log` | v1.1 payoff geometry; CI green (last run 36228586717) |
| `main` | `d1cde34` | PR #114 merged: branch-forward-scheduler live; scheduled workflows green through 07:54Z; 8h and D4 scheduler bridges active |

## Forward evidence (descriptive only)
| Watch | Last run | Status | DON8 / EMA8 / VOL8 completed · open |
| --- | --- | --- | --- |
| regime marginal pairwise shadow v1 (8h bridge, ref `0966172`) | 05:24Z | ACCUMULATING, day 0 | 0·0 / 0·0 / 0·0 |
| payoff-geometry forward v1 (fixed in `cef1490`) | 09:49Z | ACCUMULATING, day 0 | 0·1 / 0·0 / – |
| session-alignment (control plane 08:55Z) | 08:55Z | WAITING_FOR_COMPLETIONS | 0·1 / 0·0 / 0·0 |
| v3 forward companion | today | PRE_START (starts 2026-09-27) | 0 / 0 / 0 |

- Only open post-start episode: DON8 LINK LONG from 2026-09-25 16:00Z, pre-entry vol HIGH, currently +160 bps net (MFE 258, MAE −122). Open, so not scored.
- Direction mix: DON8 long 10/10, EMA8 long 10/10, VOL8 long 9/10 (1 flat); no shorts. The book is effectively one long crypto-beta bet, so short-side and v3 evidence will be slow to arrive.
- Jev and control plane: offline deterministic provider, action `collect_more_evidence` / `ACCUMULATE_UNCHANGED`.

- Coverage: 10 symbols × 805 8h bars, 2026-01-01 → 2026-09-26 00:00Z, no gaps. 92 contrasts frozen; anchors 0; inferential window closed.
- The bridge alternates jobs: 05:15Z run did session-alignment and VOL8 forward; 05:24Z run did the regime shadow.
- The operational monitor, control plane, Jev decision, payoff-geometry forward and v3 companion now run via the `main` scheduler (first dispatch 2026-09-26 ~09:40Z, all green after the fix).

## Open findings (unresolved)
1. **Scheduled workflows (partly resolved).** Cron fires only from `main`. The user added
   `prospective-8h-evidence-scheduler-bridge-v1.yml` (cron 00/08/16 :25 and :40) and a D4 bridge on
   `main`; they run the regime shadow, VOL8 forward and session-alignment collectors from pinned
   ref `0966172`. RESOLVED for the rest: PR #114 (merged) schedules payoff-geometry forward, jev
   decision, operational monitor, control plane and the v3 companion.
   Bug found on first post-start run: payoff-geometry forward leaked a private Timestamp field into
   the JSON. Fixed on the PR #113 branch in `cef1490` with a regression test.
2. **Short-side accounting asymmetry.** The canonical ledger compounds shorts as
   constant-notional (`Π(1−r)`) and longs as fixed-quantity. DON8 short ledger-minus-static gap
   p50 −244 bps, p10 −1,029 bps. Fixed-quantity re-score: DON8 short PF 0.87→1.35, EMA8 short PF
   0.86→1.30, longs identical. `canonical_v3` (fixed quantity between target changes) is implemented
   and reproduces this; v2 stays bound to frozen protocols. `universal-canonical-v3-forward-companion-v1`
   is pre-registered (start 2026-09-27T00:00Z): DON8/EMA8/VOL8 forward trades under v2 and v3.
3. **Effective N is about 16–31 per cell** even for thousands of trades. The raw
   N ≥ 20 sufficiency rule overstates the evidence.
4. **Runtime pinning.** pandas 2.3 + numpy 2.5 emit a "generic timedelta unit … will raise an error" deprecation on
   ordinary Timedelta math, and there is no lock file. numpy is capped `<2.6` on both forward branches
   (`d5679d6`, `dcd5a4e`), all green. The bridges pin ref `0966172`, which still allows numpy <3.
5. **Cross-Sectional Independent Venue Replication v1** has failed on every run since 2026-09-25: Bybit
   returns HTTP 403 to GitHub-hosted runners. It's an environment problem, not code; it needs another
   data source or a self-hosted runner (user decision).
6. **VOL8 excursion ordering:** 37% of episodes are `SAME_BAR`, so ordering is unobservable.

## Evidence-rate reframe (2026-09-26, `docs/FIRST_PRINCIPLES_EVIDENCE_RATE_2026_09_26.md`)
- Combined 30-sleeve v3 portfolio: historical Sharpe 1.07 net, t 1.71 (not significant even
  in-sample), about 1,275 forward days to reach t = 2. Beta to basket −0.04, so hedging adds nothing.
- Breadth: 10 coins = 2.0 independent bets; +12 alts = 2.6; the 3 strategies = 1.5. Only
  non-crypto-factor assets add breadth (PAXG +0.35, TRX +0.33).
- `universal-trend-portfolio-forward-v1` pre-registered (start 2026-09-28, daily P&L, v3). Scheduling
  is in PR #115 (awaiting user merge).
- Policy: freeze per-trade and regime diagnostics and new trend variants on the same strategies and
  coins. New work must add independent breadth or shorten time-to-answer.

## Portfolio anatomy (`docs/PORTFOLIO_ANATOMY_2026_09_26.md`)
- Strengths: convex "smile" (+8% in the worst basket months, +17% in the best); long and short both pay
  under v3; +14% in 2025 and +18% in 2026 while the basket fell 35% and 24%.
- Weaknesses: the top 1% of trades (26) = 102% of net P&L; drawdowns −30% (346 days) and −25%; volatility 38%;
  ±1 sizing puts risk in DOGE/ENA/SUI (53% of P&L); VOL8 has a 15.6%/yr cost drag.
- Crypto funding drag only 0.6%/yr. **MEXC tradfi perp funding is 10–84%/yr |rate| and unmodeled**, so
  accounting v3.1 with funding must come before any cross-asset protocol.
- Liquid tradfi by rule (≥10M 24h, no leveraged/inverse/single stock): XAUT, SILVER, USOIL, SPX500,
  NAS100. Crypto + tradfi effective N 1.7 → 5.5.

## Decisions
- Workstream D (`universal-market-state-labels-v1`) was not built (post-hoc re-cut of v1 thresholds).
- Monitor runs pick one action; 2026-09-26 08:05Z run = `collect_evidence` only, no code change.
- 08:05Z (second pass): no new PR #113, bridge or target-workflow runs; monitor only.

## Next action candidates
- `ask_user`: merge PR #115 (schedules the daily trend portfolio watch).
- `implement`: canonical v3.1 = v3 + funding cash flows (prerequisite for cross-asset).
- `implement`: pre-register a cross-asset trend universe screened only on availability, liquidity and
  correlation to the crypto factor (target effective N ≥ 6), with the same frozen rules and daily-P&L protocol.
- `collect_evidence`: after the 08:25/08:40Z bridge runs, report the first post-start trades.
- `collect_evidence`: after 2026-09-27, report the v3 companion's first trades descriptively.
