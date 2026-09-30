# Markov Price Diagnostics v1

## Purpose

This diagnostic applies a frozen first-order Markov chain to the price histories associated with the three active frozen strategy candidates:

- `ena_bb40_rsi25_75_atr15_v1`
- `mexc_8h_ema24_96_atr025_v1`
- `mexc_xs_mom30_7_dn_v1`

It is deliberately separated from strategy logic. It does not modify entries, exits, sizing, costs, funding, candidate hashes, forward start times, or promotion gates.

## Anti-tampering boundary

The transition matrix is fitted only on price observations strictly before each candidate's development/freeze boundary defined in `config/markov_price_diagnostics_v1.json`.

Post-freeze prices are allowed only to determine the latest completed price state and project probabilities through the already-frozen transition matrix. They cannot refit transition probabilities.

Strategy PnL is not an input to state construction, state thresholds, transition fitting, or reliability labels.

## State definition

Each completed candle receives one of nine states:

- direction: `DOWN`, `FLAT`, `UP`
- volatility regime: `LOW`, `NORMAL`, `HIGH`

Direction uses the current close-to-close log return normalized by the rolling standard deviation of the prior 30 completed returns. The frozen direction thresholds are `z < -0.5`, `-0.5 <= z <= 0.5`, and `z > 0.5`.

Volatility regime uses the ratio of prior 10-bar realized volatility to prior 60-bar realized volatility. The frozen thresholds are below `0.8`, `0.8` through `1.2`, and above `1.2`.

This creates the nine-state space such as `UP|HIGH` or `FLAT|LOW`.

## Markov estimation

The model is first-order:

`P(S[t+1] | S[t])`

Transition rows use symmetric additive smoothing with alpha `0.5`. The raw transition counts are always preserved alongside probabilities. A current state is labeled `adequate` only after at least 20 pre-freeze outgoing transitions from that state; otherwise it is labeled `sparse`.

The report also provides, for the current state only, the pre-freeze empirical probability that the next close-to-close return is positive and the historical mean/median next-bar return. These are descriptive diagnostics, not execution signals.

## Candidate alignment

The diagnostic uses the candidate's own price interval without changing the strategy:

- ENA mean reversion: 1-hour candles, forecasts at 1/3/6/12/20 steps.
- 10-coin trend: 8-hour candles, forecasts at 1/3/6 steps for each symbol.
- 10-coin cross-sectional: daily candles, forecasts at 1/3/7 steps for each symbol.

For multi-symbol strategies, each symbol receives its own independently estimated price-state chain. The candidate summary reports only robust aggregate descriptive statistics; it does not create replacement portfolio weights.

## Interpretation

A Markov probability can answer questions such as:

- given the current `UP|HIGH` state, how often did the same market historically transition to another up state?
- what is the probability distribution over direction/volatility states one or several bars ahead?
- is the present state historically common enough to interpret or is it sparse?

It cannot establish a profitable edge by itself. It does not include strategy execution rules or transaction economics, and it must not be used to retroactively filter the frozen forward records.

If a Markov relationship later looks useful, it must become a separately versioned candidate and start a new forward clock. The existing frozen candidates remain untouched.
