# Equities relative-reversal replication v2 — pre-PnL clarification

Frozen before any May or June replication PnL is calculated.

- Eligible sessions are US regular trading sessions in the frozen windows for which MSFT, AMD, BAC, CVX and SPY each contain exact bars at 10:00, 14:00, 14:01 and 15:55 America/New_York. Weekends and exchange holidays do not count as sessions.
- Ranking ties are broken by alphabetical ticker order only, as a deterministic non-economic tie breaker.
- For the four-name portfolio, the lowest relative-return metric is long at weight +0.5 and the highest is short at weight -0.5.
- Gross portfolio return is `0.5 * (long_exit / long_entry - 1) * 10,000 - 0.5 * (short_exit / short_entry - 1) * 10,000`.
- Primary net return subtracts exactly 2 portfolio bps once. Stress net return subtracts exactly 4 portfolio bps once.
- The reversed control swaps the chosen long and short at the identical decision, entry and exit timestamps and pays the identical cost.
- Positive-session concentration is the largest positive primary-net session contribution divided by the sum of all positive primary-net session contributions. If there are no positive sessions, the concentration gate fails.
- Leave-one-name-out removes exactly one frozen stock, reranks the remaining three using the unchanged metric and timestamps, takes the lowest long and highest short at +0.5/-0.5, and applies the same 2 bps primary cost.
- May D0 halves remain exactly 2026-05-04..2026-05-15 and 2026-05-18..2026-05-29.
- If any D0 gate fails, the June D3 holdout remains sealed and must not be inspected for this replication ID.
