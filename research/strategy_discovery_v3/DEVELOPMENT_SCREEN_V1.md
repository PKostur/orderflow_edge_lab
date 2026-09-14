# Strategy Discovery v3 — Market-Neutral Development Screen v1

## Evidence boundary

This report records development-only screening under the protocol frozen in `config/strategy_discovery_v3_market_neutral.json`. The locked August–September 2026 internal holdout was **not opened** because no cell passed every frozen development gate. Nothing here is genuine future OOS evidence, a profitable-edge claim, or a live-trading promotion.

Development dependence clusters: 21-day calendar folds 0–14 from the 2025-09-01 start. Fold 15 was discarded because it straddles the frozen 2026-08-01 development/holdout boundary. Folds 16–17 remain locked.

## Search size

The realized tournament produced 622 relationship/strategy cells across true two-leg BTC-hedged residuals, rolling OLS log-spread reversion, Kalman residual reversion, cross-sectional beta-residual long/short portfolios, PCA one-factor residual portfolios, and training-only selected alt/alt stationary pairs.

- State-screen passes: **50**
- Cells with positive median development net expectancy after primary both-leg costs: several, but only 2 survived the preliminary state + expectancy + fold-sign screen.
- Cells passing **all** frozen development gates: **0**
- Locked internal holdout opened: **No**

## Closest cells

| Family | Parameters | Development folds | Trades | Median state rho | Median fold net | Positive folds | Breadth issue |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Alt/alt cointegration reversion | SOL/SUI, 192h, z1.5, hold24h | 8 | 86 | +0.255 | **+16.82 bps** | 75% | Fails minimum 10 development folds |
| PCA one-factor residual reversion | 96h, z2.0, hold48h | 15 | 116 | +0.083 | **+15.16 bps** | 53% | Fails 60% positive-fold and symbol-breadth gates |
| Cross-sectional beta-residual momentum control | lookback24h, k2, hold24h | 15 | 295 | +0.059 | **+4.57 bps** | 60% | Only 44% constituent-symbol contribution breadth |
| Alt/alt cointegration reversion | LINK/SUI, 336h, z1.5, hold8h | 9 | 143 | +0.049 | +1.88 bps | 56% | Fails fold-count and fold-sign gates |

The SOL/SUI cell beats its reversed-direction control by a wide margin, but the relationship-validity gate admits it in only eight development folds. It is therefore not eligible for the holdout regardless of headline expectancy.

## Family-level findings

| Family | Realized cells | State passes | Best development median net |
| --- | ---: | ---: | ---: |
| Alt/alt cointegration reversion | 402 | 9 | +110.54 bps (sparse cell; fails trial-count/stability gates) |
| Cross-sectional beta-residual momentum control | 30 | 12 | +25.51 bps |
| PCA one-factor residual reversion | 30 | 11 | +15.16 bps |
| Cross-sectional beta-residual reversion | 30 | 5 | +14.43 bps |
| PCA one-factor residual momentum control | 30 | 6 | -7.48 bps |
| Rolling OLS log-spread reversion | 30 | 7 | -7.89 bps |
| Kalman beta-residual reversion | 40 | 0 | no admissible trades after frozen relationship gate |
| Rolling beta-residual reversion | 30 | 0 | no admissible trades after frozen relationship gate |

The return-residual and Kalman families were largely rejected before PnL because their residual processes did not jointly satisfy the frozen ADF and 2–168h half-life requirements in enough folds.

## Interpretation

True two-leg construction improved the payoff scale in a few cells relative with earlier one-leg short-horizon strategies, but the improvement is not broad or stable enough for promotion. The strongest information is concentrated in (a) selected alt/alt stationary relationships, (b) cross-sectional residual momentum, and (c) slower PCA residual reversion. None currently satisfies the complete breadth/stability requirements.

The internal holdout remains scientifically useful because it has not been opened. A separately frozen v3.1 may continue development work on structurally different payoff/robustness definitions, but it must not retroactively alter this v3 verdict.

Claims remain: development only; locked internal holdout unopened; no verified OOS; no profitable edge established; live disabled.
