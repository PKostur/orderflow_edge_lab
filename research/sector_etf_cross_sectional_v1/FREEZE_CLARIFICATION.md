# Sector ETF cross-sectional v1 — pre-PnL calculation clarification

Frozen before any sector-strategy PnL is calculated.

## Independent-source fallback

- Massive historical stock data is not entitled for the frozen 2019-09-01 through 2023-12-29 acquisition window.
- The frozen strategy protocol may therefore be evaluated from one independent fallback source without changing dates, universe, signals, costs, or gates.
- Fallback source for this run: Yahoo Finance chart API daily OHLC for all eleven frozen ETFs.
- One run must use the same source for all eleven ETFs. No per-symbol source mixing or missing-symbol substitution is allowed.
- Raw Yahoo OHLC is used as delivered by the chart endpoint. Adjusted-close total-return series is not used for entry, exit, or feature prices.
- If any frozen ETF lacks the required history or common-session timestamps, the affected observation is ineligible; the universe is never reduced.

## Calendar and timing

- The research calendar is the intersection of daily dates available for all eleven frozen ETFs.
- A trailing N-session feature at signal session t is `close[t] / close[t-N] - 1`, requiring N+1 common-session closes.
- Ranking uses the frozen rule and ticker-ascending tie break.
- Signal is formed only after the signal session close.
- Entry is the next common valid session open.
- Exit is the open exactly H common valid sessions after entry, where H is the frozen holding period.
- Signal, entry, and exit must all lie inside the D0 window for a D0 observation. Warmup closes may precede D0.
- After an observation exits, the next signal is formed at that same exit session close. This makes observations sequential and non-overlapping.

## PnL and gates

- Each selected leg gross return is `direction * (exit_open / entry_open - 1) * 10000` bps.
- Primary/stress net leg return subtracts the frozen 8/16 bps round-trip cost once.
- Portfolio net return is the arithmetic mean of the six selected leg net returns.
- Reversed control uses the same dates, names, ranks, entry, exit, and costs with every direction multiplied by -1.
- Sector contribution is each selected leg's net bps divided by six and summed across D0 observations.
- Calendar-year stability groups observations by signal year.
- Positive-contribution concentration is the largest positive sector contribution divided by the sum of positive sector contributions. If none are positive, the gate fails.
- A family that fails any D0 gate is dead under that family ID; its 2024-2025 holdout is not fetched or inspected.
