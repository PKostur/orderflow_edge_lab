# Universal Regime Marginal + Pairwise Prospective Shadow v1

This watch is frozen **before** the first historical marginal/pairwise regime report is inspected.

Prospective start: **2026-09-26T00:00:00Z**.

The watch keeps the same five causal 8h labels, all 14 marginal states, all 78 unordered two-axis state combinations, the same three frozen strategies, the same ten symbols, and the same 20 bps round-trip cost assumption.

## Why freeze the future watch now?

The purpose is to prevent a common research failure: run a large historical condition scan, keep the attractive cells, and then call only those conditions "prospective hypotheses." Instead, all 92 lower-dimensional contrasts are placed into the future ledger before their historical marginal/pairwise outcomes are known.

Historical results may later identify *anchors*, but they cannot add, remove, redefine, merge, or retune prospective contrasts.

## Historical anchor rule

After the separately frozen historical marginal/pairwise analysis runs, an exact strategy/contrast becomes a historical anchor only when:

1. it is inference-eligible under the frozen historical breadth rules; and
2. its **global Holm FWER adjusted p-value is <= 0.10**.

BH or BY significance alone cannot create a historical anchor. The historical direction is the sign of the frozen state-minus-complement expectancy difference.

If a strategy has no historical global-Holm discovery, it has no selected replication anchor. All 92 contrasts are still accumulated prospectively for descriptive reporting.

## Prospective evidence

Only canonical trades whose entries occur at or after 2026-09-26T00:00:00Z may enter prospective evidence. Terminal snapshot liquidations do not count as completed trades.

The source fetch begins on 2026-01-01 to supply enough causal warm-up for the longest regime chain: the 90-bar market-coupling window plus the preceding 540 coupling observations.

No formal anchor replication decision is permitted before:

- 90 calendar days have elapsed;
- the exact prospective contrast has at least 20 group and 20 complement trades;
- the group covers at least 3 symbols and 3 distinct 30-day blocks;
- the complement covers at least 3 distinct 30-day blocks;
- at least 1,000 block-bootstrap replicates are valid.

An eligible historical anchor is marked \`REPLICATED_DESCRIPTIVELY\` only if the prospective expectancy-difference sign agrees with the historical anchor **and** the prospective global Holm FWER adjusted p-value is <= 0.10. If the sample is eligible but that rule is not met, it is \`NOT_REPLICATED\`. Before the time/sample requirements it remains \`WITHHELD\`.

These labels are research replication statuses only. They do not authorize filtering, promotion, live execution, or leverage.

## Multiplicity and dependency

All eligible prospective contrasts stay in the global 92-hypothesis family within each strategy. Global Holm is the conservative replication reference. Benjamini-Yekutieli remains the dependency-robust FDR reference because the regime contrasts overlap substantially.

## Boundary

The watch cannot:
- alter any regime threshold, persistence rule, state label, axis pair, strategy, symbol or cost;
- use pre-start entries;
- skip original trades because of their state;
- convert an adverse or favorable historical condition into a live filter;
- issue an early verdict;
- authorize live trading or leverage.
