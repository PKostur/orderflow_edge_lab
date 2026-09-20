# FX market-state v1 — orthogonality / redundancy freeze

Frozen before inspecting any joint H2/H3 overlap or conditional result.

Purpose: determine whether the two historical state survivors are largely redundant before any future strategy conditioning.

## Common eligibility

Use only frozen 15-minute grid timestamps where **both** FXS-H2 and FXS-H3 inputs and 15-minute targets are exactly available. No interpolation.

Evaluate D0 (July 6-31) and D3 historical holdout (August 3-28) separately.

## Binary states

- H2 = 1 when the already-frozen current-volatility / prior-60m-baseline ratio is >= 1.50.
- H3 = 1 when the already-frozen absolute 20-close log-price z-score is >= 2.0.
- No threshold changes are permitted.

## Redundancy statistics

For each window report:

- H2 trigger count/rate;
- H3 trigger count/rate;
- joint H2&H3 count;
- P(H3|H2) and P(H2|H3);
- Jaccard = joint / union;
- phi correlation of the two binary states.

Predeclared descriptive high-redundancy flag: **abs(phi) >= 0.50 OR Jaccard >= 0.50**.

This flag is a simplification screen, not statistical proof.

## Conditional state checks

H2 volatility persistence:
- within H3=0 common-eligible timestamps, compute the frozen H2 triggered future-volatility ratio minus the H2 control mean in that same H3=0 stratum;
- repeat within H3=1;
- positive in both strata is descriptive evidence that H2 is not merely a proxy for H3 displacement.

H3 reversion:
- among H3 triggers, report the frozen signed reversion target separately for H2=0 and H2=1;
- positive mean in H2=0 demonstrates that H3 has state information outside H2 expansion episodes;
- no minimum cell count will be invented after results. Small cells must be reported as a limitation.

## Decision rule

- Do **not** combine H2 and H3 into a trading rule in this version.
- If high redundancy is flagged in either historical window, prefer the simpler/stabler single state feature in later research rather than combining them.
- If high redundancy is not flagged in either window, keep them as separate state descriptors pending independent-source or genuine future evidence.
- No result from this analysis can establish executable PnL, candidate promotion, live support, or leverage support.
