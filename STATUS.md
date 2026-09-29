# Current state dashboard

This file answers two questions: **what is running right now**, and **what is the
next scheduled decision**. It is a navigation layer only. It does not modify,
retune, reinterpret, or summarize-away any frozen evidence. When this file and a
frozen artifact disagree, the frozen artifact wins.

- Generated-by convention: this file is maintained by hand (or by a future
  automation) from the canonical artifacts listed inside it.
- Last reviewed: 2026-09-29 (after Prospective Formal Review 1); research-branch watches added 2026-09-29
- Repository commit at review: see `git log -1`

## Standing safety boundary (unchanged by this file)

```text
live_order_transmission_supported = false
profitable_edge_established       = false
verified_out_of_sample_evidence   = false
```

No promoted strategy exists. The live execution boundary remains closed.

## Primary decision in flight

| Item | Value |
|---|---|
| Watch | `evidence_v2_cross_strategy_session_forward_v1` |
| Strategy | DON8 — Donchian breakout, 8h interval, lookback 55, frozen 10-symbol MEXC universe |
| Prospective start | 2026-09-23 00:00:00 UTC |
| Review gate | 30 calendar days after the boundary (frozen in `config/evidence_v2_session_forward_watch_v1.json`) |
| Target review date | **2026-10-23 00:00:00 UTC** (not before) |
| Current status | `ACCUMULATING` — no early pass/fail is permitted |
| Forward automation | `evidence-v2-session-forward.yml` (scheduler; one run incrementally scores only timestamps after the boundary) |
| Canonical artifacts | `research/EVIDENCE_V2_SESSION_AUDIT_2026_09_22.md`, `research/VALIDATION_PRIORITY_FREEZE_2026_09_23.md`, `docs/RESEARCH_PROTOCOL.md` |

**Next scheduled decision:** no strategy decision of any kind is permitted
before 2026-10-23 00:00:00 UTC. When the review window matures, the locked
workflow (not this file) computes the verdict.

## Secondary prospective watches

| Watch | Family / focus | Prospective boundary | Review gate | Status |
|---|---|---|---|---|
| `SESSION_W1_ALIGNED_SHORT_ASIA_OPENING` | ENA session microstructure | 2026-09-22 15:39:58 UTC | ≥10 new independent batches and ≥5 new calendar days | **CLOSED — FALSIFIED** (Formal Review 1, 2026-09-29) |
| `SESSION_W2_ALIGNED_BTC_SHORT_ASIA_OPENING` | BTC-aligned session watch | 2026-09-22 15:39:58 UTC | ≥10 new independent batches and ≥5 new calendar days | **CLOSED — FALSIFIED** (Formal Review 1, 2026-09-29) |
| `SESSION_W3_CVD_LNY_WIDE_RANGE_BTC_AGAINST_V1` | CVD, London/New-York overlap | 2026-09-22 18:10:00 UTC | ≥20 new signals, ≥8 new batches, ≥7 new calendar days | `ACCUMULATING` (6/8 batches, 5/7 days as of 2026-09-29; partial numbers uninterpreted) |

Review counts are computed only by the frozen discovery-aggregation pipeline over
independent capture batches — never by hand and never from cumulative artifacts.

**Formal Review 1** (2026-09-29): W1 and W2 reached their frozen review gates
(10 batches / 6 days each) and were **falsified in every predeclared cell** —
net means −3.6 to −12.5 bps/trade, PF 0.06–0.31, at both 4 and 8 bps friction.
See `research/SESSION_WATCH_FORMAL_REVIEW_1_2026_09_29.md`. These IDs are
terminal: no retuning, re-siding, or re-phasing under the same IDs.

## Research-branch forward watches (daily, descriptive until review)

| Watch | Config (on `research/payoff-geometry-v1-1`) | Prospective start | Review | Status |
|---|---|---|---|---|
| `multi-premia-blend-v1` — equal-risk blend of trend, cross-sectional momentum, funding carry (70 coins) | `config/multi_premia_blend_v1.json` | 2026-09-29 00:00 UTC | 180 days | `ACCUMULATING` |
| `multi-premia-human-v1-forward` — same blend held as top-5 / top-10 coins at a daily 08:00 UTC check-in | `config/multi_premia_human_v1.json` (runs in the blend workflow) | 2026-09-29 00:00 UTC | 180 days | `ACCUMULATING` |
| `crypto-trend-core-v1` / `crypto-trend-core-voltarget-v1` — DON8+EMA8, 17 perps, inverse-vol, v3.1 | `config/crypto_trend_core_v1.json`, `config/crypto_trend_core_voltarget_v1.json` | 2026-09-29 00:00 UTC | 180-day sanity gate | `ACCUMULATING` |
| `universal-trend-portfolio-forward-v1` | `config/universal_trend_portfolio_forward_v1.json` | 2026-09-28 00:00 UTC | per config | `ACCUMULATING` |
| `universal-cross-asset-trend-forward-v1` / `-invvol-forward-v1` | `config/universal_cross_asset_trend_*forward_v1.json` | 2026-09-28 00:00 UTC | per config | `ACCUMULATING` |
| `universal-canonical-v3-forward-companion-v1` | `config/universal_canonical_v3_forward_companion_v1.json` | 2026-09-27 00:00 UTC | per config | `ACCUMULATING` |
| `new-listing-holdout-v1` (quarterly) | `config/new_listing_holdout_v1.json` | first batch 2027-03-12 | per batch | `WAITING` |

These are dispatched daily by `branch-forward-scheduler.yml` on `main`. Historical context (development and
one-shot holdouts, descriptive only) is in `research/payoff-geometry-v1-1:research/*/RESULT.md`; the strongest is the multi-premia blend
on 60 untouched coins (Sharpe 1.39, t 3.16). None of this is OOS evidence until the forward review dates.

## Research stop rule (active)

Until a predeclared review target is reached:

- no additional session filters from already-inspected datasets;
- no altered session boundaries, costs, sides, symbols, or strategy parameters;
- no leverage to rescue expectancy;
- no promotion based on a partial-period endpoint;
- no opening of sealed holdouts (`cross_market_etf_v1` August window remains
  sealed; see `research/cross_market_etf_v1/FINAL_WRAP_2026_09_21.md`).

Engineering, data-integrity, and reporting work remains allowed when it does not
touch strategy definitions.

## Closed / falsified lanes (do not reopen under these IDs)

| Lane | Research ID | Terminal state | Canonical record |
|---|---|---|---|
| ETF session families H1/H2/H3 | `cross_market_etf_v1` | `FALSIFIED_D0_ALL_FAMILIES`; August holdout sealed, uninspected | `research/cross_market_etf_v1/STATUS.md` |
| Futures price transfer + replications | `cross_market_futures_v1` | Falsified; order-flow lane blocked only on data entitlement | `research/cross_market_etf_v1/FINAL_WRAP_2026_09_21.md` |
| Discovery-v1 short-horizon strategy family | 332-epoch self-improvement sequence | Negative median gross expectancy before costs; rescue attempts exhausted | `research/self_improvement/CONTINUOUS_SELF_IMPROVEMENT_REPORT_V1.md` |

## Positive-but-not-yet-executable findings

| Finding | Evidence strength | Boundary |
|---|---|---|
| 60s volatility-expansion state prediction transfers across symbols (median Spearman +0.352, 6/6 symbols positive) | Transfer evidence from one new dependence cluster only — **not** six independent clusters | Not converted into positive executable expectancy; see self-improvement report |
| DON8 session-conditioned development record | Positive in every development year, positive fold majority, positive symbol breadth, both sides | Development-only; prospective DON8 watch above is the sole path to an OOS claim |

## Where things live

| Need | Go to |
|---|---|
| Current engineering health | Run `orderflow-multi-agent --output artifacts/multi_agent_report.json`; release-manager status must be `reviewable` |
| How a strategy may be promoted | `docs/PROMOTION_GATE.md`, `docs/RESEARCH_PROTOCOL.md` |
| Data-path and capture mechanics | `docs/MEXC_ORDERFLOW.md`, `docs/DATA_LINEAGE.md` |
| Full research lane index | `research/INDEX.md` |
| Documentation map | `docs/README.md` |
