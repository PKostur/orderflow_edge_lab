# Cross-market futures v1 — Level-1 quote-age clarification

Frozen before any real non-crypto futures tick PnL is inspected.

- The maximum causal age of a prior Level-1 BBO used by CMF-H1 or CMF-H3 is **1.0 second**.
- The same 1.0-second bound must be used by source normalization, data audit, feature construction, replay, and export probing for this research lane.
- A prior quote older than 1.0 second is stale and cannot classify a trade or supply executable BBO/microprice state.
- A quote with the same timestamp as a trade is usable only when source sequence fields prove quote-before-trade ordering; otherwise it is blocked.
- Trade-local bid/ask snapshots may classify that trade when present, but are not promoted into reusable quote state for later trades.
- This clarification resolves an engineering default mismatch before real futures tick results; it does not change H1/H2/H3 thresholds, horizons, markets, costs, controls, or D0 gates.
