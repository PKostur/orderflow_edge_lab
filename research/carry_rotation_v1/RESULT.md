# carry-rotation-v1: result (run once, 2026-10-23, GitHub run 39979684173)

Weekly rotation of delta-neutral funding carry into the 5 highest-funding of 20 large caps, Binance, 2021-01 to
2026-09, after the same fees as carry-study-v1. Rules: `config/carry_rotation_v1.json`. Numbers: `result.json`.

| | Rotation (top 5 of 20) | BTC/ETH always on |
|---|---:|---:|
| Per year, on capital (50/50) | 2.5% | 5.7% |
| Max drawdown, on capital | -5.8% | -0.4% |
| Positive months | 33% | 91% |
| 2021 / 2022 / 2023 / 2024 / 2025 / 2026 (on capital) | 21.6 / -2.2 / 0.2 / 1.9 / -2.6 / -2.5% | 18.6 / 1.2 / 4.0 / 6.5 / 2.5 / 0.8% |

Funding collected 86% of notional over the period, but weekly switching cost 57%, leaving less than holding BTC and
ETH. It has lost money every year since 2025. Reading: chasing the highest funding is eaten by trading costs;
the plain BTC/ETH hedge is better on every measure.
