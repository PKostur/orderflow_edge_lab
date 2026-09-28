# Multi-premia, human-constrained (`multi-premia-human-v1`, declared `e938530`): H5 PASSES, with caveats

Descriptive. 70 coins, 2020-06 to 2026-09, 20 bps, Binance funding proxy. Net per-coin blend weight, decided at 00 UTC,
traded at the 08 UTC open (09/10 CET check-in), top K coins by |weight|, gross capped at 1x.

| Book | Sharpe | t | Annual return | Max drawdown | Halves | Daily turnover |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| V_ALL (70 coins, same timing) | 1.75 | 3.95 | 18.6% | −12.4% | 1.98 / 1.52 | 5.8% |
| H10 | 1.40 | 3.23 | 24.6% | −28.2% | 1.69 / 1.15 | 8.1% |
| **H5 (user constraint)** | **1.19** | **2.65** | 29.3% | **−31.3%** | 1.89 / 0.66 | 9.3% |
| H3 | 0.95 | 2.12 | 28.6% | −51.4% | 2.38 / −0.19 | 10.1% |

Per year, H5: 2021 +107%, 2022 +26%, 2023 +79%, 2024 +41%, 2025 −2%, 2026 −24% (V_ALL: 2025 +17%, 2026 −7%).

## Reading
- The pre-registered rule passes (t ≥ 2, Sharpe ≥ 0.5 × V_ALL, both halves positive).
- Daily 08 UTC timing and netting cost 2.09 → 1.75; truncating to 5 coins costs another 1.75 → 1.19.
- Concentration buys return and gives up diversification: drawdown goes from −12% to −31%, and the recent half is weak
  (0.66; 2025–26 negative). The edge now depends on a few names, so H5 is a much riskier book than the blend.
- Monotone in K: each extra coin helps. A human who can manage 10 positions keeps noticeably more (1.40, halves both > 1).
- No further tuning; next step is forward-only (pre-register H5 alongside the blend watch), not promotion.
