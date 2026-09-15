# Gold RV Persistence — HistData 2024 Later-Period Replication v2 Result

## Decision

**PASS: independent-source later-historical state replication complete.**

The exact frozen `rv_persistence` candidate passed every preregistered replication gate on calendar 2024 HistData XAUUSD without parameter retuning.

This is later historical OOS relative to the 2021–2022 development study and 2023 locked validation. It is not prospective future OOS and does not establish a trading edge.

## Evidence identity

- candidate: `rv_persistence`
- parent locked XAUUSD result commit: `549d8f5928b26bd6ea2de55779047875fb463448`
- prior HistData 2023 robustness result commit: `2c99caf24347a68efbba6a2fca0f6c9676124454`
- replication source: `blackmoon87/forex-histdata-m1`
- source commit: `208e67d7bda5cd5536df27531704e07fe4d54641`
- instrument: XAUUSD spot gold
- provider: HistData
- canonical workflow run: `35001509877`
- canonical scored head: `b9505b45aacfa9154f926ee05377728529a29f94`
- artifact: `gold-rv-persistence-histdata-2024-replication-v2` (`10409527770`)
- artifact digest: `sha256:6a54225dedcf66f933fbd94d6721247e38d8b94da276e97f9a3b0852e34e7bf1`

## Source verification

Pinned HistData Git LFS objects were verified before parsing:

- 2023 warmup archive: SHA256 `89a4f3f7ec2a52b29fbce8d4ca2ab650971817ae371b332f5fe471a488bcffc2`, 3,629,564 bytes;
- 2024 replication archive: SHA256 `6d47f5cb269e0c4f35c63c7532713aae7dcf98901f605458b00dd6a69e7105de`, 4,358,732 bytes.

HistData timestamps were treated as fixed EST UTC-05:00 without daylight-saving adjustment, converted to UTC, and then mapped to New York civil time for the frozen anchor grid.

Valid rows:

- 2023 warmup archive: 308,752;
- 2024 replication archive: 355,592;
- combined input: 664,344 rows.

No 2025 or later data entered the scorer.

## Frozen candidate

No parent parameter changed:

- prior 60-minute realized volatility;
- next 60-minute realized volatility;
- trailing 20-valid-observation same-clock normalization;
- weekday New York two-hour anchor grid at 00, 02, 04, 06, 08, 10, 12, 14, 16, 18, 20 and 22;
- positive `pre_rv_ratio -> future_rv_ratio` relationship;
- no interpolation;
- one frozen candidate only.

November–December 2023 was admitted only as causal same-source baseline warmup. Only calendar 2024 New York dates entered inference.

## Replication result

- raw anchor observations including warmup: **3,025**;
- 2024 replication observations: **2,591**;
- scorable New York dates with at least eight valid anchors: **256**;
- first scorable anchor: **2024-01-02 01:00 UTC**;
- last scorable anchor: **2024-12-31 19:00 UTC**;
- median daily primary Spearman: **+0.387121**;
- positive daily effects: **84.375%**;
- one-sided 20,000-epoch sign-flip p-value: **0.0000499975**;
- first-half median daily Spearman: **+0.390909** across 127 dates;
- second-half median daily Spearman: **+0.383333** across 129 dates;
- secondary future-range median daily Spearman: **+0.218182**;
- positive eligible clock slots: **11**.

## Clock-slot breadth

Every eligible slot was positive:

| New York hour | Observations | Spearman |
| --- | ---: | ---: |
| 00:00 | 254 | +0.603025 |
| 02:00 | 259 | +0.643295 |
| 04:00 | 258 | +0.623982 |
| 06:00 | 259 | +0.552494 |
| 08:00 | 259 | +0.373846 |
| 10:00 | 259 | +0.560082 |
| 12:00 | 259 | +0.666611 |
| 14:00 | 252 | +0.627235 |
| 16:00 | 242 | +0.593105 |
| 20:00 | 84 | +0.637258 |
| 22:00 | 206 | +0.537790 |

The 18:00 slot did not produce an eligible scored row under the unchanged exact-bar rule. No missing data were interpolated to rescue it.

## Frozen gate audit

All conditions passed:

- at least 160 scorable dates: **PASS, 256**;
- median daily Spearman at least +0.15: **PASS, +0.387121**;
- at least 58% positive daily effects: **PASS, 84.375%**;
- at least eight positive eligible clock slots: **PASS, 11**;
- first-half median effect positive: **PASS, +0.390909**;
- second-half median effect positive: **PASS, +0.383333**;
- secondary future-range effect positive: **PASS, +0.218182**;
- one-sided p no greater than 0.05: **PASS, 0.0000499975**.

## Data-quality diagnostic

The largest exact one-minute absolute log return in the combined materialization was `0.0101834` on 2024-05-03 13:30 UTC. That New York date remained positively scored at `+0.266667`.

No observation was removed, clipped, or reweighted after inspection.

## Relationship to earlier replication attempts

The MGC/Databento 2023 study remains a formal frozen-gate failure because it had only 45 qualifying dates and seven eligible clock slots despite a strong positive state effect.

The HistData 2023 study remains a formal frozen-gate failure because it had only 140 qualifying dates versus the required 160 despite passing every other gate.

Those failures are not retroactively upgraded, pooled, or threshold-adjusted. The 2024 result is a separate preregistered later-period replication that independently satisfies the unchanged gate.

## Claims boundary

Supported claim:

- the exact Gold intraday realized-volatility persistence state has now passed development, locked 2023 validation, and an independent-source later-historical 2024 replication.

Not supported:

- price direction;
- a valid entry or exit rule;
- executable expectancy after costs;
- profitable edge;
- prospective future OOS;
- leverage suitability;
- live readiness.

The previously rejected breakout-continuation and failed-breakout-reversal mechanisms remain rejected.

## Next permitted stage

Freeze a prospective state shadow before observing future data. The shadow must preserve the exact candidate and claim boundary. No economic, leverage, or live promotion is permitted from this state result alone.
