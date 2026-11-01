# Round 1: published crypto strategies with non-price signals

Scope note: the search found almost no fully specified, codable strategy in this category. One candidate (ETF flow sign) is fully specified but weak. The rest are partial and fail the "published parameters" rule as far as I could verify. No backtests were run. About 20 tool calls were made. Several primary documents (HKUST report, Vaasa thesis PDF, Farside, SMU page, Wiley page) could not be fetched (403, 404, ECONNREFUSED or empty), so those items rest on search snippets and secondary pages.

## Which published, fully specified non-price crypto strategies exist (excluded categories removed)?

### Takeaway
Only one candidate has an exact published rule: the Bitcoin Magazine Pro daily ETF-flow sign rule. It is a commercial blog backtest of about 15 months, with look-ahead timing problems. Others are partially specified at best (MVRV-Z/NUPL, Grayscale premium, basis factor). DVOL/VRP, Coinbase premium, open interest/long-short ratio, stablecoin supply and skew produced no published trading rule with parameters.

### Cited Findings

#### Candidate 1: ETF flow sign rule (fully specified)
```json
{
  "id": "C1",
  "name": "Bitcoin Magazine Pro: follow the daily spot-BTC-ETF net flow sign",
  "source_url": "https://bitcoinmagazine.com/markets/bitcoin-etf-flow-strategy-beats-buy-and-hold",
  "source_date": "2025-04-04 (author Matt Crosby, Bitcoin Magazine Pro lead analyst)",
  "traded_asset": "BTC (spot implied; the article does not state spot vs perp)",
  "signal_data": "Daily aggregate US spot BTC ETF net flow in USD. The article uses Bitcoin Magazine Pro's paid-site series. A free substitute is the Farside Investors table https://farside.co.uk/btc/ (could not be fetched: HTTP 403; earliest date 2024-01-11 as the first ETF trading day, not verified). Equivalence of Farside to the BM Pro series is unverified.",
  "signal": "flow_t > 0 -> long; flow_t < 0 -> flat (cash assumed; article does not say explicitly). No smoothing, lookback or threshold other than sign zero.",
  "holding/rebalance": "Trade at daily close when sign changes. Position persists while sign is unchanged.",
  "sizing": "100% of portfolio when long, no leverage",
  "parameters": {"threshold_usd": 0, "lookback": "none", "leverage": 1.0, "initial_entry": "2024-01-11 at ~46,434 USD"},
  "publication_lag_handling": "None stated. Trade is assumed at the same day's close as the flow. ETF flows are published after the US close (Farside publishes the next morning), so this is look-ahead. For a codable version the flow of day t can only drive a position from the close of day t+1 or later; the source's own execution cannot be reproduced exactly.",
  "source_sample": "2024-01-11 to end of March 2025",
  "reported_performance": "Strategy +118.5% vs buy-and-hold +81.7% over the sample. In-sample, single period, no costs, drawdown, Sharpe or tax figures given.",
  "post_publication_evidence": "None found. The same-family Nasdaq syndication notes most flows are trend-confirming rather than predictive (secondary, no data seen).",
  "known_weaknesses": "Author's employer sells the data. ~15 months sample. Same-day look-ahead. No costs. Sell leg undefined (cash vs short). Flows correlate with same-day price, so edge may be contemporaneous momentum."
}
```
- Rule, dates, entry price, 118.5% vs 81.7% and absence of costs: [Bitcoin Magazine](https://bitcoinmagazine.com/markets/bitcoin-etf-flow-strategy-beats-buy-and-hold); same rule restated at [LookIntoBitcoin](https://www.lookintobitcoin.com/bitcoin-research/front-running-institutions-beating-btc/).
- The same search showed a Nasdaq-syndicated Bitcoin Magazine piece saying most ETF flows are trend-confirming, and a second Bitcoin Magazine article (strategy-btc-buy-hold, ~200% vs ~155%) that I did not open; its rules are unread — [search result list](https://bitcoinmagazine.com/markets/bitcoin-etf-strategy-btc-buy-hold).

#### Candidate 2: On-chain NUPL / MVRV Z-score contrarian long (partially specified)
```json
{
  "id": "C2",
  "name": "Grobys, Nasman, Sandretto: NUPL / MVRV Z-score / CVDD rule-based Bitcoin cycle timing",
  "source_url": "https://osuva.uwasa.fi/items/d5993292-4a47-4162-89d7-7ddf676ba319/full (thesis record); journal: Research in International Business and Finance vol 89, DOI 10.1016/j.ribaf.2026.103486",
  "source_date": "2025 thesis; 2026 journal article",
  "traded_asset": "BTC",
  "signal_data": "NOT VERIFIED. Securities.io summary names no provider. MVRV needs market cap and realized cap; CoinMetrics community API (CapMVRVCur) is a possible free source but I did not verify this against docs. NUPL derived from realized cap likewise.",
  "signal": "Only vendor-style levels recovered: NUPL > 0.75 marks 'euphoria/top'; MVRV Z < -0.2 'fear'; MVRV Z ~5 to 7 exit zone. The exact entry/exit thresholds, holding windows and the 'most aggressive version' are NOT in what I could read.",
  "holding/rebalance": "unknown",
  "sizing": "unknown",
  "parameters": "UNKNOWN beyond the levels above; full text required",
  "publication_lag_handling": "unknown (realized-cap series are revised/recomputed; vintage not discussed in what I saw)",
  "source_sample": "2013-12-07 to 2025-04-12 (three cycles)",
  "reported_performance": "Sharpe 0.45 (buy-and-hold) -> 1.28 with MVRV Z-score rule; beats random entries in Monte Carlo. In-sample; thesis headline 'cumulative returns exceeding 326,000%' in strongest cases.",
  "post_publication_evidence": "None (published 2026).",
  "known_weaknesses": "Three cycles only. Thresholds likely chosen on the same history. Contrarian bottom signals evaluated on cycle bottoms identified in hindsight (CVDD). Not codable until the paper's rules are read."
}
```
- Thesis by Sebastian Nasman (Vaasa, 2025), NUPL, MVRV Z, CVDD, Monte Carlo, 326,000% figure; journal follow-up, Sharpe 0.45 to 1.28 — reported in a search summary of [OSUVA record](https://osuva.uwasa.fi/items/48a4f9df-03ca-4b96-9072-07b462b14dfa/full) and [Securities.io](https://www.securities.io/de/using-on-chain-data-predict-bitcoin-cycles/).
- Sample 7 Dec 2013 to 12 Apr 2025, NUPL > 0.75, MVRV Z < -0.2, exit zone 5 to 7, no explicit rules and no data provider named — [Securities.io](https://www.securities.io/de/using-on-chain-data-predict-bitcoin-cycles/).

#### Candidate 3: Grayscale (GBTC) premium change long-short (not usable)
```json
{
  "id": "C3",
  "name": "Huang, Lin, Lu, Sun: The Financialization of Cryptocurrencies, GBTC premium change signal",
  "source_url": "https://ink.library.smu.edu.sg/lkcsb_research/7447",
  "source_date": "2023-02 (SMU version); earlier HKU version also exists",
  "traded_asset": "BTC",
  "signal_data": "GBTC premium/discount to NAV. No free official history verified; GBTC converted to an ETF in Jan 2024, so the series ended as a premium signal.",
  "signal": "Change in GBTC premium predicts next-day BTC return; exact formula, thresholds not retrieved",
  "holding/rebalance": "daily long-short (details unread)",
  "sizing": "unknown",
  "parameters": "unknown",
  "publication_lag_handling": "unknown",
  "source_sample": "unknown",
  "reported_performance": "Daily alpha 40 bps (2023 version) vs 90 bps (earlier HKU version); transaction costs may offset it. In-sample.",
  "post_publication_evidence": "none found",
  "known_weaknesses": "Instrument no longer trades as a premium vehicle; version-to-version alpha shrank 90 to 40 bps; parameters not found. Recommend dropping."
}
```
- Paper title, authors, 40 bps vs 90 bps and cost caveat — from search summaries of [SMU](https://ink.library.smu.edu.sg/lkcsb_research/7447) and the [HKU fintech page](https://fintechacademy.cs.hku.hk/?p=8311). The SMU page itself fetched empty.

#### Candidate 4: Cross-sectional crypto futures basis factor (parameters not retrieved)
```json
{
  "id": "C4",
  "name": "Basis / momentum / basis-momentum factors in crypto futures (Journal of Futures Markets vol 43 issue 8, article fut22425)",
  "source_url": "https://www.infona.pl/resource/bwmeta1.element.wiley-fut-v-43-i-8-fut22425 (fetch returned 404 at last attempt; found via search snippet)",
  "source_date": "2023 (inferred from volume 43)",
  "traded_asset": "cross-section of major crypto futures",
  "signal_data": "futures vs spot prices; source venue not verified",
  "signal": "Basis is the strongest cross-sectional predictor; sort on basis. Exact formula, quantiles, rebalance not retrieved.",
  "holding/rebalance": "daily factor returns much stronger than weekly; monthly insignificant",
  "sizing": "unknown",
  "parameters": "unknown",
  "publication_lag_handling": "unknown",
  "source_sample": "2017 to 2021",
  "reported_performance": "Basis, momentum and basis-momentum factors earn significant excess returns; no numbers retrieved",
  "post_publication_evidence": "none found",
  "known_weaknesses": "Basis cross-section is close to carry (funding/basis carry is excluded in this repo); daily rebalancing costs; parameters unknown."
}
```
- Findings quoted from search summary of the Wiley record: [infona record](https://www.infona.pl/resource/bwmeta1.element.wiley-fut-v-43-i-8-fut22425). Authors and DOI were not retrieved.

#### Sources reviewed and rejected (no codable published rule)
- USDT supply timing: BDC Consulting, June 2022, author Vitalii Khudyi; mean ROI 229%, Sharpe 1.4577, sample end-2020 to March 2022, but no spike thresholds, lookbacks, sizing or holding rules — [BDC Consulting](https://bdc.consulting/insights/cryptocurrency/a-new-study-finds-that-using-usdt). Fails the parameter rule.
- Stablecoin liquidity regime paper (Research Square rs-9715935, BTC/ETH/SOL 2020 to 2026, HMM density forecasts, stablecoin volume growth positively associated with returns): a forecast model, not a trading rule; full text not read — [Research Square](https://www.researchsquare.com/article/rs-9715935/v1).
- Coinbase premium: only indicator definitions (Coinbase BTC price minus Binance BTC price) and an unsourced CryptoQuant analyst remark that a 30-day EMA crossing a 100-day EMA of the index signals bull continuation; no backtest — [TradingView script](https://www.tradingview.com/script/NXnLGGdF-Coinbase-Premium-Index-Any-Symbol/), [Cointelegraph](https://cointelegraph.com/markets/bitcoin-coinbase-premium-returns-is-90-k-btc-price-in-the-cards). An HKUST undergraduate independent-study report on trading with on-chain data (including Coinbase premium) exists but returned HTTP 403 so its rules are unread — [HKUST PDF](https://cse.hkust.edu.hk/~rossiter/independent_studies_projects/trading_bitcoin_onchain_data/trading_bitcoin_onchain_data.pdf). Worth retrying by another route.
- DVOL / variance risk premium: Alexander and Imeraj (Journal of Alternative Investments, Deribit-based indices, Mar 2019 to Mar 2020) is descriptive; Almeida, Grith, Miftachov, Wang "Risk Premia in the Bitcoin Market" (arXiv 2410.15195, Deribit, Jul 2017 to Dec 2022) reports an average BVRP of 0.14 (0.17 low-vol, 0.12 high-vol regime), no strategy P&L — [Sussex record](https://sro.sussex.ac.uk/id/eprint/91094/), [Harbourfront summary](https://harbourfrontquant.substack.com/p/return-and-variance-risk-premia-in), [arXiv](https://arxiv.org/html/2410.15195v2). A practitioner API page defines VRP as DVOL minus 30-day realized vol (annualized stdev of daily log returns) — [Oanor](https://www.oanor.com/tag/dvol), a definition only.
- Options skew: no backtested skew rule found; the nearest paper uses GARCH conditional skewness from returns (not options) and notes a sign flip between 2018 to 2020 and 2021 to 2022 — via search result, [Deribit insights](https://insights.deribit.com/?p=21727) only defines skew. Net buying pressure paper [arXiv 2109.02776](https://arxiv.org/pdf/2109.02776) is about options flow, not a rule.
- Open interest / long-short ratio: only practitioner heuristics, no parameterized rules — [CF Benchmarks](https://blog.cfbenchmarks.com/bitcoins-open-interest-question), [K33](https://k33.com/research/archive/articles/shorts-squeezed-btc-denominated-open-interest-in-perps-blasted-through-300). The Binance long/short ratio is account-count based (secondary source: [Sharpe.ai](https://www.sharpe.ai/futures/bitcoin/long-short-ratio)).
- CME basis: Lee, El Meslmani and Switzer (2020, RIBAF) find basis has some predictive power for spot changes but is a biased predictor (Jan 2018 to Mar 2019); Matsui and Gudgeon (2020) find the 1-month futures price is not an unbiased predictor. No rule — [EconPapers](https://econpapers.repec.org/RePEc:eee:riibaf:v:53:y:2020:i:c:s0275531919309808). The CF Bitcoin Compounding Basis Index is a rules-based product (short futures in contango, long in backwardation) but its parameters were not read — [CF factsheet](https://docs.cfbenchmarks.com/factsheets/cfcmcbi_btc.pdf).

### Inferences
- The literature in these categories is mostly descriptive predictability work; trading-rule write-ups with exact numbers come from data vendors (Bitcoin Magazine Pro, BDC), which have commercial incentives.
- C1 is the only item that can be coded today, and it must be coded with a one-day signal lag, so it cannot be tested "exactly as published".
- C2 is the most credible (peer-reviewed, 11+ years) but cannot be coded until the full-text rules are read; its sample has few independent events (three cycles), so even a faithful replication has little statistical power.
- ETF-flow data begins 2024-01, so any test of C1 has a short sample and overlaps heavily with the source's own sample.

### Gaps
- Exact thresholds and holding rules for Grobys et al. (try the published article DOI 10.1016/j.ribaf.2026.103486 or the OSUVA PDF; both were unreachable or not fetched).
- Authors, parameters and data of the Wiley basis-factor paper; Huang et al. signal formula.
- Any published DVOL-VRP, Coinbase-premium, OI or long/short ratio, skew or exchange-netflow trading rule with parameters: none found in about 20 calls. Not searched: Quantpedia crypto entries, SSRN keyword searches, blockchain.com-based rules, Kimchi/Coinbase premium academic papers beyond one search.
- Verification of free endpoints: data.binance.vision metrics (OI, long/short ratio; the brief says from 2020-09) is NOT confirmed — the binance-public-data GitHub README only documents aggTrades, klines and trades for futures; Farside, DefiLlama, Deribit DVOL endpoints and CoinMetrics community docs were not checked.

## Data endpoint verification

### Takeaway
No free endpoint named in the brief was verified against official docs, apart from the negative finding that the binance-public-data README does not list futures "metrics" files.

### Cited Findings
- The binance-public-data README lists only AggTrades, Klines and Trades for USD-M/COIN-M futures and says data is aggregated into daily or monthly files with new daily data arriving the next day — [GitHub binance-public-data](https://github.com/binance/binance-public-data). The metrics folder may still exist on data.binance.vision, but this was not confirmed.
- Farside BTC ETF table fetch failed with HTTP 403 — [Farside](https://farside.co.uk/btc/).

### Inferences
- A replication needing OI or long/short history should test the data.binance.vision directory listing directly before relying on the 2020-09 start.

### Gaps
- All other endpoints unverified.
