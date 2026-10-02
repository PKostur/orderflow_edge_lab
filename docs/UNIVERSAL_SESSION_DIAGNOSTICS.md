# Universal session diagnostics

## Boundary

This note records descriptive historical diagnostics for the already frozen DON8, EMA8, and VOL8 strategy definitions. It does not change strategy targets, select parameters, authorize a session filter, promote a candidate, establish profitable edge, or authorize leverage or live trading.

The evaluation used the immutable MEXC 8h snapshot requested by `config/universal_existing_strategy_backtests_v1.json`, from 2024-01-01 through 2026-09-12, across BTC, ETH, SOL, XRP, DOGE, BNB, ADA, LINK, SUI, and ENA. ENA retains its declared leading listing gap. The frozen validation passed compatibility and canonical ledger reconciliation.

Evaluation workflow run: `35917302401` at commit `7d5c36a4e7156bd880fe47d1c2766ce9a8227139`.

Artifact digest: `sha256:e6772874dbedf2e17f0e76910bc7232d6aa130ef6c6beaf0f2cf13452bc60a62`.

## Fixed diagnostic protocol

Session definitions reuse `session_metrics.py` and are daylight-saving aware: Asia is 09:00 to 18:00 Tokyo time, London is 08:00 to 17:00 London time, and New York is 08:00 to 17:00 New York time. Membership is multilabel, so overlapping sessions are not forced into one bucket.

A trade is assigned from its canonical entry timestamp. Cumulative session return is calculated per symbol as the product of canonical net trade factors. The cross-symbol table reports the median of those per-symbol cumulative returns rather than compounding unrelated symbols into a synthetic portfolio.

Correct direction is defined before inspection as `gross_bps > 0`. Distance travelled after a correct direction is the canonical unweighted MFE over the complete trade episode. Alignment factors use only information completed before entry: the immediately preceding own bar, the previous three own bars, and the most recent completed BTC bar.

## 20 bps session diagnostics

| Strategy | Session membership | Trades | Median symbol cumulative return | Positive symbol fraction | Pooled expectancy, bps | Pooled win rate | Mean MFE after correct direction, bps |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DON8 | ASIA | 157 | 5.2% | 50% | 567.6 | 38.9% | 6847.2 |
| DON8 | LONDON | 85 | 32.0% | 60% | 1136.4 | 38.8% | 9069.5 |
| DON8 | NEW_YORK | 73 | 17.6% | 60% | 535.9 | 35.6% | 6893.9 |
| EMA8 | ASIA | 231 | -9.5% | 40% | 274.3 | 25.1% | 6732.1 |
| EMA8 | LONDON | 140 | 66.1% | 70% | 872.0 | 32.1% | 7858.5 |
| EMA8 | NEW_YORK | 111 | 23.3% | 60% | 363.7 | 31.5% | 5240.8 |
| VOL8 | ASIA | 1306 | 2.3% | 50% | 34.2 | 35.1% | 1199.7 |
| VOL8 | LONDON | 868 | 34.1% | 70% | 83.4 | 33.9% | 1483.7 |
| VOL8 | NEW_YORK | 789 | -6.7% | 40% | 36.1 | 33.6% | 1276.9 |

The session ordering is stable from 12 through 20 bps in pooled expectancy: London is descriptively higher than the other named session memberships for all three strategies. This does not establish a London trading filter. The 8h timestamp grid creates coarse entry-time attribution and session overlap, and same-period cross-symbol agreement is not future out-of-sample evidence.

Exclusive-regime diagnostics show that the simple London membership result is partly concentrated in overlap buckets. For example, the Asia plus London overlap has positive median per-symbol cumulative return at 20 bps for all three strategies, while several non-overlap and London plus New York cells are weaker. This is another reason not to turn the membership result directly into a trading rule.

## Alignment diagnostics at 20 bps

The table below compares aligned versus against observations within each symbol and then summarizes the symbol-level differences. A positive expectancy difference means the aligned bucket had higher historical expectancy for that symbol.

| Strategy | Factor | Symbols with both states | Median aligned minus against expectancy, bps | Symbols with higher aligned expectancy | Median cumulative-return difference | Symbols with higher aligned cumulative return | Median correct-direction MFE difference, bps |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DON8 | BTC prior bar | 7 | 1783.7 | 86% | 77.0 pp | 86% | 2849.3 |
| EMA8 | BTC prior bar | 10 | 580.4 | 80% | 58.2 pp | 70% | 1825.8 |
| EMA8 | own prior bar | 10 | 340.0 | 70% | 49.3 pp | 80% | 1437.7 |
| EMA8 | own prior 3 bars | 10 | 427.6 | 90% | 48.4 pp | 60% | 1586.5 |
| VOL8 | BTC prior bar | 10 | 72.9 | 70% | 17.5 pp | 80% | 346.9 |
| VOL8 | own prior bar | 10 | 60.6 | 70% | -2.1 pp | 50% | 350.9 |
| VOL8 | own prior 3 bars | 10 | 84.0 | 80% | 46.3 pp | 80% | 419.5 |

DON8's own prior-bar and prior-three-bar direction are mechanically aligned for every recorded episode under this frozen breakout definition, so they provide no separating information. BTC prior-bar alignment is the useful observed split for DON8. EMA8 shows descriptive separation in all three causal alignment factors. VOL8 shows little pooled BTC expectancy separation, while its own three-bar alignment has a clearer historical split.

## Interpretation

These diagnostics identify historical state dependence worth freezing for a prospective test, not a new optimized strategy. The next valid research step is to define any session or alignment hypotheses without further threshold tuning and test them prospectively or on a genuinely untouched future period. Until then the frozen strategy definitions remain unchanged and no session condition is authorized for live use.
