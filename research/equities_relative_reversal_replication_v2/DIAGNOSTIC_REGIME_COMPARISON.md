# Diagnostic-only regime comparison — equity relative reversal replication v2

This analysis is post-result and **cannot** rescue, condition, retune or promote the dead replication family. It is descriptive only.

## May D0 versus June D3

| Metric | May D0 | June D3 |
|---|---:|---:|
| Sessions | 19 | 21 |
| Strategy net mean, 2 bps | +21.8554 | -2.3614 |
| Mean cross-sectional ranking spread | 348.5760 bps | 355.3799 bps |
| Mean cross-sectional dispersion | 130.5175 bps | 136.6243 bps |
| Mean SPY 10:00->14:00 move | +13.3287 bps | +0.8727 bps |
| Mean absolute SPY 10:00->14:00 move | 33.2484 bps | 45.6469 bps |

The failure is not explained by low cross-sectional dispersion: June had slightly larger dispersion and ranking spread.

Across all stock-day observations, the relation between the pre-14:00 relative-return metric and the subsequent 14:01->15:55 SPY-relative return weakened sharply:

- May: correlation = -0.2906; slope(post on pre) = -0.1516.
- June: correlation = -0.07995; slope(post on pre) = -0.02994.

Interpretation: the underlying cross-sectional mean-reversion tendency was materially stronger in May and largely collapsed in June rather than cleanly flipping to persistent momentum. This is regime-description only and is not an eligible conditioning rule for the dead family.

No new candidate is created from this diagnostic.
