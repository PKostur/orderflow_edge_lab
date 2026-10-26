# Blend capacity / price impact v1 (descriptive only)

Assumptions: square-root law, cost = Y*sigma_d*sqrt(Q/ADV); Q=|dw|*AUM; ADV/sigma trailing 30d (causal).
Window 2026-04-05..2026-10-11 (190 days), 70 coins. Reference gross edge 10%/yr is an ASSUMPTION. Fee drag (20 bps round trip): 1.38%/yr. Mean daily sum|dw| = 0.038.
MEXC USD volume = vol(contracts)*contractSize*close. Binance archive end 2026-09-30; later days forward-filled; 62/70 coins matched.

## Liquidity source: mexc

Annualized impact drag (fraction of AUM per year)

| Y | 1e+04 | 1e+05 | 1e+06 | 1e+07 | 1e+08 |
|---|---|---|---|---|---|
| 1.0 | 0.37% | 1.18% | 3.73% | 11.79% | 37.27% |
| 0.5 | 0.19% | 0.59% | 1.86% | 5.89% | 18.64% |
| 2.0 | 0.75% | 2.36% | 7.45% | 23.57% | 74.55% |

AUM (USD) at which impact drag reaches a share of the reference edge

| Y | 25% | 50% | 100% |
|---|---|---|---|
| 1.0 | 4.5e+05 | 1.8e+06 | 7.2e+06 |
| 0.5 | 1.8e+06 | 7.2e+06 | 2.88e+07 |
| 2.0 | 1.12e+05 | 4.5e+05 | 1.8e+06 |

Top 10 impact coins at AUM 1e+06 (Y=1, drag/yr)

AKE_USDT 0.52%, NIL_USDT 0.39%, RARE_USDT 0.39%, PHA_USDT 0.26%, LSK_USDT 0.19%, BR_USDT 0.18%, ORDI_USDT 0.13%, GRASS_USDT 0.12%, AR_USDT 0.11%, QNT_USDT 0.11%

Top 10 impact coins at AUM 1e+07 (Y=1, drag/yr)

AKE_USDT 1.63%, NIL_USDT 1.24%, RARE_USDT 1.22%, PHA_USDT 0.82%, LSK_USDT 0.60%, BR_USDT 0.57%, ORDI_USDT 0.42%, GRASS_USDT 0.39%, AR_USDT 0.36%, QNT_USDT 0.35%

## Liquidity source: binance_spot

Annualized impact drag (fraction of AUM per year)

| Y | 1e+04 | 1e+05 | 1e+06 | 1e+07 | 1e+08 |
|---|---|---|---|---|---|
| 1.0 | 0.24% | 0.77% | 2.42% | 7.66% | 24.23% |
| 0.5 | 0.12% | 0.38% | 1.21% | 3.83% | 12.11% |
| 2.0 | 0.48% | 1.53% | 4.85% | 15.32% | 48.46% |

AUM (USD) at which impact drag reaches a share of the reference edge

| Y | 25% | 50% | 100% |
|---|---|---|---|
| 1.0 | 1.06e+06 | 4.26e+06 | 1.7e+07 |
| 0.5 | 4.26e+06 | 1.7e+07 | 6.81e+07 |
| 2.0 | 2.66e+05 | 1.06e+06 | 4.26e+06 |

Top 10 impact coins at AUM 1e+06 (Y=1, drag/yr)

NIL_USDT 0.26%, RARE_USDT 0.25%, LSK_USDT 0.20%, PHA_USDT 0.16%, QNT_USDT 0.11%, ORDI_USDT 0.11%, PYTH_USDT 0.08%, AR_USDT 0.07%, JUP_USDT 0.06%, EIGEN_USDT 0.05%

Top 10 impact coins at AUM 1e+07 (Y=1, drag/yr)

NIL_USDT 0.83%, RARE_USDT 0.79%, LSK_USDT 0.64%, PHA_USDT 0.52%, QNT_USDT 0.34%, ORDI_USDT 0.34%, PYTH_USDT 0.24%, AR_USDT 0.21%, JUP_USDT 0.18%, EIGEN_USDT 0.17%

