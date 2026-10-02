# Universal Descriptive Regime Marginal + Pairwise v1

This protocol reduces the sparsity of the frozen 162-way regime grid **without selecting favorable historical combinations**. It inherits the five causal labels from \`universal-descriptive-regime-labels-v1\` unchanged and evaluates all lower-dimensional states symmetrically.

It is same-period historical research only. It cannot alter DON8, EMA8, VOL8, the prospective session/alignment watch, positions, execution rules, or any deployment gate.

## Why this layer exists

The corrected v1.1 regime report showed that the full five-way Cartesian grid is sparse for slower strategies. Only 1 DON8 and 2 EMA8 five-way cells met the >=20-trade inferential floor.

The response is not to pick promising-looking historical cells. Instead, this protocol lowers dimensionality mechanically:

- all 14 marginal states are primary;
- all 10 unordered pairs of the five axes are secondary;
- every state combination inside every pair is emitted;
- no axis or pair is selected using strategy PnL.

This gives 14 marginal contrasts and 78 pairwise joint-state contrasts, or 92 fixed contrasts per strategy.

The design follows the hierarchy principle used in interaction modeling: interaction structure should be accompanied by its lower-order terms rather than appearing in isolation. See Bien, Taylor & Tibshirani, *A Lasso for Hierarchical Interactions*, Annals of Statistics 41(3), 2013, arXiv:1205.5050.

## Contrast semantics

Every contrast asks whether the unchanged strategy behaved differently inside a state than outside that state:

\`mean net_bps in state - mean net_bps in complement\`

For a marginal contrast, the pool contains all trades with a known value on that axis and the complement is the union of the other states of that axis.

For a pairwise contrast, the pool contains all trades with known labels on both axes and the complement is every other state combination of those same two axes.

This is a **condition contrast**, not a new trading rule and not a portfolio return.

Each contrast reports the group and complement sample sizes, expectancy, win rate, correct-direction rate, MFE, MAE, symbol breadth, 30-day block breadth, and per-symbol expectancy differences where both sides exist.

## Eligibility

A contrast receives inferential output only when all of these preregistered conditions hold:

- >=20 group trades;
- >=20 complement trades;
- >=3 group symbols;
- >=3 distinct group 30-day blocks;
- >=3 distinct complement 30-day blocks;
- >=1000 valid bootstrap replicates.

Ineligible contrasts remain present with descriptive metrics. They are not silently dropped.

## Null-centered shared block bootstrap

All trades are assigned to non-overlapping 30-day calendar blocks from one common origin. The same 3,000 bootstrap block draws are reused across symbols, strategies, marginal contrasts, and pairwise contrasts.

For a tested state-vs-complement contrast, the null hypothesis is equal mean net return. Group and complement outcomes are separately centered to their common pooled mean before resampling. The bootstrap therefore approximates the distribution under the equality null instead of resampling the observed difference as if it were the null.

The repository keeps a fixed-block convention for consistency with Payoff Geometry v1. Politis & Romano (1994), *The Stationary Bootstrap*, motivates dependence-aware resampling but this implementation does not claim to be the stationary-bootstrap algorithm.

## Multiplicity

The hypotheses are strongly dependent because state groups overlap. Three corrections are therefore shown:

- Benjamini-Hochberg FDR, as the conventional power-oriented FDR reference;
- Benjamini-Yekutieli FDR, which was developed for FDR control under general dependency;
- Holm FWER, the conservative family-wise reference.

Corrections are computed both within tier and globally across every eligible one of the 92 preregistered contrasts within each strategy. The protocol names **global Holm FWER** as its conservative reference and global BY as the dependency-robust FDR reference.

References:
- Benjamini & Hochberg (1995), DOI 10.1111/j.2517-6161.1995.tb02031.x
- Benjamini & Yekutieli (2001), DOI 10.1214/aos/1013699998
- Holm (1979), *A Simple Sequentially Rejective Multiple Test Procedure*
- Politis & Romano (1994), DOI 10.1080/01621459.1994.10476870

## Crypto coupling rationale

Market coupling remains a descriptive axis rather than a trading premise. Bouri, Benbachir & El Alaoui (2025), DOI 10.1016/j.physa.2025.130587, report condition-dependent cross-correlations among major cryptocurrencies. Other recent crypto work likewise finds dynamic cross-correlation structure. That supports testing coupling as a market-state descriptor, not treating a historical coupling split as a validated edge.

## Authority boundary

No marginal or pairwise discovery can directly become a trade filter. Any condition proposed for decision-making after this report must receive a new candidate/protocol frozen before later untouched evidence is observed.
