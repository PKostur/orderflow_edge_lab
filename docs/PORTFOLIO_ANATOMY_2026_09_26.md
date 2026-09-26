# Portfolio anatomy and breadth options (2026-09-26)

Scope: the combined DON8/EMA8/VOL8 portfolio, with equal capital across 30
strategy × coin sleeves under canonical v3 at 20 bps. Window: the frozen
2024-01-01 to 2026-09-12 period, already inspected, so descriptive only.
Reproduce with `python scripts/portfolio_anatomy_2026_09_26.py artifacts/data/8h`.
Nothing here selects parameters; it decides where breadth should come from.

## Headline

| | Value |
| --- | ---: |
| Net Sharpe (gross) | 1.07 (1.25) |
| Annualized return / volatility | 40.5% / 37.8% |
| Cost drag | 6.6%/yr, of which VOL8 contributes 5.2 points (its sleeve-level drag is 15.6%/yr) |
| Funding drag (crypto, 2025-04 onward) | 0.6%/yr (Sharpe 1.07 → 1.05) |
| Daily skew / excess kurtosis | +0.31 / 4.8 |
| Average net / gross exposure; share of days net long | −0.05 / 0.81; 44.5% |

## Strengths

1. **Convex payoff, the classic trend "smile".** Mean monthly return by quintile
   of the basket's monthly return: worst +8.1%, q2 −5.1%, q3 −0.9%, q4 −3.8%,
   best +16.9%. It earns in both extreme up and extreme down markets and bleeds
   in quiet ones.
2. **Both sides pay under v3.** Long-side Sharpe is 1.86 and short-side 1.29.
   Exposure is directionless on average (net −0.05), so this is not beta.
3. **It held up when the market fell.** In 2025 the basket returned −34.8% and
   the portfolio +13.8%; in 2026 to date the basket is −24.1% and the portfolio
   +18.3%.
4. **Signals diversify coins.** Mean sleeve correlation is 0.29, against 0.68
   for the raw coins.

## Weaknesses

1. **Extreme concentration in a few trades.** Of 2,647 trades, the top 1% (26
   trades) produce 102% of net P&L and the top 5% produce 201%. Without them the
   book is deeply negative. The evidence therefore rests on about 26 events.
   This is typical of trend following, but it is also why significance takes
   years.
2. **Deep, long drawdowns at high volatility.** The worst drawdowns were −30%
   (346 days, 2024-12 to 2025-11), −25% (242 days) and −18% (196 days), with
   volatility at 38% a year. Positions are ±1 unit regardless of each coin's
   volatility, so risk goes to the most volatile coins.
3. **Coin concentration follows from that.** DOGE, ENA and SUI produce 53% of
   P&L; BTC and BNB produce 9%. That is risk allocation by volatility, not
   evidence that meme coins trend better.
4. **Time concentration.** 2024 had a Sharpe of 1.75; 2025 had 0.53.
5. **VOL8 mainly adds cost.** It makes 778 trades a year, has a 15.6% annual
   sleeve cost drag, the lowest Sharpe of the three (0.72) and a 24.5% P&L
   share.
6. **Diversification thins under stress.** Sleeve correlation rises from 0.29
   to 0.37 on the worst basket-decile days.
7. **Fat tails.** The worst day was −11.1% (2025-03-03). Monthly returns
   correlate 0.58 with the basket through the convexity, even though daily beta
   is about 0.
8. **Breadth.** The book amounts to roughly 2 independent assets (see
   `FIRST_PRINCIPLES_EVIDENCE_RATE_2026_09_26.md`).

## Broadening option: MEXC tradfi perpetuals

MEXC lists about 430 tradfi-zone USDT perpetuals: FX, metals, energy, broad
indices, ETF proxies and single stocks. Nearly all were listed in 2026, so there
is no long historical backtest, but that is enough for forward evidence (the
rules need about 35 days of warm-up).

**Breadth.** Over the 154-day overlap, crypto alone is 1.74 effective bets;
adding the 29 FX, commodity and index perps gives 5.5. Each adds +0.2 to +0.3.

**Liquidity** (24h turnover). Only XAUT (97M), SILVER (100M), USOIL (37M),
UKOIL (28M), SPX500 (44M) and NAS100 (12M) are material. EWY is 2.6M and
QQQSTOCK 1.2M; FX, base metals and most indices are under 1M, where the 20 bps
cost assumption is not credible.

**Funding is first-order and currently unmodeled.** From MEXC funding history:

| Contract | Annualized mean \|funding\| | Signed (long pays when +) |
| --- | ---: | ---: |
| XAUT | 11.7% | +5.2% |
| SILVER | 25.9% | +18.3% |
| USOIL / UKOIL | 60.8% / 53.4% | −21.4% / −23.9% |
| SPX500 / NAS100 | 21.4% / 10.0% | −18.5% / −4.4% |
| COPPER / NGAS | 32.2% / 83.7% | +19.9% / +51.3% |
| EUR / JPY / GBP / AUD | 14.5% / 32.8% / 16.0% / 20.9% | +2.5% / +2.4% / +1.4% / +6.4% |

These magnitudes exceed any plausible trend premium in these markets.
Canonical v2 and v3 charge no funding. For crypto that costs about 0.6%/yr, but
for tradfi perps it would decide the result.

## Implications (ordered)

1. **Accounting v3.1 must include funding** before any cross-asset protocol:
   position × rate at each settlement, from MEXC history, with fixed quantity
   between target changes as in v3. Without it, any tradfi result is
   meaningless.
2. **A cross-asset forward universe, chosen by rule, not by P&L:** tradfi FX,
   commodity or broad-index perps; no leveraged, inverse or single-stock
   contracts; listed at least 90 days; 24h turnover of at least 10M USDT; one
   contract per underlying. Today that gives XAUT, SILVER, USOIL, SPX500 and
   NAS100. Scored on daily P&L under v3.1 with the same frozen rules.
3. **Risk-based sizing** (inverse-volatility sleeves), pre-registered as a
   forward variant beside, not instead of, the ±1 book. It is the a-priori fix
   for coin concentration and drawdown depth and is standard managed-futures
   practice, not derived from this P&L.
4. **VOL8's turnover** is a weakness to watch forward; it is not to be retuned.
