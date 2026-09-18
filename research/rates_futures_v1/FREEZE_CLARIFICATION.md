# Rates futures v1 — pre-PnL calculation clarification

Frozen before strategy PnL.

- Standard outright contracts are identified by ticker matching the product root followed by a standard month code/year and with no ':' or '-' in the ticker.
- Contract selection is evaluated independently for each product on each candidate signal session. The selected contract must have at least 21 calendar days remaining to last_trade_date.
- A family's 20-session volatility window uses exactly 20 same-native-contract close-to-close log returns, requiring 21 closes.
- H1's 5-session numerator is the sum of the five most recent log returns contained within that same 20-return window.
- H2's shock return is the most recent log return in the same 20-return window.
- H3's 20-session trend uses log(current signal close / close exactly 20 valid sessions earlier) on the same contract.
- Entry is the next common valid session open after the signal. Exit is the open exactly N common valid sessions after entry, where N is the family's frozen holding_sessions.
- A portfolio observation is eligible only if every product needed for feature construction/ranking and every selected leg has all required same-contract bars. No leg may cross a roll.
- For H1/H2, portfolio gross/net return is the sum of each selected leg's signed return times abs(weight), with each leg paying its weighted native-tick friction.
- For H3, inverse-volatility weights are computed as 1/sigma then normalized by total inverse volatility; friction is weighted by abs(weight).
- Product contribution is each leg's weighted net bps summed across eligible D0 observations.
- Positive-contribution concentration is largest positive product contribution / sum positive product contributions; if none are positive, the gate fails.
- Reversed control keeps identical signal dates, products, weights, entry/exit timestamps and costs while multiplying every direction by -1.


## Window-boundary rule

Frozen before strategy PnL.

- D0 signal, entry and exit must all fall within 2025-02-03 through 2025-12-31 inclusive. January 2025 bars may be used only as indicator warmup.
- D3 signal, entry and exit must all fall within 2026-01-02 through 2026-08-31 inclusive.
- No D0 position may consume a 2026 holdout exit price, and no D3 position may consume the reserved September-2026 check.
