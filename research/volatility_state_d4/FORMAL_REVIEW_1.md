# D4 volatility-state transfer: formal review 1

**Conclusion: NOT REPLICATED (directionally).** The frozen positive rank
relationship (higher `local_range_to_spread_15s` → higher subsequent
`volatility_expansion_ratio_60s`) did not replicate in the completed
prospective sample.

- Watch: `volatility-state-transfer-forward-v1`
- Gate: at least 5 independent clusters across at least 3 UTC dates, now
  satisfied with 11 clusters over 2026-09-25, 26 and 27. The protocol defines
  no p-value or binary threshold, and none is invented here.
- Bound snapshot: bridge run `36338618227`, collector ref
  `096617250b9164caafa7e1859aa00d480ea7cce2`, artifact ID `10937803160`,
  artifact digest `sha256:ad0bb3698587ef90c29a4356046b5c6126e60aa59b9cca01f099e81ea0e8297b`,
  aggregate SHA-256 in `FORMAL_REVIEW_1.json`, and the 11 cluster ids.

| Measure | Value |
| --- | --- |
| Cluster median Spearman (11) | −0.030, −0.085, −0.385, −0.157, −0.334, −0.113, −0.276, −0.191, −0.317, −0.083, −0.178 |
| Median of cluster medians | −0.178 |
| Median pooled within-symbol rank correlation | −0.177 |
| Positive-cluster fraction | 0 / 11 |
| Per-symbol median (ARB / ETH / FIL / NEAR / SOL / UNI) | −0.183 / −0.198 / −0.168 / −0.334 / −0.186 / −0.131 |

**Context (not pre-registered).** 11 of 11 negative gives a two-sided
sign-test probability of about 0.001 under a symmetric null.

**Scope and consequences.** This is state prediction, not strategy P&L. D4
must not be used as a strategy foundation. The reversed sign must not be
adopted post hoc as a hypothesis on this sample; any reuse needs a new,
independently specified version.

**Post-review policy.** Clusters accumulated after this snapshot are reported
as post-review accumulation only and cannot revise this conclusion. The
collector's own `formal_verdict = WITHHELD` is by design and stays as it is.
