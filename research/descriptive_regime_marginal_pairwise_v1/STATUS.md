# Descriptive Regime Marginal + Pairwise v1 Status

## Frozen protocol

- implementation freeze: \`2eb4450cae4627f1e10cc8e532842814380068e1\`
- binding commit: \`7695374fd16ebd0dc4ae14848235b9c8830cef80\`
- workflow activation: \`db54f101e52d8379a110e723bd8acfe5dd560319\`
- successful run: \`36174220487\`
- artifact digest: \`sha256:d468ea400f25bfd2bd02285e2ff7f0891d7f044d2c2e17b5f969f8101171b62b\`
- contrast contract hash: \`16d2cda054189809189ced0c2dda4bbbb6dbbd8d2ae7d67f2f679f19186aee30\`

The family is fixed at 14 marginal state-vs-complement contrasts and 78 pairwise joint-state-vs-complement contrasts per strategy. All five axes and every unordered axis pair are included symmetrically. No condition was selected from historical PnL.

## Multiplicity result

| Strategy | Eligible total | Eligible marginals | Eligible pairwise | Global BH discoveries | Global BY discoveries | Global Holm discoveries |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DON8 | 37 | 11 | 26 | 0 | 0 | 0 |
| EMA8 | 51 | 11 | 40 | 0 | 0 | 0 |
| VOL8 | 82 | 14 | 68 | 0 | 0 | 0 |

There is therefore **no historical anchor under the preregistered prospective rule**, which requires a global-Holm-adjusted p-value <= 0.10.

## Marginal state results

No marginal state survives global multiplicity adjustment for any strategy.

Some unadjusted contrasts are directionally large but unstable under full-family correction. Examples:

- DON8 \`trend_state=MIXED\`: state-minus-complement expectancy difference about -1,239 bps, raw block-bootstrap p about 0.0123, global Holm about 0.432, only 20% of comparable symbols show a positive state difference.
- DON8 \`trend_state=TREND\`: difference about +3,458 bps, raw p about 0.0640, global Holm 1.0; the very large point estimate is carried by only 27 group trades.
- EMA8 \`coupling_state=LOW\`: difference about +1,010 bps, raw p about 0.259, global Holm 1.0, although 90% of comparable symbols have a positive difference.
- VOL8 marginal effects are much smaller. The largest broadly observed directions include higher expectancy in low coupling and trend states, but none approaches corrected significance.

Shock and near-high drawdown states are sparse for DON8/EMA8 and fail the preregistered breadth floor in several marginal contrasts.

## Pairwise state results

The smallest raw p-values also fail tier and global correction.

Examples:
- DON8 \`MIXED trend + HIGH coupling\`: difference about -1,365 bps, raw p ~0.0080, tier BH ~0.134, global Holm ~0.296.
- EMA8 \`MIXED trend + MID coupling\`: difference about -1,089 bps, raw p ~0.0110, tier BH ~0.387, global Holm ~0.561.
- VOL8 \`HIGH volatility + NORMAL shock\`: difference about -125 bps, raw p ~0.0090, tier BH ~0.374, global Holm ~0.738.

These are descriptive patterns only and cannot be promoted into filters.

## Interpretation

The lower-dimensional analysis improves sample coverage substantially relative to the 162 five-way cells, but the apparent condition effects do not survive the preregistered 92-hypothesis family.

This weakens the case that the earlier five-way VOL8 adverse cells represent a simple, stable low-dimensional regime mechanism. They may reflect a higher-order conjunction, sampling variation, or correlated historical conditions. None of those explanations may be chosen as a strategy rule from this same-period evidence.

## Prospective consequence

The future-watch anchor rule was frozen before this artifact was inspected. It selects historical anchors only from global Holm discoveries. Because there are none, the prospective watch has zero selected replication anchors from this historical run.

All 92 contrasts remain frozen for prospective descriptive accumulation. No later historical reinterpretation can add an anchor to this v1 watch.
