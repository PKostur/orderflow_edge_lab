# Gold Macro/Trend v2 — Locked Internal Validation Result

## Evidence boundary

This is a **locked retrospective internal validation**, not future OOS.

Candidate was frozen first at commit `cb35e41df289e18ba2725350b462687fa5561c20`.

Validation protocol was then frozen in `config/gold_macro_trend_v2_validation.json` before the 2021-2023 candidate result was opened.

Canonical validation workflow run: `34892238678`

Validation source head: `f96c604683419090ea92ecf8e701e8ea58f6b97d`

Artifact: `gold-macro-trend-v2-internal-validation` (`10366884197`)

Artifact digest: `sha256:891bcc258fd51b276ab9459d084cdc7953a587dd099ba388895cc50a0d342a69`

All canonical source hashes matched the development source bundle exactly.

## Frozen candidate

`gold_silver_ratio_momentum_126_z1_hold21_v2`

- ratio: gold / silver close
- rolling z-score: 126 trading days
- active at |z| >= 1.0
- momentum direction: long gold at positive ratio extreme, short gold at negative ratio extreme
- hold: 21 trading bars
- completed close -> next open entry
- one active trade
- costs: 2 / 5 / 10 bps, primary 5 bps
- 126-calendar-day dependence folds

No parameter was changed after the development freeze.

## State validation

- eligible state observations: **251**
- scorable state folds: **9**
- median fold Spearman: **+0.236364**
- positive state folds: **7/9 = 77.78%**
- state gate: **PASS**

## Economic validation

- non-overlapping trades: **21**
- long trades: **12**
- short trades: **9**

At 5 bps primary round-trip cost:

- median fold net: **+166.3825 bps**
- median fold PF: **5.2559**
- positive economic folds: **7/9 = 77.78%**
- mean net: **+129.5581 bps/trade**
- reversed-direction mean net: **-139.5581 bps/trade**
- median-fold risk-adjusted score: **0.481047**
- equal-timing long-gold benchmark median-fold risk-adjusted score: **0.000000**
- equal-timing long-gold benchmark mean net: **+48.3236 bps/trade**

Cost stress:

- 2 bps median-fold net: **+169.3825 bps**
- 10 bps median-fold net: **+161.3825 bps**

Directional adversarial audit:

- long-subset mean net at 5 bps: **+159.3964 bps/trade**
- long-subset median net: **+166.3825 bps**
- long win rate: **66.67%**
- short-subset mean net at 5 bps: **+89.7736 bps/trade**
- short-subset median net: **+245.7147 bps**
- short win rate: **66.67%**

The development concern that performance might be only long-gold exposure is materially reduced by validation: the short sleeve is positive in the locked period and the candidate outperforms the equal-timing long-gold benchmark on both mean net and the frozen risk-adjusted comparison.

## Decision

The frozen candidate **passes the locked internal validation gate**.

This does **not** establish a verified persistent edge because:

1. development and validation are both retrospective;
2. the primary price source is continuous-front futures proxy data and can contain roll/basis effects;
3. the validation sample has only 21 non-overlapping trades;
4. no genuinely future-after-freeze outcome has completed yet.

The next admissible step is an **independent-instrument/source replication** with the candidate unchanged, followed only if successful by a future paper/shadow freeze. No leverage or live transmission is authorized.

## Claims

- locked internal validation: **PASS**
- independent-source replication: **not yet completed**
- verified future OOS: **false**
- profitable edge established: **false**
- leverage authorized: **false**
- live enabled: **false**
