# Initial ENA/BTC trading-session diagnostic

Date: 2026-09-22

## Data

* Venue/source: Binance USDT perpetual futures, used as a 24-hour market-behavior diagnostic.
* Symbols: ENAUSDT and BTCUSDT.
* Bars: 15 minute.
* Window: 2026-09-08 00:00 UTC <= timestamp < 2026-09-22 00:00 UTC.
* Sample: 14 fully completed 24-hour days.
* Important: this is not MEXC execution evidence and not a strategy backtest. Venue-specific order flow can differ.

Session definitions use the DST-aware defaults in `session_metrics.py`.

During this September window the equivalent UTC coverage is:

* Asia: 00:00-09:00 UTC.
* London: 07:00-16:00 UTC because London is on BST.
* New York: 12:00-21:00 UTC because New York is on EDT.

## Session membership metrics

Membership metrics include overlap bars in each named session.

### ENA

| Session | Avg return | Median return | Positive days | Avg range | Realized vol | Avg volume |
|---|---:|---:|---:|---:|---:|---:|
| Asia | +243.96 bps | +121.94 | 64.3% | 676.00 | 376.45 | 538,538,969 |
| London | +99.59 bps | +89.69 | 64.3% | 707.98 | 430.46 | 699,771,962 |
| New York | +28.86 bps | +1.82 | 50.0% | 800.65 | 468.65 | 754,579,690 |

### BTC

| Session | Avg return | Median return | Positive days | Avg range | Realized vol | Avg volume |
|---|---:|---:|---:|---:|---:|---:|
| Asia | +44.35 bps | +32.89 | 64.3% | 159.10 | 86.19 | 42,199 |
| London | +73.36 bps | +46.96 | 71.4% | 230.45 | 123.79 | 76,231 |
| New York | +44.99 bps | +8.31 | 57.1% | 230.23 | 129.35 | 80,941 |

## Exclusive regime metrics

These remove overlap double-counting.

### ENA

| Regime | Avg return | Median | Positive days | Avg range | Realized vol |
|---|---:|---:|---:|---:|---:|
| Asia only | +132.55 bps | +81.46 | 64.3% | 592.71 | 340.81 |
| Asia + London | +107.84 | +77.32 | 64.3% | 287.09 | 139.58 |
| London only | -29.34 | -74.01 | 28.6% | 338.53 | 196.32 |
| London + New York | +21.99 | +79.78 | 57.1% | 552.47 | 321.71 |
| New York only | +8.80 | -56.74 | 50.0% | 580.22 | 303.95 |
| Off-session | -36.79 | -4.29 | 35.7% | 315.47 | 182.03 |

### BTC

| Regime | Avg return | Median | Positive days | Avg range | Realized vol |
|---|---:|---:|---:|---:|---:|
| Asia only | +19.69 bps | +28.12 | 71.4% | 119.88 | 72.18 |
| Asia + London | +24.37 | +10.43 | 64.3% | 81.07 | 40.05 |
| London only | +4.59 | -1.79 | 42.9% | 77.45 | 47.13 |
| London + New York | +43.68 | +43.05 | 71.4% | 185.63 | 99.84 |
| New York only | +1.07 | -12.92 | 50.0% | 130.34 | 71.16 |
| Off-session | -26.99 | -16.19 | 28.6% | 78.28 | 43.31 |

## Initial conclusions

### 1. New York is a volatility/liquidity state, not automatically a directional state

ENA has its highest named-session range, realized volatility and volume during New York, yet its average and median directional return are much smaller than Asia.

BTC shows a similar distinction: New York range and realized volatility are high, but New-York-only directional drift is close to zero.

This matters because a continuation strategy and a mean-reversion strategy may react very differently to the same "high volatility" session label.

### 2. ENA directional behavior was strongest earlier in the global day

In this 14-day sample, ENA Asia-only and Asia-London overlap had materially stronger positive average and median returns than London-only or New-York-only.

This is a candidate explanation for why some ENA setups travel farther than others, but it is period-specific and must not be turned into an Asia-only strategy from this inspected sample.

### 3. BTC's strongest directional regime was the London-New York overlap

BTC London-New-York overlap had +43.68 bps average session return, +43.05 bps median, and 71.4% positive days. London-only and New-York-only were much less directional.

That suggests BTC context may be especially informative during the overlap, when both major Western liquidity centers are active.

### 4. ENA and BTC do not have identical session structure

ENA's strongest directional behavior appears earlier, while BTC's clearest directional regime is London-New-York overlap.

Therefore a future ENA strategy filter should probably not use "BTC session is strong" as a simple universal proxy. More useful conditioning could test:

* ENA session regime;
* BTC session regime;
* BTC direction/alignment inside that regime;
* whether ENA is moving with or independently from BTC.

### 5. Existing ETF H1/H2 cannot answer this question

Every exact historical filtered ETF signal is in `LONDON+NEW_YORK`:

* H1: 41 / 41.
* H2: 25 / 25.

That is expected because the strategies search shortly after the US cash open.

## Next test

Do not freeze a session filter yet.

The next meaningful experiment is to stratify the existing MEXC order-flow signal families by the new `trading_session_regime` and accumulate multiple independent capture batches in each regime.

For each family x session x horizon x fee combination, track:

* observations and independent batches;
* cumulative net bps;
* mean EV;
* win rate;
* payoff ratio;
* profit factor;
* max drawdown;
* positive-batch fraction;
* spread/range/flow context.

Only after repeated session-specific strategy economics appear should a session-conditioned candidate be frozen for forward testing.
