# Current state dashboard

This file answers two questions: **what is running right now**, and **what is the
next scheduled decision**. It is a navigation layer only. It does not modify,
retune, reinterpret, or summarize-away any frozen evidence. When this file and a
frozen artifact disagree, the frozen artifact wins.

- Generated-by convention: this file is maintained by hand (or by a future
  automation) from the canonical artifacts listed inside it.
- Last reviewed: 2026-09-29 (after Prospective Formal Review 1; wait-window observability added)
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
| `SESSION_W3_CVD_LNY_WIDE_RANGE_BTC_AGAINST` | CVD, London/New-York overlap | 2026-09-22 18:10:00 UTC | ≥20 new signals, ≥8 new batches, ≥7 new calendar days | `ACCUMULATING` (6/8 batches, 5/7 days as of 2026-09-29; partial numbers uninterpreted) |

Watch IDs are quoted exactly as the frozen configs define them. Earlier notes wrote W3
with a `_V1` suffix; the frozen ID in `config/session_development_watch_v1.json` has no
suffix, and tooling now reports the frozen ID verbatim.

Review counts are computed only by the frozen discovery-aggregation pipeline over
independent capture batches — never by hand and never from cumulative artifacts.
W3, unlike DON8, does carry numeric thresholds: `config/session_watch_cvd_lny_v1.json`
`review_rule` requires profit factor above 1.0, a positive batch fraction above 0.5, positive
cumulative net at 4 bps and positive expected value, with data-volume gates of 20 signals,
8 independent batches and 7 calendar days.

**Formal Review 1** (2026-09-29): W1 and W2 reached their frozen review gates
(10 batches / 6 days each) and were **falsified in every predeclared cell** —
net means −3.6 to −12.5 bps/trade, PF 0.06–0.31, at both 4 and 8 bps friction.
See `research/SESSION_WATCH_FORMAL_REVIEW_1_2026_09_29.md`. These IDs are
terminal: no retuning, re-siding, or re-phasing under the same IDs.

## Forward watches (generated)

<!-- BEGIN GENERATED: forward-watches (scripts/generate_status.py) -->

_Generated 2026-10-06T06:32:32Z from `config/prospective_review_clock_v1.json` and the latest dashboard snapshot. Do not edit by hand._

| Watch | Config | Start | Review gate | Earliest review | Status | Scored days |
|---|---|---|---|---|---|---|
| `evidence_v2_cross_strategy_session_forward_v1` | – | 2026-09-23 | 30 calendar days | **2026-10-23** | `see workflow` | – |
| `fast-gates-v1` | `config/fast_gates_v1.json` | 2026-10-05 | 60 calendar days | **2026-12-04** | `COLLECTING` | 0 |
| `universal-canonical-v3-forward-companion-v1` | `config/universal_canonical_v3_forward_companion_v1.json` | 2026-09-27 | 90 calendar days | **2026-12-26** | `COLLECTING` | 8 |
| `crypto-trend-core-v1` | `config/crypto_trend_core_v1.json` | 2026-09-29 | 180 calendar days | **2027-03-28** | `COLLECTING` | 6 |
| `crypto-trend-core-voltarget-v1` | `config/crypto_trend_core_voltarget_v1.json` | 2026-09-29 | 180 calendar days | **2027-03-28** | `COLLECTING` | 6 |
| `multi-premia-blend-v1` | `config/multi_premia_blend_v1.json` | 2026-09-29 | 180 calendar days | **2027-03-28** | `COLLECTING` | 6 |
| `multi-premia-human-v1-forward` | `config/multi_premia_blend_v1.json` | 2026-09-29 | 180 calendar days | **2027-03-28** | `COLLECTING` | 6 |
| `zoo-mirror-forward-v1` | `config/zoo_mirror_forward_v1.json` | 2026-10-03 | 180 calendar days | **2027-04-01** | `COLLECTING` | 2 |
| `paper-account-blend-v1` | `config/paper_account_blend_v1.json` | 2026-10-05 | 180 calendar days | **2027-04-03** | `COLLECTING` | 0 |
| `news-sentiment-v1-forward` | `config/news_sentiment_v1.json` | 2026-11-01 | 180 calendar days | **2027-04-30** | `PRE_START` | 0 |
| `universal-cross-asset-trend-forward-v1` | `config/universal_cross_asset_trend_forward_v1.json` | 2026-09-28 | 365 calendar days | **2027-09-28** | `COLLECTING` | 7 |
| `universal-cross-asset-trend-invvol-forward-v1` | `config/universal_cross_asset_trend_invvol_forward_v1.json` | 2026-09-28 | 365 calendar days | **2027-09-28** | `COLLECTING` | 7 |
| `universal-trend-portfolio-forward-v1` | `config/universal_trend_portfolio_forward_v1.json` | 2026-09-28 | 365 calendar days | **2027-09-28** | `COLLECTING` | 7 |
| `prop-paper-career-v1` | `config/prop_paper_forward_v1.json` | 2026-10-05 | 365 calendar days | **2027-10-05** | `PRE_START` | 0 |

No verdict of any kind before a watch's earliest review date; the frozen workflow computes it.

<!-- END GENERATED: forward-watches -->

## Wait-window observability (reporting only)

No tool below counts evidence, computes a verdict, or promotes anything. Review counts
remain the exclusive output of the frozen discovery-aggregation pipeline.

| Tool | What it answers | Cadence |
|---|---|---|
| `orderflow review-clock` | How much calendar time each watch has accumulated, and when a calendar gate matures | daily (`prospective-review-clock-v1.yml`) |
| `orderflow capture-health` | Is the capture stream still alive? `--fail-on-stoppage` exits 3 when it is not | daily, alarms (`capture-health-watch-v1.yml`) |
| `orderflow review-packet` | Hash-pinned review skeleton with empty verdict cells for a watch that has met its gate | on demand, at review time |
| `orderflow artifact-coverage` | Would the frozen pipeline still find every input it needs? Declared in `config/evidence_retention_requirements_v1.json` | daily, in the digest |
| `orderflow ops-digest` | One daily artifact combining clock, captures, ledger batch count, and coverage | daily (`wait-window-ops-digest-v1.yml`) |

## Validation tooling (analysis and contracts)

Added 2026-09-30. These tools analyse an already-frozen report or check a contract. They add no
threshold to an open watch, change no frozen definition, and label every number they produce on an
already-open watch as `post_hoc_descriptive`. See `docs/VALIDATION_TOOLING.md`.

| Tool | What it answers |
|---|---|
| `orderflow robustness` | Cluster bootstrap interval, minimum detectable effect at the frozen gate, concentration, friction sensitivity, control arms and negative controls for a frozen forward report. |
| `orderflow research-hygiene` | Pre-registration audit, frozen-definition hash check (`config/frozen_manifest_v1.json`), workflow-to-artifact contract, inspection registry integrity. |
| `orderflow discovery-screen` | Would a candidate clear the declared round-trip cost, and does the declared cost match measured friction? |
| `orderflow orthogonality` | Redundancy clusters, incremental information against existing regime variables, leave-one-out stability. |

Pre-registration status of the frozen watches, reported mechanically by the hygiene audit:

| Watch | Decision rule | Trial family |
|---|---|---|
| `WATCH_CVD_LNY_WIDE_RANGE_BTC_AGAINST_V1` (W3) | Numeric thresholds in `review_rule` (profit factor above 1.0, positive batch fraction above 0.5, positive cumulative net at 4 bps, positive EV) | not declared |
| `evidence_v2_cross_strategy_session_forward_v1` (DON8) | Eleven metrics declared, **no numeric threshold for any** | not declared |
| `session_development_watch_v1` (W1/W2/W3 gates) | Data-volume gates only (batches, days, signals) | not declared |

The two gaps cannot be repaired retroactively: adding a numeric rule after the window opened is
post-hoc by definition. They are recorded as acknowledged gaps in
`config/preregistration_registry_v1.json`, and the contract that future watches must satisfy
(full `decision_rule` block, `trial_family`, and a `design` block with dependence cluster and design
effect) is stated there.

**Next review to be prepared:** W3 is expected to reach its frozen gate before DON8. The
procedure for assembling a review from the frozen counting report is the same in both
cases — see `docs/DON8_REVIEW_RUNBOOK.md` (the DON8 case) and the packet command. The
pre-registered procedural rules for the DON8 review record are frozen in
`research/DON8_FORMAL_REVIEW_CRITERIA_2026_10_23.md`, written while the window was still
open. Those rules add no numeric threshold and change no frozen definition; they exist so
the review cannot choose its own procedure after seeing the outcome.

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

## Closed / not established lanes

| Lane | Research ID | Terminal state | Canonical record |
|---|---|---|---|
| Volatility-state D4 transfer replication | `volatility-state-transfer-forward-v1` | **NOT REPLICATED directionally** at Formal Review 1: 11/11 prospective clusters negative, median cluster Spearman −0.178. The collector's formal verdict remains WITHHELD by design; no reversed-sign rescue is permitted on the same sample. | `research/volatility_state_d4/FORMAL_REVIEW_1.md`, `research/volatility_state_d4/STATUS.md` |

## Positive-but-not-yet-executable findings

| Finding | Evidence strength | Boundary |
|---|---|---|
| Historical 60s volatility-expansion state prediction transferred across symbols (median Spearman +0.352, 6/6 symbols positive) | Development/transfer evidence only; the later frozen D4 prospective replication was negative in all 11 clusters | Not an executable edge and not a strategy foundation; see `research/volatility_state_d4/FORMAL_REVIEW_1.md` |
| DON8 session-conditioned development record | Positive in every development year, positive fold majority, positive symbol breadth, both sides | Development-only; prospective DON8 watch above is the sole path to an OOS claim |

## Where things live

| Need | Go to |
|---|---|
| Current engineering health | Run `orderflow-multi-agent --output artifacts/multi_agent_report.json`; release-manager status must be `reviewable` |
| How a strategy may be promoted | `docs/PROMOTION_GATE.md`, `docs/RESEARCH_PROTOCOL.md` |
| Data-path and capture mechanics | `docs/MEXC_ORDERFLOW.md`, `docs/DATA_LINEAGE.md` |
| Full research lane index | `research/INDEX.md` |
| Documentation map | `docs/README.md` |
