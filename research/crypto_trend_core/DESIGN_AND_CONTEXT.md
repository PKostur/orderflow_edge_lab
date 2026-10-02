# crypto-trend-core-v1: design and disclosed context

Registered in `7875591` (forward start 2026-09-29). The candidate focuses on
the demonstrated strength: a crypto trend premium carried by DON8 and EMA8.

| Choice | Basis |
| --- | --- |
| DON8 + EMA8; VOL8 dropped | VOL8 was weakest in every dataset (post-evidence choice, disclosed) |
| 17 coins | 10 development coins + 7 untouched-holdout coins (post-evidence choice, disclosed) |
| Entry inverse-vol sizing at 15%, cap 1 | Fixed a priori; no leverage |
| v3.1 accounting with funding, 20 bps | Funding cost 11%/yr in 2021; 20 bps is conservative per the order-book snapshot |

## Disclosed context (computed after registration; every part of this data has been seen)

Over 2020-06 to 2026-09 on the same design, with no funding before 2025:

| Sharpe | t | Max drawdown | Cumulative |
| ---: | ---: | ---: | ---: |
| 1.31 | 3.10 | −12.5% | +186% |

By year: 2020H2 +4%, 2021 +80%, 2022 −0.3%, 2023 +12%, 2024 +15%, 2025 +11%,
2026 YTD +7%.

**Calibration of the 180-day gate.** Across 69 rolling 180-day windows, the
mean was positive in 75% of them and a −25% drawdown occurred in none. Even if
the historical edge persists, the gate has roughly a 1-in-4 chance of failing
by chance. A failed 180-day gate is therefore "not yet", not "no"; a pass is
"eligible for the paper and approval gates", not "proven".

## What would count as real evidence

The forward stream plus any future untouched data (for example, newly listed
coins that meet the mechanical rule). At the context Sharpe of about 1.3,
detection at t = 2 needs roughly 2.4 years of forward data.
