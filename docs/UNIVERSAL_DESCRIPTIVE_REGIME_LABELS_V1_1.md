# Universal Descriptive Regime Labels v1.1

v1.1 is an inference-only hardening of \`universal-descriptive-regime-labels-v1\`. It does **not** change the five regime definitions, 8h data, DON8/EMA8/VOL8 strategy rules, 20 bps cost assumption, entry-time state attribution, three-bar persistence, 4-sigma shock window, or the 162-cell Cartesian grid.

## Why a new version was required

The first frozen v1 run was allowed to execute only after the v1 implementation freeze. Its artifact showed an impossible inferential pattern: one-trade and other very sparse cells could receive near-minimum p-values. The cause was an implementation error in the v1 bootstrap test. v1 computed bootstrap means from the empirical cell observations and compared the displacement of those bootstrap means around the observed mean with the absolute observed mean. That does not generate the test distribution under the zero-expectancy null.

The v1 descriptive labels, trades, cell counts, point estimates and percentile bootstrap intervals remain historical diagnostics. The v1 raw p-values, Benjamini-Hochberg q-values, Holm adjusted p-values and significance flags are explicitly invalidated and must not be used.

## Frozen v1.1 null test

For each predeclared joint cell with at least 20 completed trades:

1. Compute the observed pooled mean net return in bps.
2. Subtract that observed cell mean from every trade outcome in the cell. This creates a zero-mean empirical residual sample under the null.
3. Use the same global non-overlapping 30-day calendar-block draws across symbols, strategies and cells.
4. Compute the mean of the null-centered residuals in each valid bootstrap replicate.
5. The two-sided bootstrap p-value is the fraction of null-centered bootstrap means whose absolute value is at least as large as the absolute observed cell mean, with the standard +1 Monte Carlo correction.

Cells with fewer than 20 trades are still emitted with every descriptive metric, but they receive no inferential p-value and do not enter the multiplicity family. This minimum was already used by the repository as the small-cell warning threshold and is now made binding for v1.1 inference.

Within each strategy, all predeclared joint cells that meet the >=20-trade threshold and have a valid null-centered p-value enter the multiplicity family. Both Benjamini-Hochberg FDR and Holm FWER adjustments are reported at alpha 0.10.

## Statistical rationale

Bootstrap hypothesis testing should approximate the distribution under the null, rather than simply resampling the empirical distribution around the observed estimate. This is why v1.1 explicitly mean-centers each tested cell before resampling. The block draws remain joint across the market panel so nearby time dependence and simultaneous cross-symbol observations are not treated as independent.

Benjamini-Hochberg controls false discovery rate under its stated dependence conditions, while Holm provides family-wise error control. These cell-level corrections remain descriptive research diagnostics. Any later strategy-selection claim still requires a separately frozen decision protocol and stronger data-snooping controls such as White Reality Check or Hansen SPA.

## Authority boundary

v1.1 cannot authorize a regime filter, modify a candidate, establish profitable edge, authorize live trading, or authorize leverage. It is same-period historical diagnostics only.
