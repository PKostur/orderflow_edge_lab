# Markov EV Overlay v1 — Initial Analysis

## Boundary

Protocol frozen before EV inspection: `config/markov_ev_overlay_v1.json`.

This is a diagnostic/counterfactual analysis only. It does not modify any frozen candidate, signal, entry, exit, position, weight, cost assumption, funding accounting, forward clock, or promotion status.

The underlying Markov transition matrices and state rewards are fitted only from each candidate's pre-freeze MEXC price history. Post-freeze prices are used only to identify the current state.

## Method

For each of the 9 frozen direction × volatility states, estimate the mean next close-to-close log return from pre-freeze observations. Treat those means as state rewards. Starting from the current state, propagate the first-order Markov transition matrix for H bars and calculate:

`expected_gross_bps(H) = sum_{k=0}^{H-1} p_k dot reward_vector`

For a fresh long action:

`expected_net_bps = expected_gross_bps - 20 bps round-trip cost`

For a fresh short action:

`expected_net_bps = -expected_gross_bps - 20 bps round-trip cost`

Flat EV is 0.

The conservative diagnostic score is `expected_net_bps - 1 standard error`, where standard error is an independence approximation propagated from the state reward estimates. It is not a forecast confidence interval for realized PnL and can understate uncertainty, especially for correlated portfolio symbols.

Future funding is assumed to be 0 for this EV ranking. This does not alter the realized-funding accounting in the frozen forward scoreboards.

## ENA 1h

Candidate: `ena_bb40_rsi25_75_atr15_v1`

Current state: `DOWN|NORMAL`.

| Horizon | Expected gross underlying bps | Approx. SE bps | Long net after 20 bps | Long conservative score | Best fresh action |
|---:|---:|---:|---:|---:|---|
| 1h | +5.10 | 5.25 | -14.90 | -20.15 | FLAT |
| 3h | +5.78 | 6.15 | -14.22 | -20.37 | FLAT |
| 6h | +6.66 | 6.97 | -13.34 | -20.31 | FLAT |
| 12h | +8.99 | 8.19 | -11.01 | -19.20 | FLAT |
| 20h | +12.92 | 9.53 | -7.08 | -16.61 | FLAT |

Interpretation: the current ENA state has a mild positive/mean-reverting reward, but it is too small to clear the frozen 20 bps fresh round-trip hurdle. Markov EV therefore does not justify creating a fresh directional trade from this state. This does not alter the original BB/RSI/ATR candidate's own entry logic.

## 10-coin 8h trend

Candidate: `mexc_8h_ema24_96_atr025_v1`.

Existing frozen portfolio at the analyzed snapshot: +10% BTC, ETH, SOL, XRP, DOGE, BNB, ADA, LINK, ENA and -10% SUI.

### Existing frozen portfolio, Markov reward diagnostic

| Horizon | Expected gross portfolio bps | Approx. portfolio SE* | Fresh-entry net after 20 bps | Conservative score* |
|---:|---:|---:|---:|---:|
| 1 bar / 8h | +22.16 | 11.13 | +2.16 | -8.98 |
| 3 bars / 24h | +39.10 | 13.86 | +19.10 | **+5.24** |
| 6 bars / 48h | +79.35 | 16.48 | +59.35 | **+42.87** |

`*` Independence approximation. Crypto symbols are correlated, so portfolio uncertainty is understated if interpreted as a realized-PnL risk measure.

The protocol's preregistered primary trend horizon is 3 bars, not 6 bars. The stronger 6-bar number is reported descriptively and must not be substituted as the primary horizon after seeing the result.

### 3-bar fresh-action conservative scores

Only ETH and LINK clear the 20 bps cost hurdle plus one estimated standard error at the preregistered 3-bar horizon:

- ETH long: +17.85 bps conservative score
- LINK long: +18.07 bps conservative score
- BTC, SOL, XRP, DOGE, BNB, ADA, SUI, ENA: FLAT is superior under the conservative fresh-entry score

This does not imply removing or resizing any existing frozen trend positions. It identifies where the Markov reward model currently agrees most strongly with fresh directional exposure.

### 6-bar descriptive result

At 6 bars, positive conservative long scores appear for ETH, SOL, DOGE, BNB, LINK and ENA. BTC, XRP, ADA and SUI remain below the conservative fresh-entry threshold. SUI's current frozen short is not reinforced by the Markov reward model.

Because 6 bars looked stronger only after inspection, it remains descriptive development evidence unless separately preregistered for a future-only experiment.

## 10-coin 30d/7d dollar-neutral cross-sectional momentum

Candidate: `mexc_xs_mom30_7_dn_v1`.

Existing frozen portfolio: +25% XRP, +25% ENA, -25% ADA, -25% SUI.

### Existing frozen basket, Markov reward diagnostic

| Horizon | Expected gross portfolio bps | Approx. portfolio SE* | Fresh-entry net after 20 bps | Conservative score* |
|---:|---:|---:|---:|---:|
| 1 day | -29.08 | 66.65 | -49.08 | -115.72 |
| 3 days | -16.01 | 71.80 | -36.01 | -107.81 |
| 7 days | +12.27 | 78.08 | **-7.73** | **-85.81** |

At the preregistered 7-day horizon, the univariate Markov reward model does not support the existing basket after the 20 bps cost hurdle. Uncertainty is also very large.

This is not evidence that the cross-sectional strategy is wrong. The strategy is a relative-ranking portfolio and the Markov model here is univariate per symbol. The disagreement is useful precisely because the models target different mechanisms.

At the 7-day horizon, individual univariate conservative fresh-action scores favor ETH long, ADA long and ENA long. ADA therefore directly disagrees with the frozen cross-sectional strategy's ADA short. No frozen weight is changed because of this disagreement.

## EV-maximization interpretation

The initial results support a conservative architecture for any future Markov-assisted candidate:

1. Keep every existing frozen strategy untouched.
2. Do not let Markov reverse a base strategy signal.
3. For a separately versioned shadow clone, allow the original strategy to propose the trade.
4. Markov may only PASS or VETO the proposed fresh trade using a horizon frozen in advance.
5. PASS only if the same-side expected net reward after the full 20 bps round-trip hurdle is positive and its conservative score (`net EV - 1SE`) is positive.
6. Require the current state to have at least 20 pre-freeze outgoing transitions.
7. Do not use Markov to add leverage or increase position size.
8. The clone starts a new forward clock and is compared prospectively against the untouched base candidate.

This architecture maximizes estimated expected value by avoiding historically poor state/action combinations, while minimizing degrees of freedom and preserving a clean base-control comparison.

## Current ranking

- **Best Markov/base agreement:** 8h trend at the preregistered 3-bar horizon, particularly ETH and LINK.
- **Weak positive state reward but below costs:** ENA 1h.
- **Strongest disagreement:** cross-sectional basket, especially the ADA short, but the univariate Markov model is not a substitute for the cross-sectional mechanism.

No profitable edge is established. No live action is authorized. Any Markov-gated clone must be frozen separately before collecting future results.
