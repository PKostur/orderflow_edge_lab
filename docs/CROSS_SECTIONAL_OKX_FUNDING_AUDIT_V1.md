# Cross-Sectional OKX Funding Coverage Audit v1

## Purpose

This is a data-quality-only audit for the frozen cross-sectional candidate `mexc_xs_mom30_7_dn_v1`.

It was created after the first OKX D2 replication exposed incomplete realized-funding history from the current public funding-history REST endpoint.

The audit does **not** repair, overwrite, or reinterpret the frozen v1 replication artifact. It does not recompute candidate PnL.

## Coverage rule

The audit reconstructs the candidate's unchanged executed daily weights from the OKX shared price calendar.

For every symbol-day interval with a nonzero executed weight, it requires at least one finite realized funding observation strictly inside the held interval. This mirrors the funding-settlement inclusion rule used by the cross-sectional backtest.

A complete economic replication requires 100% coverage of those actually held intervals.

Missing funding is never considered equivalent to a zero funding rate for admission purposes.

## Evidence boundary

Outputs are data-quality diagnostics only:

- required held intervals;
- covered held intervals;
- coverage fraction;
- per-symbol coverage;
- first and last realized-funding observations;
- examples of missing held intervals;
- a boolean indicating whether complete-funding economics are admissible.

The audit cannot:

- change the candidate;
- retune parameters;
- repair an inspected historical result;
- promote a strategy;
- establish profitable edge;
- authorize live trading;
- authorize leverage.

If coverage is incomplete, a full economic replication requires a new versioned protocol using a source with demonstrably complete realized funding.

OKX's historical-data service advertises perpetual funding-rate archives from March 2022 onward, and OKX added a public historical-market-data query endpoint with funding-rate support in September 2025. Those archives are the appropriate next source to investigate rather than zero-filling unavailable REST history.
