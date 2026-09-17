# Cross-Market Futures v1 — Freeze Clarification

Frozen clarification: 2026-09-17, before inspection of any non-crypto strategy PnL.

This document narrows data eligibility and fixes feature equivalence. It does not change the frozen ES/NQ/GC/CL universe, signal thresholds, horizons, cooldown, friction surface, D0 transfer-survival gates, or claims.

## Signal clock

Signals are evaluated only on causally observed trade events, matching the existing discovery-v1 event convention. A signal may use only trade-flow and book state available before or at that trade under an unambiguous source ordering.

If two source events share the same timestamp, same-timestamp state may be used only when the source provides an ordering field (for example sequence) that establishes causal order. Otherwise the ambiguous update is excluded rather than arbitrarily ordered.

## CMF-H1 — aggressive-flow ratio

Use the same 10-second causal rolling aggressive-trade window as the source discovery implementation.

For each symbol:

`flow_ratio = (buy_volume_10s - sell_volume_10s) / (buy_volume_10s + sell_volume_10s)`

where volumes are trade sizes classified from explicit aggressor side when available, otherwise from a causal quote match. Tick-rule-only classification may be reported diagnostically but may not be used to rescue a dataset that fails the repository data-quality policy.

A signal requires at least 5 trade prints in the rolling window. The frozen absolute threshold remains 0.25.

## CMF-H2 — displayed-book imbalance

The transferred feature is explicitly **top-10 displayed depth imbalance**, not a BBO-only substitute:

`book_imbalance_10 = (sum(top10_bid_size) - sum(top10_ask_size)) / (sum(top10_bid_size) + sum(top10_ask_size))`

The frozen absolute threshold remains 0.25.

A dataset without causally ordered Level-2/top-10 depth is **ineligible for CMF-H2**. It may still be eligible for H1 and/or H3. Do not replace this feature with top-1 imbalance after observing results.

## CMF-H3 — normalized microprice edge

Use best bid/ask prices and displayed best-level sizes:

`microprice = (ask * bid_size + bid * ask_size) / (bid_size + ask_size)`

`microprice_edge = (microprice - midpoint) / (spread / 2)`

The frozen absolute threshold remains 0.20.

A dataset lacking best-level queue sizes is **ineligible for CMF-H3**. Do not synthesize sizes or substitute midpoint displacement.

## Market-depth availability

Full depth remains optional for the v1 dataset as a whole because H1 and H3 can be evaluated without top-10 depth when their own required fields are present. Full depth is mandatory specifically for H2. Eligibility must be reported per hypothesis before any PnL summary is produced.

## Native-contract and roll rule

Event-level state, signals, and fills must remain inside one recorded native contract per capture cluster. Continuous/rolling symbols may be used only as descriptive context. No synthetic roll jump may create a signal, target, fill, or PnL observation.

## Friction

Observed executable spread is always included by crossing ask/bid as frozen. The extra 0/1/2 total round-trip tick surface is then applied in native tick units and converted to return bps at the event price. Exact broker/exchange commissions remain a separately reported unresolved hurdle until sourced; they may not be assumed to be zero for promotion.

## Research status

No non-crypto strategy PnL had been inspected when this clarification was frozen. This remains transfer discovery only, with no candidate promotion, live-execution, or leverage claim.
