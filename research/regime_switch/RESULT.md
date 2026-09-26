# Regime switch (trend following vs mean reversion): result

- Protocol: `regime-switch-trend-meanrev-v1`, declared in `cb3a97f` before evaluation
- Regime: the frozen v1 efficiency-ratio label
- Mean reversion: textbook Bollinger(20, 2σ) with RSI(14) at 30/70
- Sizing and accounting: inverse-vol sizing, canonical v3, no funding
- Status: descriptive, on seen data

## Crypto (17 perps, 8h, 2020-2026; TREND 34%, MIXED 30%, CHOP 36% of bars)

| Variant | Sharpe | t | Max drawdown | Mostly-CHOP days | Other days |
| --- | ---: | ---: | ---: | ---: | ---: |
| trend_only | 0.89 | 2.12 | −11.0% | +2.2 bp | +2.9 bp |
| chop_filter | 0.73 | 1.73 | −7.9% | +0.8 bp | +2.1 bp |
| switch | 0.67 | 1.59 | −9.2% | +0.7 bp | +2.0 bp |
| meanrev_only | −1.05 | −2.66 | −32.1% | −0.8 bp | −2.3 bp |

## ETFs (daily, 2009-2026; contaminated)

trend_only −0.22 · switch −0.20 · chop_filter −0.20 · meanrev_only 0.00

## Reading

1. Mean reversion loses in crypto, and does so significantly, even on
   CHOP-labelled days. On 8h bars crypto continues rather than reverts.
2. The regime label has no predictive value for the next day's trend P&L.
   Trend following still earns +2.2 bp a day on CHOP days, because the label
   lags the market. Switching or filtering in CHOP gives up profitable exposure.
3. The chop filter lowers drawdown only by holding less.
4. Decision: keep the trend-only core. Do not add regime switching or this
   mean-reversion component.

## Limits

One mean-reversion specification and one regime definition were tested, on
seen data. A regime approach that anticipates rather than lags the market
would need a different information source (for example order flow, funding or
open interest) and its own pre-registration.
