# Session state (updated 2026-09-28 22:45Z)

## Branches
| Branch | Status |
| --- | --- |
| `fix/universal-existing-validation` | PR #113, draft, never merge; D4 formal review lives here |
| `research/payoff-geometry-v1-1` | all research below; CI green |
| `main` | `branch-forward-scheduler` dispatches branch watches (cron only fires from main); 8h bridge runs old watches from ref `0966172` |

## Forward watches (descriptive only; verdicts only at each review horizon)
| Watch | Start | Status 09-28 | Review |
| --- | --- | --- | --- |
| `multi-premia-blend-v1` (lead candidate) | 09-29 | PRE_START, 70 coins | 180 days |
| `multi-premia-human-v1-forward` (H5/H10/V_ALL, same workflow) | 09-29 | PRE_START; H5 book DASH/LSK/PHA/WLFI/ZEC | 180 days |
| `crypto-trend-core-v1`, `-voltarget-v1` | 09-29 | PRE_START | 180-day sanity gate |
| trend-portfolio, cross-asset, cross-asset-invvol | 09-28 | PRE_START (first full day scores 09-29) | per config |
| v3 forward companion | 09-27 | COLLECTING, 0 trades | per config |
| regime shadow / payoff-geometry / session-alignment (8h bridge) | 09-25 | green; only open episode DON8 LINK long | per config |
| `new-listing-holdout-v1` | quarterly | first batch 2027-03-12 | – |

- Monitor 2026-09-28 22:39Z: nothing new, all runs green.
- D4: formally reviewed, NOT_REPLICATED_DIRECTIONALLY (run 36338618227, SHA 8752bbec…). Automatic D4 collection stopped on main; any later cluster is post-review only.
- Monitor task `orderflow-research-monitor`: 01:30/09:30/17:30 local; reads all watches incl. `human_report.json`.

## Open issues
- Bybit venue replication (403 on GitHub runners) is superseded by `cross-sectional-okx-replication-v1` (green; D2 independent venue, descriptive transfer only).
- numpy capped `<2.6` on forward branches; bridges on ref `0966172` still allow numpy <3.
- Old 10-coin book is all long (crypto beta); short-side/v3 forward evidence will be slow. Effective N per cell is ~16–31.

## Evidence so far (one line each; details in `research/*/RESULT.md` and `docs/`)
- Trend core (DON8+EMA8, invvol, v3.1): pre-window holdout PASS (t 3.13); untouched 7 coins narrow FAIL (t 1.87); untouched 53 coins PASS (t 2.00); ETFs FAIL (rules are crypto-specific).
- Rejected refinements: regime switch, channel exit, funding overlay, chop-regime search, horizon ensemble, Markowitz. Vol target adopted as candidate.
- Multi-premia blend (trend + XS momentum + funding carry, equal risk): dev Sharpe 2.09 (t 4.48), robust to neighbours (1.6–2.2), costs (1.80 at 60 bps), crises.
- **Untouched-coins holdout (60 unused coins, run once): blend PASS, Sharpe 1.39, t 3.16, DD −11%, halves 1.41/1.37.** Carry alone fails (t 0.9).
- Human-constrained (≤5 coins, daily 08 UTC): dev H5 PASS (1.19, DD −31%) but holdout H5 0.60 (t 1.40). Concentration is the weak link; ≥10 coins keeps more (dev 1.40).
- Human execution: CET 09/15/21 timing costs little; market > limit; tuning grids are noise.
- Canonical accounting: v2 frozen; v3 (fixed quantity) and v3.1 (+funding) for new work.
- Trend bot (`trend_bot.py`, paper only): parked by user.

## Rules in force
- Automatic live order transmission disabled; no promotion, leverage, filters, live trading; outputs descriptive.
- Pre-register before evaluation; holdouts run once; never edit frozen configs/modules or canonical v2.
- Evidence-rate rule: no new per-trade/regime diagnostics or trend variants on the old 10 coins; new work adds breadth or shortens time-to-answer.

## Next action candidates
- `collect_evidence`: first forward days from the ~06:45–08:30 UTC runs on 09-29/09-30.
- `xs-low-vol-v1` declared: evaluate dev (70 coins) then confirmation (60 coins) once.
