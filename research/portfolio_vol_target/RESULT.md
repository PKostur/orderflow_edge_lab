# Portfolio-level volatility targeting: result (adopted as a refinement candidate)

- Protocol: `portfolio-vol-target-v1`, declared in `5dc4dba` before evaluation
- Base: the crypto-trend-core design (DON8 + EMA8, 17 perps, inverse-vol sleeves, v3, 20 bps), 2020-2026
- Overlay: L = min(3, 15% / trailing 60-day portfolio vol), rebalanced weekly, turnover charged
- Status: descriptive, on seen data

| | Base | + Vol target |
| --- | ---: | ---: |
| Sharpe (t) | 1.40 (3.18) | 1.42 (3.38) |
| Annual return / realized vol | 20.5% / 14.6% | 26.6% / 18.7% |
| Max drawdown | −13.9% | −17.1% |
| 2020 / 2021 / 2022 | +7% / +93% / −0.3% | +14% / +56% / −3.3% |
| 2023 / 2024 / 2025 / 2026 | +13% / +15% / +11% / +7% | +31% / +27% / +25% / +22% |

- Leverage: p10 0.63, p50 1.68, p90 2.45; at the cap of 3 on 1.6% of days.
- Gross exposure: base mean 18%; scaled p50 27%, p90 51%, max 109%; above
  100% on 0.5% of days.
- Total overlay cost: about 1% over six years.

## Reading

Sharpe barely changes. The gain is consistency and capital use: the book
leans in during calm years and pulls back in hot ones, so returns depend far
less on 2021. That addresses a major weakness found in the portfolio anatomy.
Costs: realized vol overshoots the target (18.7% vs 15%) because trailing vol
lags, and drawdown deepens to −17%. For live use, set a slightly lower target
or accept about 19%. Adopt as a refinement candidate; forward evidence is
still required.
