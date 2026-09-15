# Markov Price Diagnostics v1 — Initial Frozen Snapshot

## Evidence boundary

Protocol frozen before results: `config/markov_price_diagnostics_v1.json`.

This snapshot is diagnostic only. It does not alter any frozen candidate, forward result, position, cost assumption, funding treatment, or promotion rule.

Transition matrices use pre-freeze MEXC price history only. Current post-freeze prices are used only to identify the current state.

Sources:

- Deadline Forward PnL Scoreboard run `34987197027`, artifact `deadline-forward-pnl-scoreboard`, digest `sha256:cb61de9fb64fd6287ef82a8551a252b43ef900fffc49a4415f26c969d348ade0`.
- ENA pre-freeze history from run `34703135745`, artifact `ena-mean-reversion-risk-v1`, digest `sha256:94ee2ebd582b695156b7ef187f520ccd62ce7b6fcccefdedf3fdd2086c2d723c`.

The state space is the frozen 9-state direction × volatility grid. `P(next +)` and `P(next -)` refer to the sign of the next raw close-to-close return observed historically after the same state. State-transition probabilities are separate and use the 9-state Markov matrix.

## ENA 1h mean reversion

Candidate: `ena_bb40_rsi25_75_atr15_v1`

Latest completed 1h state in the preserved source: `2026-09-15 14:00 UTC`.

Current Markov state: **DOWN|NORMAL**.

- current direction z: `-1.5665`
- current volatility ratio: `1.1259`
- pre-freeze outgoing transitions from this state: `550` → adequate
- historical `P(next +)`: **51.09%**
- historical `P(next -)`: **48.00%**
- mean next return after this state: **+5.10 bps**
- median next return after this state: **+6.76 bps**

One-step Markov direction probabilities from `DOWN|NORMAL`:

- DOWN: **27.86%**
- FLAT: **40.85%**
- UP: **31.29%**

At 3 steps the distribution is approximately DOWN 29.27%, FLAT 43.11%, UP 27.62%. By 20 steps it is approximately DOWN 29.05%, FLAT 43.40%, UP 27.55%.

Interpretation: the historical state has a mild mean-reverting/bounce character rather than strong downside continuation, but the raw next-bar sign edge is only about 51/49. This is descriptive support for further observation, not a new ENA filter.

## 10-coin 8h trend

Candidate: `mexc_8h_ema24_96_atr025_v1`

The latest fully completed 8h bar available at the scoreboard as-of time is the bar opened `2026-09-15 00:00 UTC`. The `08:00 UTC` bar was not treated as complete for this diagnostic.

Current price states:

| Symbol | Frozen strategy weight | Current Markov state | Pre-freeze state count | P(next +) | P(next -) |
|---|---:|---|---:|---:|---:|
| BTC | +10% | DOWN|LOW | 22 | 58.70% | 41.30% |
| ETH | +10% | DOWN|LOW | 20 | 59.52% | 40.48% |
| SOL | +10% | DOWN|LOW | 13 | 53.57% | 39.29% |
| XRP | +10% | DOWN|LOW | 22 | 45.65% | 54.35% |
| DOGE | +10% | DOWN|LOW | 15 | 53.13% | 46.88% |
| BNB | +10% | FLAT|LOW | 25 | 51.92% | 48.08% |
| ADA | +10% | DOWN|LOW | 15 | 59.38% | 40.63% |
| LINK | +10% | DOWN|LOW | 10 | 68.18% | 31.82% |
| SUI | -10% | DOWN|LOW | 20 | 59.52% | 35.71% |
| ENA | +10% | DOWN|LOW | 20 | 59.52% | 40.48% |

Six of ten current symbol states meet the predeclared 20-transition adequacy threshold. SOL, DOGE, ADA, and LINK are sparse and should be interpreted cautiously.

Across the current portfolio weights, the historical next-return-sign probability aligned with the existing side is approximately **54.53%**. This is not an executable strategy probability because symbols are correlated and the statistic ignores costs and portfolio dependence.

The median one-step Markov direction distribution across the ten symbols is approximately:

- DOWN: **23.80%**
- FLAT: **38.72%**
- UP: **33.96%**

Interpretation: nine of ten markets are currently in a low-volatility down state, but those states historically show more bounce/flattening than immediate downside continuation. This does not validate the trend strategy; it helps explain why a directional trend portfolio can experience sharp reversals in this regime.

## 10-coin 30d/7d dollar-neutral cross-sectional momentum

Candidate: `mexc_xs_mom30_7_dn_v1`

Latest fully completed daily bar in the preserved source: `2026-09-14 00:00 UTC`.

Current active portfolio legs:

| Symbol | Frozen weight | Current Markov state | Pre-freeze state count | Side-support probability |
|---|---:|---|---:|---:|
| XRP | +25% | UP|LOW | 26 | 50.00% next positive |
| ENA | +25% | UP|LOW | 19 | 47.50% next positive |
| ADA | -25% | UP|LOW | 26 | 42.59% next negative |
| SUI | -25% | UP|NORMAL | 17 | 47.22% next negative |

The equal-gross-weight historical next-day sign probability aligned with the existing four legs is approximately **46.83%**.

A rough state-conditioned weighted mean next-day return, before trading costs and without modeling cross-symbol dependence, is approximately **-29.08 bps** for the current long/short signs. This number is diagnostic only and should not be interpreted as a forecast of the 7-day strategy return.

The median seven-step state distribution across all ten symbols is approximately DOWN 30.17%, FLAT 43.01%, UP 26.40%, showing rapid convergence toward the chain's longer-run state mix rather than a strong seven-day directional forecast.

Interpretation: the univariate daily Markov chains do **not** currently reinforce the cross-sectional basket, especially the short legs. That does not invalidate the 30d/7d relative-momentum strategy because the strategy targets cross-sectional relative performance over a 7-day holding period, while this Markov diagnostic is built from each asset's own short-memory price state.

## Initial conclusion

The Markov layer currently adds **context rather than a new edge claim**:

1. ENA 1h shows a mild historical bounce tendency from its current `DOWN|NORMAL` state, but only a weak next-bar sign asymmetry.
2. The 8h universe is unusually synchronized in `DOWN|LOW`; historical transitions lean toward flattening/bouncing more than continued strong downside, which is useful regime context for the trend candidate.
3. The current cross-sectional four-leg basket is not supported by one-day univariate Markov direction probabilities. This is a useful disagreement signal to observe, not a reason to alter the frozen basket.
4. No Markov result may be used to back-filter, retune, or reinterpret already-started forward PnL.
5. If a Markov relationship later appears economically useful, it must be frozen as a separate candidate and start a new forward clock.

No profitable edge is established. Live execution remains disabled.
