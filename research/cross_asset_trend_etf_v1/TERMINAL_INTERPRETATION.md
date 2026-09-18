# Cross-asset trend ETF v1 — terminal D0 interpretation

Status: **FALSIFIED_D0_ALL_FAMILIES**.

The 12-month family failed multiple gates. The 6-month family is recorded as a near-survivor for research provenance only:

- primary mean: +29.1406 bps per non-overlapping portfolio observation
- stress mean: +17.5087 bps
- reversed primary mean: -54.1406 bps
- positive years: 7/10
- both 2008-2012 and 2013-2017 halves positive
- all 8 assets had positive cumulative contribution
- failed the frozen concentration gate: SPY was 32.6016% of positive contribution versus a 30% maximum

The failure is binding. The gate is not relaxed, the family ID is dead, and the 2018-2023 holdout is not opened for v1.

Development inspection showed SPY's average absolute risk weight was only about 12.05% while IEF's was about 27.33%; therefore an ex-post cap on SPY weight is not adopted as a rescue. A new, separately frozen research ID may test broader market diversification while preserving the v1 holdout boundary.
