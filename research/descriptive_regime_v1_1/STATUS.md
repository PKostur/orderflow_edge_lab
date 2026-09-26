# Descriptive Regime Labels v1.1 Status

## Protocol state

- v1 labels and 162-cell grid are frozen and unchanged.
- v1 inference is invalidated because its bootstrap test did not impose the zero-expectancy null.
- v1.1 is inference-only hardening. It uses null-centered 30-day block resampling and tests only predeclared cells with at least 20 trades.
- Same-period historical diagnostics only. No filtering, promotion, live trading, or leverage authority.

## Immutable run references

### v1
- implementation freeze: \`f481ae50fee98953a6542334d10c123870e6301d\`
- binding commit: \`2f7bbf5dde2e1d95528a418d76d6e5ae8f4da4e0\`
- first run: \`36170278269\`
- artifact digest: \`sha256:13f9ae3e420067c1b8b81cfd5e3c17e02fcc9fd31404274a8bda0d0b9969bfd8\`
- joint cell-set hash: \`2bb7f94fb7ce3dbc65748d98cb726ee9c8072fae31319fbd073f9d935c3b46cc\`
- inference status: invalidated; do not use v1 p/q/Holm flags.

### v1.1
- implementation freeze: \`fc1003d92e512b17acedaac8cb839cbe05877f9a\`
- binding commit: \`29c27d0abe391a12cf2872c844d9c38ac02f26a0\`
- post-freeze test-harness-only fix: \`30dded1d3203d8081303adab13f2717ffac7d668\`
- successful run: \`36171029303\`
- artifact digest: \`sha256:4f0fffc32ceef3b546310d86626162cc901ff671352df9a4f230f96054b17145\`

## Coverage and sparsity

Historical completed non-terminal trades:
- DON8: 220 total, 174 fully classifiable into the five-axis grid, 46 warm-up/unclassified.
- EMA8: 332 total, 269 fully classifiable, 63 unclassified.
- VOL8: 2,095 total, 1,713 fully classifiable, 382 unclassified.

Nonempty / inferentially eligible (>=20 trades) joint cells:
- DON8: 52 nonempty / 1 tested.
- EMA8: 61 nonempty / 2 tested.
- VOL8: 96 nonempty / 23 tested.

The 162-cell grid is therefore too sparse to support broad joint-state inference for DON8 or EMA8. That is a sample-size limitation, not a strategy conclusion.

Across all symbol-bars, approximate state occupancy is:
- trend: CHOP 28.4%, MIXED 24.3%, TREND 27.4%, UNKNOWN 19.9%;
- volatility: LOW 33.8%, MID 22.8%, HIGH 24.2%, UNKNOWN 19.1%;
- coupling: LOW 26.2%, MID 19.2%, HIGH 34.0%, UNKNOWN 20.6%;
- shock: NORMAL 96.8%, SHOCK 3.2%;
- drawdown: NEAR_HIGH 8.1%, CORRECTION 11.3%, DEEP_DRAWDOWN 62.2%, UNKNOWN 18.4%.

The fixed 10%/20% drawdown convention is therefore highly imbalanced on this crypto sample. This is a descriptive state-coverage fact. It is not permission to retune drawdown boundaries against PnL.

## Corrected v1.1 inference

At alpha 0.10:

| Strategy | Tested cells | BH FDR discoveries | Holm FWER discoveries |
| --- | ---: | ---: | ---: |
| DON8 | 1 | 0 | 0 |
| EMA8 | 2 | 0 | 0 |
| VOL8 | 23 | 2 | 2 |

The two VOL8 cells surviving both corrections are adverse historical states:

1. \`CHOP / MID volatility / HIGH coupling / NORMAL shock / DEEP_DRAWDOWN\`
   - trades: 132
   - expectancy: -144.48 bps/trade
   - descriptive 30-day block percentile interval: [-233.82, -74.14] bps
   - null-centered bootstrap p: 0.00150
   - BH q: 0.02299
   - Holm adjusted p: 0.03448
   - win rate: 28.79%
   - correct-direction rate: 31.06%
   - median MFE: 214.51 bps
   - median absolute MAE: 251.24 bps
   - median per-symbol compounded return: -20.81%
   - positive-symbol fraction: 10%

2. \`MIXED / HIGH volatility / HIGH coupling / NORMAL shock / DEEP_DRAWDOWN\`
   - trades: 57
   - expectancy: -133.79 bps/trade
   - descriptive 30-day block percentile interval: [-175.51, -102.21] bps
   - null-centered bootstrap p: 0.00200
   - BH q: 0.02299
   - Holm adjusted p: 0.04398
   - win rate: 31.58%
   - correct-direction rate: 33.33%
   - median MFE: 225.21 bps
   - median absolute MAE: 256.75 bps
   - median per-symbol compounded return: -8.47%
   - positive-symbol fraction: 20%

The first adverse cell contains observations across all ten symbols and across 2024, 2025, and 2026. The second also spans all ten symbols and all three calendar years. This reduces the chance that either result is literally a single-symbol or single-year artifact, but it does not make the findings future OOS.

## Descriptive marginal observations

These are explanatory summaries only, with no new hypothesis test and no filtering authority.

- VOL8 win rate is fairly similar across LOW/MID/HIGH volatility, while median MFE is larger in HIGH volatility than LOW volatility. This is consistent with the earlier payoff-amplitude observation that volatility can change move size more than hit rate.
- Low market coupling has higher pooled historical expectancy than high coupling for all three strategies in the univariate descriptive split. This is not isolated causal evidence because coupling co-occurs with trend, volatility, drawdown and calendar regimes.
- SHOCK observations are rare, so shock-conditioned conclusions remain sample-limited.
- The drawdown dimension is dominated by DEEP_DRAWDOWN under fixed conventional 10%/20% bands, especially for altcoins.

## Research boundary / next step

Do not convert the two adverse VOL8 cells into an exclusion filter on this evidence. A decision-affecting filter would require a new preregistered candidate and later untouched/future evidence.

For interpretability, a future separately frozen layer may report all five one-axis marginal states and predeclared low-dimensional interactions rather than relying on the full 162-cell grid. Such a layer must be defined symmetrically across all axes and before inspecting any new period; it must not select combinations because their historical PnL looked attractive.
