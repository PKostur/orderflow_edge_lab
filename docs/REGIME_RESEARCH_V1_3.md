# Regime Research v1.3

`regime-research-v1.3` is a forward discovery protocol for indicator-family orthogonality and incremental market-state prediction.

It does not change the indicator definitions or future-state targets from `regime-research-v1`, the effect thresholds from v1.1, the overlap-aware dependence clustering from v1.2, or the frozen `discovery-v1` trading logic.

## Why this version exists

The earlier protocol intentionally exposed many candidate indicators. v1.3 predeclares one representative per major family before later evidence is inspected, then permits a second feature only through an explicit incremental-information test or a prespecified interaction rationale.

This reduces the risk of selecting whichever correlated indicator happens to produce the highest development profit factor.

## State-first sequence

The protocol evaluates future market state before strategy PnL:

1. directionality versus chop;
2. volatility expansion versus contraction;
3. liquidity stability versus deterioration;
4. continuation versus reversion.

Only a state hypothesis that survives the inherited forward association, sign-stability, dependence-cluster and redundancy rules may later enter a separately frozen strategy-conditioning experiment.

## Primary family representatives

The predeclared representatives are:

| Family | Representative | Primary state target |
| --- | --- | --- |
| Trend and structure | `directional_efficiency_15m` | directionality, continuation/reversion |
| Volatility regime | `atr14_percentile_15m` | volatility |
| Liquidity and microstructure | `spread_bps` | liquidity |
| Aggressive flow | `signed_volume_ratio_10s` | directionality, continuation/reversion |
| Mean reversion | `bollinger_zscore_1m` | continuation/reversion |
| BTC and cross-asset context | `rolling_btc_correlation` | directionality, continuation/reversion, volatility |
| Derivatives positioning | `funding_rate_zscore` | directionality, continuation/reversion, volatility |
| Session and time | `utc_session` | all state targets as a stability slice |

Derivatives observations are used only when legitimately available. Missing fields remain missing and are never invented or silently filled with zero.

## Prespecified incremental tests

v1.3 allows only the following second-feature questions without a later protocol version:

* ADX beyond directional efficiency for directionality.
* Bollinger bandwidth percentile beyond ATR percentile for volatility.
* Top-10 depth beyond spread for liquidity.
* Aggressive-volume acceleration beyond signed-volume ratio for continuation/reversion.
* RSI beyond Bollinger z-score for continuation/reversion.
* BTC flow alignment beyond rolling BTC correlation for directionality.

The inherited high-redundancy boundary is absolute Spearman correlation of 0.80. A highly redundant feature is not added merely because it has a larger in-sample PF.

## Dependence and transfer

Independent capture batches remain dependence clusters using the v1.2 overlap-aware rule. One PnL-independent representative report per cluster enters the forward association and redundancy screen.

Cross-pair transfer must retain unchanged feature definitions and a PnL-independent pair universe. Transfer is supporting generalization evidence, not untouched OOS validation.

## Economics, risk and promotion boundary

State prediction itself is PnL independent. Any later conditioning experiment must preserve realistic fees, spread, slippage and latency, original-versus-reversed controls, stop-based MAE/MFE research, trial accounting, holdout auditing, paper/shadow reconciliation and runtime integrity.

No result from v1.3 by itself establishes a profitable edge or authorizes live order transmission.
