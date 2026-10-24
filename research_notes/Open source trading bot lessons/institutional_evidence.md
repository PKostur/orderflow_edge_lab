# Institutional and academic evidence on systematic crypto strategies (calibration baseline)

Notes dated 2026-10-09. All findings come from web search summaries and a few page fetches. Several primary PDFs failed to load (JFQA PDF 404, Wasa repository refused, IRFA 403), so many paper-level numbers are abstract-level only. Treat every figure as a claim unless marked otherwise.

## Q1. What do crypto CTA/trend indices, funds and academic trend studies report (2018-2026)? How do they size and diversify?

### Takeaway
I found no audited crypto-CTA index or named fund track record with Sharpe and drawdown. The best evidence is academic: Zarattini-Pagani-Barbon report a net Sharpe above 1.5 for a Donchian ensemble on the top-20 liquid coins. Traditional CTAs were weak in 2024-25, with a 20% peak-to-trough drawdown in the SG Trend Index. Our ~1 Sharpe on consistent venues is therefore not out of line with a realistic professional baseline.

### Cited Findings
- "Catching Crypto Trends" (Zarattini, Pagani, Barbon; last revised 2025-04-09) combines several Donchian-channel models with different lookbacks into one signal and adds volatility-based sizing. The rotational top-20 liquid-coin portfolio shows a net-of-fees Sharpe above 1.5 and annualized alpha of 10.8% versus Bitcoin. The abstract does not give a maximum drawdown or the end of the sample. This is a backtest claim, not a live record. — [Barbon page](https://abarbon.com/papers/catching-crypto-trends)
- Its universe is coins listed at least a year since 2015 with median daily volume of at least $2m over the prior 30 days. The paper says it assesses transaction costs and proposes a portfolio technique to reduce them. — [search summary of paper/IDEAS](https://ideas.repec.org/p/chf/rpseri/rp2580.html), [Concretum](https://concretumgroup.com/catching-crypto-trends-a-tactical-approach-for-bitcoin-and-altcoins/)
- "A Decade of Evidence of Trend Following Investing in Cryptocurrencies" tests vanilla trend on Bitcoin with Sharpe-optimized parameters, using data from Sept 2011 to Dec 2019. The sample ends before 2022 and the headline figures were not retrieved. — [arXiv 2009.12155](https://ar5iv.labs.arxiv.org/html/2009.12155)
- Lionsoul (Gregory Mall), a single-author 60/40 backtest from Jan 2021 to Mar 2026, swapped spot BTC for a BTC/cash trend sleeve. A Binance Square repost reports 14.2% annualized and Sharpe 0.84, versus 11.8% and 0.71 for a static 5% BTC allocation. It assumes 15 bps per round trip. The source is non-institutional and secondary. — [Binance Square repost](https://www.binance.com/de/square/post/352480327447329)
- The Talyxion arXiv preprint reports Sharpe 3.02 against 1.71 for buy-and-hold on Binance futures daily data (Jan 2023 to Aug 2025). It is a short sample and not peer reviewed. — [arXiv 2511.13239](https://arxiv.org/pdf/2511.13239)
- An unverified Substack note cites "AdaptiveTrend" with Sharpe 2.41 and max drawdown about 12.7% over 36 months (2022-2024). The figures are from a social-media summary, not the paper. — [Substack note](https://substack.com/@quantitativo/note/c-216039933)
- Traditional CTA context (not crypto): the SG Trend Index fell 20.4% from May 2024 to May 2025, its second-largest drawdown since 2000. It has had 16 drawdowns above 10% since 2000, roughly every 18-24 months. — [Cambridge Associates](https://www.cambridgeassociates.com/insight/does-trend-followings-recent-struggle-signal-that-the-strategy-is-structurally-broken/)
- SG Trend Index: +2.6% in 2024, then about -4.5% in Q1 2025. — [Connect Money](https://www.connectmoney.com/?p=23503) (secondary source)
- SG CTA Index: -2.52% in Q1 2025 and a 2022 gain of 20.1%. — [Full FX](https://thefullfx.com/ctas-tough-start-to-2025-continues/), [Risk.net](https://risk.net/asset-management/hedge-funds/strategy/2299487/cta-trend-followers-suffer-in-market-dominated-by-intervention). The Risk.net snippet is ambiguous on dates.
- Crypto hedge fund indices are the only fund-level crypto numbers I found. HFR Cryptocurrency Index: +51.4% annualized, 59.5% annualized volatility over the 5 years to Feb 2025 (return/vol about 0.86, my arithmetic), and +59.8% in 2024. This is a mostly long-biased index, not a CTA index. — [Full FX on HFR](https://thefullfx.com/hfr-expands-crypto-fund-performance-data/)

### Inferences
- A defensible calibration band for a live, net, diversified crypto trend program is Sharpe about 0.8-1.5. The top is the academic backtest (Barbon, over 1.5), and the bottom is the simple trend-sleeve backtest (0.84). Preprint Sharpes of 2-3 are most likely short-sample or overfit.
- Trend in a single asset class should expect multi-year drawdowns. The traditional CTA record (20% drawdown, 16 drawdowns above 10% since 2000) is a useful prior for how long a flat or negative stretch can last even without decay.
- The sizing approach in the Barbon paper (ensemble of lookbacks, volatility sizing, liquidity-filtered top-20) matches what the team's DON8+EMA8 core already does in spirit.

### Gaps
- No crypto CTA index (for example CF Benchmarks or S&P crypto trend) and no named crypto trend fund track record with Sharpe or drawdown. The searches did not surface any.
- No Man AHL, Winton or AQR crypto-sleeve performance disclosure was found.
- The Barbon paper's drawdown, sample end date and cost figures need the full PDF.
- Capacity numbers for crypto trend were not found.

## Q2. Which cross-sectional factors survive out of sample, after publication and costs, in liquid universes?

### Takeaway
Momentum (and a combined trend/technical factor, CTREND) is the family with the best net-of-cost and large-cap support. Size and volume effects come from micro-caps and are not tradable. Momentum in larger coins is costly, concentrated in the short leg and in bull markets, and fades. Momentum is also prone to crashes, which volatility scaling reduces. Direct post-publication decay tests are thin.

### Cited Findings
- Liu-Tsyvinski-Wu, "Common Risk Factors in Cryptocurrency" (NBER w25882, 2019; Journal of Finance per SSRN and a Chinese database, with conflicting venue listings). The sample is 2014-2018 with coins above $1m market cap, sorted into weekly quintiles. A three-factor model of market, size and momentum explains the cross-section, and nine factor strategies earn significant gross returns. — [NBER](https://www.nber.org/papers/w25882.pdf), [SSRN](https://papers.ssrn.com/abstract=3379131)
- CXO Advisory's summary of that paper cautions that weekly rebalancing of illiquid coins may be very costly, and says momentum is much stronger among large-cap coins than small-cap. — [CXO](https://cxoadvisory.com/size-effect/cryptocurrency-factor-model)
- Fieberg, Liedtke, Zaremba (IRFA 94, 2024, "Cryptocurrency anomalies and economic constraints") report that size and volume anomalies come from micro-caps of negligible economic importance. Momentum exists in larger coins but is expensive to trade and draws most alpha from short positions. Most abnormal returns occur in bull markets and fade over time. — [ICM repository](https://open.icm.edu.pl/handle/123456789/25544) (abstract only)
- Fieberg et al., CTREND (JFQA 60(7), Nov 2025). A machine-learning aggregate of technical indicators on price and volume, using over 3,000 coins. The abstract says it survives transaction costs, persists in large and liquid coins, is robust across subperiods and market states, and is not subsumed by known factors. No Sharpe or cost figures were retrievable. — [Cambridge Core](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178)
- Mercik, Zaremba, Demir (IRFA 2026) test 36 factors over Jan 2018 to Jul 2024. Two to three factors eliminate all significant alphas, and liquidity-related variables dominate selection. — [ICM repository search summary](https://open.icm.edu.pl/bitstreams/21636cf6-61df-4fb5-9ae4-4195d592cd26/download)
- A related factor-sparsity paper says trading frictions narrow which factors are exploitable and that momentum is more resilient to rising costs than others. The factor rankings it finds shift across periods, and the later sample favors conventional liquidity and momentum measures. — [same ICM source](https://open.icm.edu.pl/bitstreams/21636cf6-61df-4fb5-9ae4-4195d592cd26/download) (search-summary level)
- Mercik et al. (IRFA 2025, "Cross-sectional interactions") use double sorts on 40 characteristics for more than 500 coins over 2017-2023. The strongest interactions combine liquidity, risk and past-return measures, and a long-short pick of the top and bottom interactions gets Sharpe above 1. This is a data-mined selection, so treat it with caution. — [ICM](https://open.icm.edu.pl/items/e5ccfa8d-15c9-4845-b7b2-8d060dd46503/full)
- Grobys et al. (Financial Markets and Portfolio Management, 2025, "Cryptocurrency momentum has (not) its moments") use weekly data for the 30 largest coins, 2016-2023. Momentum suffers severe crashes and results can hinge on a single coin. Volatility management limits the crashes, and the effect is concentrated in large caps. — [Springer](https://link.springer.com/article/10.1007/s11408-025-00474-9)
- A study quoted in a search summary finds that, after costs and daily price swings, many significant momentum portfolios earn insignificant profits. It reports time-series momentum as strong and cross-sectional momentum as weak. The specific paper was not identified. — [search summary of ICM/Transfer Ranking items](https://arxiv.org/pdf/2208.09968)
- Another ranking paper assumes 26 bps per trade and reports cost-adjusted Sharpe staying positive up to about 29 bps. — [arXiv 2208.09968](https://arxiv.org/pdf/2208.09968)
- Early momentum studies disagree. Grobys-Sapkota (2019) found no support using monthly data for 2014-2018; others find short-horizon momentum only. — [Springer review](https://link.springer.com/article/10.1007/s11408-025-00474-9)
- An Erasmus thesis (2022) finds most of 25 momentum strategies not significant and unable to beat holding BTC or Tether. A student thesis is low quality evidence. — [thesis](https://thesis.eur.nl/pub/63243/Thesis_Pieter_Bakker_503875.pdf)
- CF Benchmarks' Q1 2026 factor report uses seven factors: market, size, value, momentum, growth, downside beta and liquidity. Market, growth and downside beta have the strongest explanatory power. This is a risk-model report, not a net trading test. — [CF Benchmarks](https://cfbinfo.cfbenchmarks.com/hubfs/Files%20-%20CF%20Benchmarks/Keep_Factor%20Reports/Q1%202026_New%20Logo%20Quarterly%20Factor%20Report.pdf)

### Inferences
- For the team's XS momentum sleeve, the literature suggests restricting to liquid coins, expecting the short leg to carry much of the alpha, and expecting the premium to be regime-dependent (bull markets). A Sharpe fall from 2.09 to about 1 is consistent with the "fade over time" and "bull-market dependence" findings. This is an inference, not a test.
- Volatility-scaled momentum is supported (Grobys) and is a family the team lists but may not have tested on its own.
- The liquidity factor recurs in the sparsity papers, but whether it is tradable after costs (liquidity premia are usually in illiquid coins) is not established by what I retrieved.

### Gaps
- No clean post-publication comparison (factor returns before and after the 2019 paper) was found. Decay evidence is indirect (fade over time, bull-market dependence).
- No net-of-cost long-short Sharpe numbers for size, reversal, value/network or volatility factors in liquid universes were retrievable.
- Primary PDFs for CTREND, Grobys and Fieberg 2024 were not read; only abstracts and summaries.
- Short-term reversal and value/network factors: nothing reliable found.

## Q3. What happened to basis and funding strategies in 2022-2026 (compression, Ethena-type products, 2022 blowups)?

### Takeaway
Basis and funding yields are large but regime-dependent. They compressed toward the risk-free rate by 2025-26, and funding can turn negative in stress. The 2022 blowups I found (3AC, Alameda) were leverage and governance failures, not clean basis-strategy failures, and I found no source on 2022 market-neutral fund losses.

### Cited Findings
- BIS Working Paper 1087 "Crypto carry" (Schmeling, Schrimpf, Todorov; April 2023, revised Oct 2025). Carry averages above 10% a year and reaches 60% at peaks (the search snippet said 40%, the fetched BIS page said 60%). It is driven by trend-chasing retail leverage demand and limited arbitrage capital, and high carry predicts crashes. Cash-and-carry positions are risky because margins spike and positions get liquidated in drawdowns. — [BIS](https://www.bis.org/publ/work1087.pdf), [BIS page](https://bis.org/publ/work1087.htm)
- CME bitcoin basis: annualized yields were double-digit after the Jan 2024 ETF approvals, then compressed. One-month annualized basis was about 17% a year earlier and near 4.7-5% in early 2026, about the risk-free rate. CME open interest fell below $8bn in March 2026 and to about $7.2bn in early April, the lowest since Feb 2024. Reported benchmarks conflict (4.5% versus 3.5%). — [Advisor Perspectives (Amberdata data)](https://www.advisorperspectives.com/articles/2026/01/22/wall-street-pulls-back-bitcoin-trade), [crypto.news](https://crypto.news/cme-bitcoin-futures-slump-as-basis-trade-unwinds-and-wall-street-steps-back/)
- CF Benchmarks says basis is driven by momentum and sentiment, widening in rallies and compressing after declines. — [CF Benchmarks](https://www.cfbenchmarks.com/blog/revisiting-the-bitcoin-basis-how-momentum-sentiment-impact-the-structural-drivers-of-basis-activity)
- Ethena sUSDe: average APY fell from about 8% to about 3.5% after the 10 Oct 2025 liquidation event. Blockworks argues the decline is structural, with each bull period since the early-2024 ETF launch giving lower delta-neutral returns. TVL dropped from a $16.6bn peak (Sept 2025) to $5.6bn, with about $1.9bn of redemptions in 48 hours. — [Blockworks](https://blockworks.com/newsletter/the-breakdown/issue/post_999b16ee-0fe0-4631-a1d0-2aa15a1d18a7), [Eco explainer](https://eco.com/support/en/articles/15002228-ethena-susde-vs-usde-yield-mechanism-explained) (the latter is a promotional or support page)
- A Coin Metrics-based blog cites funding averaging about 11% APY across 2023-2025, which conflicts with the 3.5-4.5% recent sUSDe yields above. The two windows differ. — [Ryder blog](https://ryder.id/blogs/post/ethena-usde-how-synthetic-dollars-pay-15-yield), [Blockworks](https://blockworks.com/newsletter/the-breakdown/issue/post_999b16ee-0fe0-4631-a1d0-2aa15a1d18a7)
- Ethena's founder says average 2022 funding was about zero, with a worst stretch near -3% for about a week. This is a retrospective claim by the product's founder. — [Coin Metrics Substack](https://coinmetrics.substack.com/p/state-of-the-network-issue-335)
- Funding turned negative around Luna/3AC, FTX (Nov 2022) and Oct 2025. In an April episode (year not confirmed by the source) USDe briefly traded at $0.995, and Ethena capital deployed in market-neutral strategies fell from $2bn to $800m within a month. — [Forklog](https://forklog.com/en/ethenas-capital-plunge-signals-long-demand-shortage/)
- 2022 blowups: Three Arrows Capital failed after a leveraged Terra/Luna position, and a case study frames it as an operational due diligence failure. Alameda's collapse was tied to FTX commingling allegations. Neither was a plain basis-strategy failure. — [HBR case](https://store.hbr.org/product/three-arrows-capital-a-crypto-hedge-fund-failure-and-operational-due-diligence-lessons/HK1439), [Blockworks](https://blockworks.com/news/crypto-trading-blowups-2022)
- One source on Ethena says it extended the basis strategy to equity perpetuals, where funding averaged about 14% on Hyperliquid and 17.5% on Binance. This is a claim from a secondary source. — [Stock3](https://stock3.com/news/ethena-diversifies-beyond-crypto-in-search-of-higher-yields-17018706)

### Inferences
- Funding carry is crowded and sentiment-linked: yield is highest when leverage demand is highest, which is also when crash risk (BIS) is highest. A realistic forward expectation for pure carry is a low single-digit spread over cash with fat left-tail and margin risk, not the double-digit historical average.
- The repo's finding that funding carry was a venue-mismatch artifact fits the BIS and CME evidence that apparent carry depends on venue, margin and financing details. Consistent-venue carry should be treated as close to a cash-plus return.

### Gaps
- No source on 2022 market-neutral or basis fund losses (Celsius, Babel Finance, the stETH discount) was retrieved.
- No fund-level Sharpe or drawdown for basis funds. BIS Sharpe and sample-period details were not in the retrievable text.
- Capacity: only CME open interest and Ethena TVL figures as proxies.
- The "April" negative-funding episode year is unconfirmed.

## Q4. Which other families have credible out-of-sample support (and what does each depend on)?

### Takeaway
Only technical/trend-aggregate cross-sectional signals (CTREND), volatility-managed momentum and time-series trend have credible published support in what I retrieved. I found nothing credible and citable for Fear and Greed, pairs, session effects, regime switching or mean reversion.

### Cited Findings
- Volatility-managed momentum reduces crash severity in the largest 30 coins, 2016-2023. — [Springer](https://link.springer.com/article/10.1007/s11408-025-00474-9)
- CTREND (price/volume technical aggregate, over 3,000 coins) is a cross-sectional trend signal reported to survive costs and large-cap subsets. — [Cambridge Core](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178)
- Factor momentum (past winning factors keep winning) in crypto: Quantitative Finance 2023, with only an abstract-level mention retrieved. — [ICM](https://open.icm.edu.pl/handle/123456789/25542)
- Time-series momentum is reported as stronger than cross-sectional momentum after costs. — [search summary](https://arxiv.org/pdf/2208.09968)
- Mean reversion: one high-frequency study found negative returns for relative-strength rules, suggesting contrarian effects at short horizons. The study was not identified. — [search summary](https://arxiv.org/pdf/2208.09968)

### Inferences
- Candidates the team has not tested that have some published backing: a CTREND-style multi-indicator aggregate on liquid coins, a factor-momentum overlay, and volatility-scaled XS momentum. The evidence-rate rule in the repo's CLAUDE.md blocks new trend variants on the same coins, so these would need new assets or daily-P&L scoring.
- Intraday reversal could be real but is unconfirmed here.

### Gaps
- Nothing reliable found for Fear and Greed sentiment, pairs trading, session effects, regime switching or breakouts beyond Donchian trend.
- No independent replication of CTREND or the Liu-Tsyvinski-Wu factors on post-2021 data was found.
- Not searched specifically: a short-term reversal factor in liquid crypto and the network/value (NVT) factor. Both remain unverified here.
