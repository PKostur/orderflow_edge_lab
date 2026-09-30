# Research lane index

This is a navigational index of research lanes. It is descriptive only: it never
changes, retunes, reinterprets, or rescues any frozen lane. A lane's terminal
state is set by its own frozen artifacts, not by this index.

Status vocabulary: `OPEN — PROSPECTIVE` (frozen forward watch accumulating),
`CLOSED — FALSIFIED` (frozen gates failed; ID not reusable),
`CLOSED — NOT ESTABLISHED` (no persistent edge established; engineering
artifacts remain valid), `EXPLORATORY — DEVELOPMENT ONLY` (already-inspected
data; findings are development hypotheses, not OOS evidence).

For the single-page operational view (next decision dates, stop rules), see
[`STATUS.md`](../STATUS.md) at the repository root.

## Open — prospective validation (highest priority)

| Lane / watch | ID / config | Boundary | Canonical artifacts |
|---|---|---|---|
| DON8 cross-strategy session forward watch | `evidence_v2_cross_strategy_session_forward_v1` (`config/evidence_v2_session_forward_watch_v1.json`) | 2026-09-23 00:00:00 UTC; 30-day review (earliest 2026-10-23) | `research/VALIDATION_PRIORITY_FREEZE_2026_09_23.md`, `research/EVIDENCE_V2_SESSION_AUDIT_2026_09_22.md` |
| W3 — CVD London/New-York wide-range | `SESSION_W3_CVD_LNY_WIDE_RANGE_BTC_AGAINST` (frozen ID; earlier notes wrote a `_V1` suffix that the frozen config does not use) | 2026-09-22 18:10:00 UTC | `research/SESSION_PROSPECTIVE_STATUS_2026_09_22.md`, `config/session_watch_cvd_lny_v1.json` |

## Closed — falsified (IDs are terminal; no retuning under these IDs)

| Lane | Research ID | Terminal state | Canonical record |
|---|---|---|---|
| Session watch W1 (ENA short Asia opening) | `SESSION_W1_ALIGNED_SHORT_ASIA_OPENING` | `FALSIFIED` at Formal Review 1 (2026-09-29): all six predeclared cells negative after gates met | `SESSION_WATCH_FORMAL_REVIEW_1_2026_09_29.md` |
| Session watch W2 (BTC-aligned short Asia opening) | `SESSION_W2_ALIGNED_BTC_SHORT_ASIA_OPENING` | `FALSIFIED` at Formal Review 1 (2026-09-29): all six predeclared cells negative after gates met | `SESSION_WATCH_FORMAL_REVIEW_1_2026_09_29.md` |
| ETF session families (ORB continuation, VWAP vol reversion, gap reversion) | `cross_market_etf_v1` | `FALSIFIED_D0_ALL_FAMILIES`; August D3 holdout sealed and uninspected | `cross_market_etf_v1/STATUS.md`, `cross_market_etf_v1/D0_REPORT.md`, `cross_market_etf_v1/FINAL_WRAP_2026_09_21.md` |
| Futures one-minute price transfer + NQ/GC/CL replications | `cross_market_futures_v1` | Falsified; frozen futures **order-flow** protocol remains blocked only on event-data entitlement | `cross_market_etf_v1/FINAL_WRAP_2026_09_21.md` |
| OCC outlier run 51 (plus pre-period check) | `occ_r51` / `occ_r51_preperiod` | See frozen protocols and results | `outliers/occ_r51/PROTOCOL.md`, `outliers/occ_r51_preperiod/PROTOCOL.md`, `outlier_reports/occ_r51_results.md` |

## Closed — not established (methodology completed; no persistent edge)

| Lane | Scope | Canonical artifacts |
|---|---|---|
| Continuous self-improvement sequence (332 epochs: v1 pilot, v2 state refinement, v3 adversarial/horizon stress, cross-symbol screens) | Frozen discovery-v1 strategy family; state-prediction transfer; conditioning and stop-rescue attempts | `self_improvement/CONTINUOUS_SELF_IMPROVEMENT_REPORT_V1.md`, `self_improvement_v1_summary.json` |
| Volatility/liquidity state transfer into strategy conditioning | Positive state-prediction transfer (60s volatility expansion, median rho +0.352) did **not** convert into positive executable expectancy | `self_improvement/CONTINUOUS_SELF_IMPROVEMENT_REPORT_V1.md`, `config/state_threshold_freeze_v1.json` |

## Exploratory — development only (already-inspected data)

| Area | Contents |
|---|---|
| Session research | `SESSION_STRATEGY_EVIDENCE_2026_09_22.md`, `SESSION_DIAGNOSTIC_ENA_BTC_2026_09_22.md`, `MEXC_SESSION_STRATEGY_AUDIT_2026_09_22.md`, `CROSS_STRATEGY_SESSION_EVIDENCE_2026_09_22.md`, `config/trading_session_research_v1.json` |
| Cross-market regime atlas (plan) | `CROSS_MARKET_REGIME_ATLAS_PLAN_2026_09_23.md`, `config/cross_market_regime_atlas_v1.json` |
| Markov EV overlay + price diagnostics | `MARKOV_EV_OVERLAY_V1_INITIAL.md`, `MARKOV_PRICE_DIAGNOSTICS_V1_INITIAL.md`, `config/markov_ev_shadow_v1.json`, `config/markov_price_diagnostics_v1.json` |
| Discovery v2 sprints and calibration | `discovery_v2/` (protocol, candidate template, calibration status), `config/discovery_v2_*.json`, `config/dv2_payoff_meta_trend_accel_shadow_v1.json` |
| Methodology expansion / gamma exposure / sentiment & news context | `config/methodology_expansion_v1.json`, `config/gamma_exposure_trial_v1.json`, `config/sentiment_monitor_v1*.json`, `config/news_monitor_v1.json` |

## Frozen discovery / validation infrastructure (not lanes; shared machinery)

- `config/orderflow_discovery_v1.json` — frozen discovery thresholds (do not retune batch by batch).
- `config/regime_research_v1*.json` — pre-registered market-state feature families.
- `config/economics.json`, `config/candidates.json` — economics policy and frozen candidate registry.
- Protocol documents: `docs/RESEARCH_PROTOCOL.md`, `docs/PROMOTION_GATE.md`, `docs/REGIME_RESEARCH.md`.

## Review procedure

The procedural rules for the DON8 review record are pre-registered in
`DON8_FORMAL_REVIEW_CRITERIA_2026_10_23.md` (written 2026-09-29, before the window
closed). They add no numeric threshold and modify no frozen definition.

## Conventions

- New lanes must freeze a research ID and protocol **before** inspecting later evidence.
- Failed IDs are never reopened or retuned under the same ID.
- Cross-pair results are transfer evidence, not untouched OOS evidence for ENA-discovered conditions.
- This index is navigational; update it when a lane's terminal status changes in its own artifacts.
