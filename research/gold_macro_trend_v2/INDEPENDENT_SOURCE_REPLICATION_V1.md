# Gold Ratio Momentum — Independent-Source Replication v1

## Evidence boundary

This is a **cross-source retrospective replication**, not future OOS.

Parent candidate: `gold_silver_ratio_momentum_126_z1_hold21_v2`.

Parent locked internal validation result: PASS at parent head `4e9930925c807573d4fb9c6458fe61ebb8a2d231`.

Independent source was pinned before scoring:

- repository: `simom1/XAUUSD-history`
- external commit: `bda79c6c5ce09a5b488d4cd2c20fcd19bdd2ed3a`
- XAUUSD: `Gold-Cash/XAUUSD/XAUUSD_D1_2010_2026.csv`
- XAGUSD: `Silver-Cash/XAGUSD/XAGUSD_D1.csv`
- semantics: MT5 cash daily bars from one independent public data family

Canonical workflow run: `34893088584`.

Canonical source head: `2925e68edc5b79f4b7e03fefc8ca04f8690f608e`.

Artifact: `gold-ratio-momentum-independent-replication-v1` (`10367107697`).

Artifact digest: `sha256:82486facaa1dfe0ab59e54b9b31b3a22c0e4d3f4389e03b3cf00c802a15c9e73`.

No candidate parameter was changed. Cash-feed admissibility was frozen before outcome: Monday-Friday common XAU/XAG dates, tick volume >1 on both assets, positive finite OHLC, duplicate dates keep last.

## Frozen candidate

- ratio: gold close / silver close
- z window: 126 admitted common trading days
- active: |z| >= 1.0
- direction: momentum; long gold at positive ratio extreme, short gold at negative ratio extreme
- hold: 21 admitted common trading bars
- signal on completed close
- next-open entry / later-open exit
- one active trade
- costs: 2 / 5 / 10 bps, primary 5 bps
- dependence clusters: 126 calendar days

## Data integrity

- admitted gold rows: **4,279**
- admitted silver rows: **5,009**
- common admitted rows: **4,267**
- common start: **2010-01-04**
- common end in pinned snapshot: **2026-07-22**

## 2010-2023 source-robustness block

State:

- eligible state observations: **1,345**
- scorable state folds: **39**
- median fold Spearman: **+0.190476**
- positive state folds: **69.23%**

Economics:

- non-overlapping trades: **101**
- median fold net @2 bps: **+107.65 bps**
- median fold net @5 bps: **+104.65 bps**
- median fold PF @5 bps: **4.4233**
- positive economic folds @5 bps: **66.67%**
- mean net @5 bps: **+51.06 bps/trade**
- median fold net @10 bps: **+99.65 bps**
- reversed-direction mean net @5 bps: **-61.06 bps/trade**

Directional audit:

- longs: **66 trades**, mean **+76.58 bps**, median **+45.15 bps**, win rate **57.58%**
- shorts: **35 trades**, mean **+2.93 bps**, median **+81.58 bps**, win rate **60.00%**

Benchmark control:

- candidate median-fold risk-adjusted score @5 bps: **0.149906**
- equal-timing long-gold benchmark risk-adjusted score @5 bps: **0.205772**
- candidate mean net @5 bps: **+51.06 bps/trade**
- equal-timing long-gold mean net @5 bps: **+45.56 bps/trade**

### Frozen gate decision

**FAIL.**

Every main state/economic/directional requirement passed except the predeclared requirement that the candidate beat equal-timing long-gold on median-fold risk-adjusted performance. The candidate was `0.149906` versus benchmark `0.205772`.

The gate is not relaxed after inspection.

## 2024-Jul-2026 historical extension

This is later historical evidence, but still retrospective because it predates the replication freeze.

- state median Spearman: **+0.198208**
- positive state folds: **66.67%**
- trades: **16**
- median fold net @5 bps: **+24.82 bps**
- mean net @5 bps: **+70.74 bps/trade**
- median fold PF @5 bps: **1.1706**
- mean net @10 bps: **+65.74 bps/trade**
- reversed mean @5 bps: **-80.74 bps/trade**

But the extension is directionally concentrated:

- longs: **8 trades**, mean **+361.29 bps/trade**, win rate **75%**
- shorts: **8 trades**, mean **-219.82 bps/trade**, win rate **25%**
- equal-timing long-gold benchmark mean @5 bps: **+285.55 bps/trade**
- candidate median-fold risk-adjusted score: **0.17645**
- long-gold benchmark risk-adjusted score: **1.29541**

The extension therefore does not repair the source-robustness failure; it strengthens the concern that later performance is largely exposure to a strong gold bull regime while the short sleeve breaks down.

## Decision

- locked internal validation: **previously PASS**
- independent-source replication: **FAIL**
- future shadow authorized by this protocol: **false**
- leverage tested: **false**
- verified future OOS: **false**
- profitable edge established: **false**
- live enabled: **false**

The exact 126/z1/21 candidate must not be retuned or leveraged to rescue this result. The useful surviving information is the positive gold/silver ratio state relationship; any next gold experiment must be a separately frozen mechanism designed to separate relative-state information from simple long-gold beta/regime exposure.
