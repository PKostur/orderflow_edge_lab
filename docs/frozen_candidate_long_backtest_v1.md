# Frozen Candidate Long Backtests v1

This lane re-evaluates the three watched frozen candidates over longer pre-freeze MEXC history without modifying their signal, risk, universe, timeframe, or execution definitions.

## Candidates

- ENA 1h Bollinger/RSI mean reversion with the frozen 1.5 ATR hard stop.
- 8h EMA 24/96 time-series momentum with the frozen 0.25 ATR-spread threshold across the frozen 10-symbol panel.
- 30d/7d dollar-neutral cross-sectional momentum across the frozen 10-symbol panel.

## Predeclared diagnostics

Every candidate is evaluated on the full legitimate historical span available to the harness, calendar-year slices, rolling 180-day windows stepped by 90 days, and rolling 360-day windows stepped by 180 days. Every predeclared window is retained. The exact frozen 20 bps round-trip cost is the primary historical stress case. Additional 30 and 40 bps cases are adverse execution diagnostics only.

Funding-aware candidates use actual public MEXC realized funding events. Window starts reset portfolio state to flat. No parameter is re-optimized from these results.

## Interpretation

These results are retrospective development stress. The subperiods overlap and are not independent OOS trials. They cannot modify the forward candidate specification, cannot satisfy untouched OOS requirements, cannot establish a profitable edge, and cannot authorize live execution.

The dedicated GitHub Actions artifact retains all cells, raw engine reports, source-data hashes, actual data coverage, and a deterministic multi-agent release-manager report.
