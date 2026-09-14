# Gold Macro/Trend v2 — Candidate Freeze Before Internal Validation

## Evidence boundary

This freeze is created **after development evidence** and **before any 2021-2023 internal-validation strategy outcome is opened**.

Canonical development workflow run: `34891740737`

Canonical development source head: `d67c36dc364cbef315c85db9acd29b64fd82e346`

Development artifact: `gold-macro-trend-v2-development` (`10366559477`)

Artifact digest: `sha256:2440c9339c087fa6ae0e72482843968ce401618fc79ca61bd21016bfede02296`

Price-source semantics: Yahoo Finance `GC=F` / `SI=F` continuous-front futures proxies. Macro series are exact FRED series carried through immutable, commit-pinned GitHub mirrors. Any candidate surviving internal validation still requires independent spot/second-source replication before promotion.

## State-first development outcome

- predeclared cells: **138**
- state passes: **14**
- state-pass families: **10 gold/silver ratio state**, **4 macro-residual gold**
- economic prepasses: **1**
- full development passes: **1**
- 2021-2023 internal validation opened during development: **false**

## Frozen candidate

`gold_silver_ratio_momentum_126_z1_hold21_v2`

Exact definition:

- family: `gold_silver_ratio_state`
- ratio: `GC=F close / SI=F close`
- rolling z-score window: **126 trading days**
- activation: **|z| >= 1.0**
- mode: **gold_relative_momentum**
- direction: long gold when ratio z-score >= +1; short gold when ratio z-score <= -1
- hold: **21 trading bars**
- signal: completed daily close
- entry: next daily open
- exit: open after frozen hold
- no same-bar fill
- one active trade at a time
- round-trip cost schedule: **2 / 5 / 10 bps**, primary **5 bps**
- dependence cluster: **126 calendar days**

No parameter may be changed after this freeze.

## Development metrics

- eligible state events: **1,062**
- non-overlapping trades: **77**
- scorable state folds: **25**
- median fold Spearman: **+0.217475**
- positive state folds: **68.0%**
- median fold net at 2 bps: **+124.4473 bps**
- median fold net at 5 bps: **+121.4473 bps**
- median fold PF at 5 bps: **2.9013**
- positive economic folds at 5 bps: **65.625%**
- median fold net at 10 bps: **+116.4473 bps**
- mean net at 5 bps: **+35.7587 bps/trade**
- reversed-direction mean net at 5 bps: **-45.7587 bps/trade**
- strategy median-fold risk-adjusted score: **0.109929**
- equal-timing long-gold benchmark median-fold risk-adjusted score: **0.092787**
- frozen neighborhood supporters: **4**

Neighborhood support exists across longer holds, a higher z threshold, and a longer ratio window. No neighboring cell is promoted independently.

## Post-development adversarial concentration audit

This diagnostic was inspected only after the frozen development result existed and therefore cannot be treated as a predeclared development gate.

- long trades: **53 / 77**
- short trades: **24 / 77**
- long-subset mean net at 5 bps: **+59.6008 bps/trade**
- short-subset mean net at 5 bps: **-16.8925 bps/trade**
- equal-timing long-gold benchmark mean net at 5 bps: **+43.1722 bps/trade**
- candidate mean net at 5 bps: **+35.7587 bps/trade**

This creates a material risk that development performance partly reflects long-gold exposure rather than a symmetric relative-value timing edge.

## Validation policy frozen now

The locked 2021-2023 internal period may be opened only against this exact candidate. No retuning, family substitution, threshold selection or best-cell comparison is permitted.

Validation must report, without suppressing failures:

1. the same state-before-PnL metrics;
2. 2/5/10 bps economics;
3. reversed-direction control;
4. equal-timing long-gold benchmark;
5. long-vs-short contribution separately;
6. calendar-fold dependence metrics;
7. trade count and directional concentration.

Primary validation gate:

- at least **5 scorable 126-day state folds**;
- median state Spearman > 0;
- >= **60%** positive state folds;
- at least **18** non-overlapping trades;
- primary 5-bps median-fold net > 0;
- primary median-fold PF > 1;
- >= **60%** positive economic folds;
- 10-bps median-fold net >= 0;
- original mean net > reversed-direction mean net;
- original median-fold risk-adjusted score > equal-timing long-gold benchmark;
- report short-side results explicitly; a negative short-side result is an adversarial warning even if the aggregate gate passes.

Internal validation remains retrospective and **cannot establish verified future OOS**. A pass would authorize only an independent-source replication / future-shadow design, not leverage or live trading.

## Claims at freeze

- verified OOS: **false**
- profitable edge established: **false**
- live enabled: **false**
