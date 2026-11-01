# carry-study-v1: result (run once, 2026-10-23, GitHub run 39970444520)

Delta-neutral funding carry (long spot, short the same notional of the USDT perpetual), BTC and ETH equally,
after 10 bp spot / 5 bp perp taker fees plus 2 bp slippage per leg. Rules: `config/carry_study_v1.json`, frozen
before any data was loaded. Full numbers: `result.json`.

## Binance, 2020-01 to 2026-09 (data.binance.vision)

| | Return on notional | Return on capital (half spot, half margin) |
|---|---:|---:|
| Whole period, per year | 13.3% | 6.5% |
| 2020 | 23.4% | 11.1% |
| 2021 | 40.5% | 18.6% |
| 2022 | 2.4% | 1.2% |
| 2023 | 8.2% | 4.0% |
| 2024 | 13.4% | 6.5% |
| 2025 | 5.1% | 2.5% |
| 2026 (to Sept) | 1.6% | 0.8% |

Max drawdown -1.7% (on notional), 91% of months positive, worst 30 days -1.5%. Funding was negative on 12% of
days, the longest negative run 16 days. The declared 7-day funding filter did worse (11.9% a year, 80% positive
months).

## MEXC, 2025-05 to 2026-10

3.3% a year on notional, 1.6% on capital (MEXC spot history covered only 271 of the 539 days). The filter did
worse (1.0%).

## Reading

The income is real and steady: it never lost more than about 2% from a peak in almost seven years. But it is
large only in strong bull markets (2020 to 2021) and has shrunk to about 1% to 2.5% a year on capital in 2025 to
2026. At today's funding levels it earns less than a cash or stablecoin savings rate, so it is not worth running
with real money now. The paper tracker `carry-forward-v1` (from 2026-10-24) records what it earns from here on.
