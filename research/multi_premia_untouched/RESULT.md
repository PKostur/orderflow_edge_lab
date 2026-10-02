# Multi-premia untouched-coins holdout (`multi-premia-untouched-holdout-v1`, registered `1014716`, run once): PRIMARY PASSES

60 perps no protocol had used (selected by MEXC metadata and turnover only), 2021–2026-09, frozen blend rules, 20 bps,
Binance funding proxy (57/60 coins covered).

| Book | Sharpe | t | Annual return | Max drawdown | Halves |
| --- | ---: | ---: | ---: | ---: | --- |
| S1 trend | 1.11 | 2.59 | 11.7% | −11.5% | 1.21 / 1.04 |
| S2 XS momentum | 0.81 | 2.03 | 28.2% | −45.5% | 0.97 / 0.68 |
| S3 funding carry | 0.41 | 0.90 | 11.6% | −51.9% | −0.02 / 0.91 |
| **S4 blend** | **1.39** | **3.16** | 16.4% | **−10.7%** | **1.41 / 1.37** |
| H5 human book (secondary) | 0.60 | 1.40 | 15.6% | −31.7% | 0.52 / 0.65 |

Blend per year: 2021 +54%, 2022 −2%, 2023 +22%, 2024 +10%, 2025 +9%, 2026 +10%.

## Reading
- The blend replicates on unseen coins (Sharpe 2.09 → 1.39, as expected out of sample) and is steadier than in development:
  both halves ≈ 1.4, positive every year but 2022 (−2%).
- Trend and momentum replicate; carry does not on its own (t 0.9), but still diversifies.
- The 5-coin human book does **not** hold up here (Sharpe 0.60, t 1.40). Its development pass (1.19) looks partly
  lucky; concentration is the weak link. The forward watch continues unchanged; prefer ≥10 coins if trading by hand.
- Caveats: survivorship in the coin list; thin tail liquidity (~0.4M USD/day) may understate costs.
