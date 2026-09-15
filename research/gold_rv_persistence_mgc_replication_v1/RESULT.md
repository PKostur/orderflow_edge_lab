# Gold RV Persistence — MGC Independent Instrument Replication v1 Result

## Evidence identity

- candidate: `rv_persistence`
- parent locked XAUUSD result commit: `549d8f5928b26bd6ea2de55779047875fb463448`
- replication source: `domzack/mgc-ohlcv-data`
- source commit: `bf75ac4587e7995ceae64c3d696e076c37be12cc`
- instrument: CME Micro Gold Futures MGC
- provider: Databento-derived public dataset
- canonical workflow run: `34991221413`
- canonical scored head: `b46275219fefd6fdc0a6df76eb904c00acee6f56`
- artifact: `gold-rv-persistence-mgc-replication-v1` (`10406040754`)
- artifact digest: `sha256:8532755cde810cae1745129255dbb3178b6efc20c81791e26e5c719e730974d3`

This is cross-source and cross-instrument robustness evidence in overlapping 2023 historical time. It is not future OOS.

## Frozen candidate

No parent parameter was changed:

- prior 60-minute realized volatility;
- next 60-minute realized volatility;
- trailing 20-valid-observation same-clock normalization;
- New York weekday two-hour anchor grid;
- positive `pre_rv_ratio -> future_rv_ratio` relationship;
- no interpolation;
- one frozen candidate only.

Because the MGC source begins 2023-01-02, each clock slot accumulated its own 20 prior valid MGC observations before becoming scorable. No XAUUSD history or baseline was imported.

## Replication result

- input rows: **329,123**
- first input timestamp: **2023-01-02 23:00 UTC**
- last input timestamp: **2023-12-29 21:59 UTC**
- first scorable anchor after causal MGC baseline warmup: **2023-02-03 15:00 UTC**
- replication observations: **1,311**
- scorable New York dates with at least eight valid anchors: **45**
- median daily Spearman: **+0.380952**
- positive daily effects: **75.56%**
- one-sided 20,000-epoch sign-flip p-value: **0.000050**
- first-half median daily Spearman: **+0.380952** across 27 dates
- second-half median daily Spearman: **+0.408333** across 18 dates
- secondary future-range median daily Spearman: **+0.214286**

The state relationship therefore reproduces strongly in the available MGC observations.

## Clock-slot breadth

Seven clock slots reached the frozen minimum of 80 observations, and all seven were positive:

- 02:00 New York: n=110, Spearman **+0.422744**
- 04:00: n=158, **+0.655996**
- 06:00: n=138, **+0.563318**
- 08:00: n=185, **+0.172113**
- 10:00: n=219, **+0.388593**
- 12:00: n=209, **+0.634079**
- 14:00: n=145, **+0.549236**

The remaining slots did not meet the frozen observation floor:

- 00:00: n=36
- 16:00: n=26
- 20:00: n=16
- 22:00: n=69
- 18:00: no scorable observations under the exact-bar rule

## Data-quality / roll diagnostic

The largest exact one-minute absolute log return in the pinned 2023 MGC materialization was **0.007328** (about 0.73%). The five largest one-minute returns were reported without excluding any observation from the primary replication.

The largest-return dates were concentrated around known high-volatility macro times, and only one of the top-five dates was itself a scorable daily-effect date. No post-hoc roll deletion or return clipping was applied.

## Frozen gate decision

**FAIL: insufficient replication breadth.**

The relationship passes the frozen effect, sign, p-value, half-year, and secondary-range requirements, but fails two predeclared breadth gates:

1. only **45** scorable dates versus the required **160**;
2. only **7** eligible positive clock slots versus the required **8**.

The breadth gates are not weakened after inspection.

## Interpretation

This is positive independent instrument/source robustness evidence, but it does not satisfy the formal independent-replication gate because MGC one-minute trade-bar sparsity leaves too few dates with at least eight exact complete anchor windows.

Do not change the parent state definition, interpolate missing bars, reduce the daily anchor requirement, or lower the clock-slot breadth threshold to turn this result into a pass.

A further independent replication should use a more liquid Gold instrument or source while preserving the exact frozen state definition.

## Claims

- strong cross-source/instrument state robustness observed: **yes**
- frozen independent replication gate passed: **no**
- directional edge established: **no**
- executable edge established: **no**
- profitable edge established: **no**
- verified future OOS: **no**
- leverage authorized: **no**
- live enabled: **no**
