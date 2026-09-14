# Strategy Discovery v4.3 — Funding Continuation Conclusion

Canonical workflow run: `34890636747`

Canonical source head: `4d4440dcd17635b26b38f87aeea93bd457320c09`

Artifact: `strategy-discovery-v4-3-funding-continuation` (`10366637501`)

Artifact digest: `sha256:b42f3150ead07de484480d88d0e5ab899c62fde6c0aaf5cd70f1e76157021f83`

## Evidence class

Later-period retrospective diagnostic only, covering `2026-08-01T00:00:00Z` through `2026-09-14T19:00:00Z`. It is not future OOS.

The hypothesis and all parameters were frozen before this later-period diagnostic was opened:

- same 17-symbol v4.2 expansion panel
- BTC hedge only
- top/bottom k = 3
- funding lookbacks = 3 and 5 settlements
- direction = long highest funding / short lowest funding
- hold = 72h
- causal 192h BTC beta hedge
- costs = 12/16/20 bps
- realized funding cashflows included
- no leverage

## 3-settlement cell

- 475 state observations
- 5 weekly dependence clusters
- median state Spearman: **-0.01178**
- positive state clusters: **40%**
- completed portfolios: 10
- primary 16 bps median-cluster net: **-66.4566 bps**
- primary median-cluster PF: **0.0000**
- positive economic clusters: **40%**
- mean primary net: **-125.6587 bps/portfolio**
- opposite carry-direction control mean: **+93.6587 bps/portfolio**
- diagnostic support: **FAIL**

## 5-settlement cell

- 475 state observations
- 5 weekly dependence clusters
- median state Spearman: **+0.20602**
- positive state clusters: **60%**
- completed portfolios: 10
- primary 16 bps median-cluster net: **-112.8749 bps**
- primary median-cluster PF: **0.3297**
- positive economic clusters: **20%**
- mean primary net: **-56.2035 bps/portfolio**
- opposite carry-direction control mean: **+24.2035 bps/portfolio**
- diagnostic support: **FAIL**

## Decision

The apparent reversed-direction opportunity seen in v4.2 does **not** survive the later temporal diagnostic. The 3-settlement state relationship itself changes sign; the 5-settlement state relationship is only marginally supportive while executable economics remain strongly negative.

Therefore:

1. Do **not** launch the planned v4.3 future shadow.
2. Do **not** test leverage.
3. Do **not** flip back again to the carry direction on this same observed period; that would be recursive outcome chasing.
4. Retain funding dispersion only as a market-state/context feature for future unrelated strategies.
5. Close the direct funding-spread directional strategy lineage unless a genuinely new mechanism with independent rationale is proposed.

## Claims

- verified OOS: **false**
- profitable edge established: **false**
- live enabled: **false**
