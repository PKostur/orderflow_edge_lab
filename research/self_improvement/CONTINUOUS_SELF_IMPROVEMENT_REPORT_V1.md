# Continuous Self-Improvement Research Report v1

## Scope

This report consolidates the adaptive self-improvement sequence run over existing `orderflow_edge_lab` evidence. The sequence used market-state prediction first and inspected frozen-strategy PnL only after state models and gates were fixed independently of PnL.

Total model-search epochs executed: **332**.

- v1 pilot: 20 epochs
- v2 state refinement: 30 epochs
- v3 adversarial/horizon stress: 120 epochs
- same-window cross-symbol liquidity screen: 84 epochs
- same-window cross-symbol volatility screen: 63 epochs
- 300-second directional adversarial screen: 15 epochs

The same-window cross-symbol model-selection screens are retained for audit but **invalidated for promotion** because all six transfer symbols share the exact same capture interval and therefore constitute one dependence cluster. They must not be interpreted as six independent validation folds.

## Dependence correction

The six transfer symbols in run `34843504234` were all observed from **2026-09-14 12:27:45 UTC through 12:42:40 UTC**. Training on five symbols' future targets while evaluating the sixth over the same clock interval can leak the shared future market regime. Any leave-one-symbol-out result from that simultaneous batch is therefore exploratory only.

The valid transfer test is instead: train only on the **12 pre-transfer ENA dependence batches**, freeze the model, then apply it to the later simultaneous cross-pair capture without using cross-pair labels for training.

## Valid state-prediction findings

### Volatility expansion

Frozen model:

- feature: `local_range_to_spread_15s`
- model: Ridge with median imputation and standard scaling
- target: `volatility_expansion_ratio_60s`
- training: 12 pre-transfer ENA dependence batches only

Transfer to the later six-symbol batch:

| Symbol | Spearman rho |
|---|---:|
| ARB | +0.376 |
| ETH | +0.359 |
| FILECOIN | +0.209 |
| NEAR | +0.344 |
| SOL | +0.470 |
| UNI | +0.132 |

Median cross-symbol rho: **+0.352**. All six symbols are positive. This is promising transfer evidence, but it is still only **one new dependence cluster**, not six independent forward clusters.

### Liquidity deterioration

Frozen v2 E12 model:

- features: `spread_bps`, `rolling_trade_count_10s`, `local_range_to_spread_15s`
- model: HGB
- target: `spread_expansion_ratio_15s`
- training: 12 pre-transfer ENA dependence batches only

Transfer results:

- ARB +0.116
- ETH -0.072
- FILECOIN +0.243
- NEAR +0.210
- SOL -0.140
- UNI +0.258

Median rho: **+0.163**, positive on 4/6 symbols. The signal is mixed and weaker than volatility transfer.

### Direction

Earlier future-direction models failed the v1 locked check and remained weak in v2/v3. A later apparent 300-second BTC-context result from same-window leave-one-symbol-out training was invalidated by the dependence correction. When the BTC model is trained only on the old ENA batches and transferred forward, median rho is only **+0.019**. No robust directional state edge is established.

## Frozen strategy execution economics

Across the six transfer symbols, before fees the frozen strategy's equal-pair median gross expectancy is:

| Horizon | Median gross bps/trade | Gross-positive pairs |
|---|---:|---:|
| 5s | -0.922 | 1/6 |
| 15s | -0.513 | 1/6 |
| 30s | -0.480 | 1/6 |

At 4 bps round trip, median net expectancy is approximately -4.92, -4.51, and -4.48 bps/trade respectively. Therefore realistic costs are not merely hiding a strong gross edge; the median gross signal itself is negative.

## PnL-independent state gates applied to the frozen strategy

### Liquidity gate

The frozen E12 model is trained only on old ENA data. The threshold is the 75th percentile of training-state predictions, selected without PnL. Trades are allowed when predicted spread deterioration is below that threshold.

At 4 bps:

| Horizon | Median baseline bps | Median gated bps | Median delta | Pairs improved |
|---|---:|---:|---:|---:|
| 5s | -4.922 | -4.973 | -0.071 | 2/6 |
| 15s | -4.513 | -4.466 | +0.010 | 4/6 |
| 30s | -4.480 | -4.683 | -0.173 | 0/6 |

The gate does not produce an economically meaningful rescue. At 15s the improvement is essentially zero and median PF remains about 0.158.

### Volatility gate

The frozen range-only volatility model is trained only on old ENA data. The primary gate allows the top quartile of predicted volatility expansion, with the threshold selected from training-state predictions only.

At 4 bps:

| Horizon | Median baseline bps | Median gated bps | Median delta | Pairs improved |
|---|---:|---:|---:|---:|
| 5s | -4.922 | -5.324 | -0.408 | 2/6 |
| 15s | -4.513 | -5.607 | -0.585 | 1/6 |
| 30s | -4.480 | -5.358 | -0.293 | 2/6 |

The robust volatility predictor does **not** translate into a profitable conditioning rule for the frozen strategy.

## Original-versus-reversed control

The original direction is usually better than reversing it at 5s and 15s, but both streams remain negative. At zero fees the equal-pair median original expectancy is -0.922 bps at 5s, -0.513 bps at 15s, and -0.480 bps at 30s. This rejects the simple explanation that the strategy only needs its direction flipped.

## Stop-risk control

At 4 bps and fixed 0.25% requested risk, across predeclared families/pairs:

- RR 1: median PF 0.069
- RR 2: median PF 0.107
- RR 3: median PF 0.130

Only 10.7% of cells have PF above 1, and descriptive positive upper-envelope examples are generally based on one or two trades. Stop geometry and risk sizing do not rescue the strategy.

## Conclusion

The self-improvement loop has reached a clear stopping conclusion for the **current frozen strategy family**:

1. There is credible PnL-independent information about future market state, especially 60-second volatility expansion.
2. There is weaker but nonzero information about future liquidity deterioration.
3. The current information set does not establish robust short-horizon directional alpha.
4. The frozen discovery strategy has negative median gross expectancy before realistic costs across the transfer universe.
5. Liquidity and volatility conditioning do not convert that strategy into positive executable expectancy.
6. Reversing direction and stop/RR changes do not solve the problem.

Therefore additional epochs that merely tune the current strategy, thresholds, or the same observed batches would be data mining rather than self-improvement. The next protocol should be versioned **before future evidence** and should target a new directional strategy family or a strategy whose payoff mechanism is explicitly linked to the proven volatility state, rather than trying to rescue discovery-v1.

No profitable edge is established. No untouched OOS claim is made. Live execution remains disabled.
