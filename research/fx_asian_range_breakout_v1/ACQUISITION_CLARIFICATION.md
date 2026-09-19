# FX Asian-range breakout v1 — acquisition overlap clarification

Frozen before any D0 PnL is calculated.

- The provider's hourly endpoint is reconstructed from overlapping fixed date chunks because the request limit applies to underlying minute aggregates.
- Overlapping chunks are an acquisition artifact, not additional observations.
- For a given pair + Unix timestamp, all duplicate copies must have identical open/high/low/close values.
- Exact duplicates are collapsed to one hourly observation.
- If duplicate copies disagree on any OHLC value, that timestamp is treated as conflicted and is not eligible for signal/range/entry/exit use. No preferred chunk is chosen after results.
- No D0 PnL is calculated until all four pairs span the complete frozen D0 date range.
