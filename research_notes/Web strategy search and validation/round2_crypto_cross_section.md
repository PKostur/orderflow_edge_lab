# Round 2: published crypto cross-sectional strategies with exact specs

STATUS WARNING: In this run no paper's full text could be read as text. Every PDF (JFQA/Cambridge, Corvinus repository copy, Cambridge supplement, Yale LTW PDF, arXiv) came back from the fetch tool as compressed binary. SSRN, ResearchGate, ScienceDirect and Springer returned 403 or a login redirect. Only abstracts, search-result snippets and secondary summaries were obtained. This is the same failure as the previous round, so the exact parameters below are mostly NOT verified. Each field is marked VERIFIED (seen in a fetched or search-snippet source), SNIPPET (seen only in a search-engine excerpt of the paper or a summary), or UNVERIFIED.

Binary PDFs were saved locally by the fetch tool and can be text-extracted with `pdftotext` (not available to this agent), then read directly:
- CTREND (Corvinus copy): C:\Users\007pe\.claude\projects\C--Users-007pe-src-orderflow-edge-lab\52e86723-5fec-4dba-8734-e0df4dec673a\tool-results\webfetch-1791734972111-qqub8d.pdf
- CTREND (Cambridge version): ...\tool-results\webfetch-1791734915744-2htigi.pdf
- CTREND Cambridge supplement (25 pages, likely has the indicator list and robustness tables): ...\tool-results\webfetch-1791735058030-l4mcgi.pdf
- Liu-Tsyvinski-Wu (Yale copy): ...\tool-results\webfetch-1791735108940-tgyfps.pdf

## Which candidates have codable specs, and what is actually known?

### Takeaway
CTREND is the strongest candidate and the weekly value-weighted quintile design is SNIPPET-confirmed, but the 28-indicator list, the regression window, the universe filters and the net Sharpe were not read. Liu-Tsyvinski-Wu momentum/size is the best-documented classic but its published universe is micro-cap heavy. The Grobys vol-managed momentum, factor momentum and large-cap reversal papers were reached only at abstract level.

### Cited Findings
- CTREND paper: Fieberg, Liedtke, Poddig, Walker, Zaremba, JFQA vol 60 no 7 (2025), pp 3116-3153, DOI 10.1017/S0022109024000747. The author list does NOT include Metko; the brief's author attribution is wrong for CTREND. Metko is an author of the factor momentum paper. — [Bremen repository](https://media.suub.uni-bremen.de/entities/publication/61093933-845a-436c-90a1-cb6bdaa52d13)
- CTREND: more than 3,000 coins, 2015 to 2022, 28 popular technical signals (momentum oscillators, moving averages, volume-based indicators, volatility measures) aggregated by machine learning into one signal; abstract says it survives transaction costs and persists in big and liquid coins, is not explained by known factors, and holds across subperiods and market states. — [Corvinus repository](https://unipub.lib.uni-corvinus.hu/11621/), [JFQA](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178)
- CTREND estimator (SNIPPET): cross-sectional combined elastic net (CS-C-ENet) of Han, He, Rapach and Zhou (2024); on average about 15 indicators carry weight each week, so the signal is not sparse. Weekly: at the start of each week coins are ranked on CTREND and grouped into quintiles; portfolios are value-weighted and rebalanced weekly; long top quintile, short bottom. A gross long-short figure of 3.87% per week appears in a snippet; it is not stated whether it is gross or net, or its weighting, so do not rely on it (a 3.87% weekly spread is about 200% per year and is likely a gross, small-coin-influenced number). — [search snippets citing the paper via ResearchGate](https://www.researchgate.net/publication/375528534_A_Trend_Factor_for_the_Cross-Section_of_Cryptocurrency_Returns), [QuantSeeker summary](https://www.quantseeker.com/p/weekly-research-recap-a75)
- Liu, Tsyvinski, Wu, "Common Risk Factors in Cryptocurrency" (NBER w25882; Journal of Finance 2022, DOI 10.1111/jofi.13119 per one listing; another summary lists Economic Modelling 2020, venue conflict). Three factors (market, size, momentum) capture the cross-section. Each week coins are sorted into fifths and long-short is highest minus lowest quintile. Sample: coins with market cap above $1 million, from 2014 (109 coins) to 2018 (1,583 coins), CoinMarketCap data. NBER version says nine long-short factors are significant; SSRN/JF version says ten. — [NBER](https://www.nber.org/papers/w25882), [search summaries](https://alphaarchitect.com/factors-investing-in-cryptocurrency/)
- Fieberg, Liedtke, Metko, Zaremba, "Cryptocurrency factor momentum", Quantitative Finance 23(12), 2023, pp 1853-1869. More than 3,900 coins, 2014 to 2022, 34 anomalies replicated; past factor winners beat factor losers; effect robust across subperiods; in crypto it originates from price momentum transferring to factor level. Construction (lookback, number of factors held) not seen. — [IDEAS](https://ideas.repec.org/a/taf/quantf/v23y2023i12p1853-1869.html), [ICM record](https://open.icm.edu.pl/items/d9f44e22-0614-4db8-8585-6dcba8906bb5)
- Grobys, Kolari, Sandretto, Shahzad, Aijo, "Cryptocurrency momentum has (not) its moments", Financial Markets and Portfolio Management, DOI 10.1007/s11408-025-00474-9. Abstract: large-cap coins, equal-weighted momentum portfolios, severe crashes, volatility management mitigates crashes, momentum associated with large caps, asks whether profits depend on micro-caps. No Sharpe, window or universe size seen. — [search result](https://osuva.uwasa.fi/handle/11111/18877)
- Short-term reversal: an International Review of Financial Analysis (2021) paper "Up or down? Short-term reversal, momentum, and liquidity effects in cryptocurrency markets" reports daily reversal is driven by illiquidity and the largest, most tradeable coins show daily momentum, not reversal. Bianchi, Babiak, Dickerson (J Banking & Finance 2022) find reversal/liquidity-provision returns are larger in small, volatile, illiquid pairs (USD pairs, 2017-2022). Both point against a large-cap reversal strategy. — [Medeniyet repository](https://earsiv.medeniyet.edu.tr/items/23a96c9f-3952-4bdf-aec5-abafb3aaab70), [Riksbank WP 413](https://www.riksbank.se/globalassets/media/rapporter/working-papers/2022/no.-413-trading-volume-and-liquidity-provision-in-cryptocurreny-markets.pdf)
- Cakici, Shahzad, Bedowska-Sojka, Zaremba, "Machine learning and the cross-section of cryptocurrency returns", IRFA 94 (2024) 103244: most ML strategies stay profitable after trading costs despite high turnover, but alphas are concentrated in small, illiquid, volatile coins. Relevant as a warning for CTREND-style ML signals. The "2.37% weekly, Sharpe 1.66" figure from a snippet could not be tied to this paper; discard. — [IDEAS](https://ideas.repec.org/a/eee/finana/v94y2024ics1057521924001765.html)
- Another paper (Borri, Liu, Tsyvinski, Wu, "Cryptocurrency as an Investable Asset Class", arXiv 2510.14435) cites CTREND in one sentence only and has no construction; its own universe excludes coins with under 180 days of history or low volume (threshold unspecified). — [arXiv](https://arxiv.org/html/2604.26747v1) (the page fetched was an LLM-agent crypto factor paper that quotes this; treat as secondary)

### Candidate specs (JSON; UNVERIFIED fields are labelled)

```json
{
  "id": "R2-C1",
  "name": "CTREND aggregate trend factor",
  "source_url": "https://doi.org/10.1017/S0022109024000747",
  "source_date": "2025 (JFQA 60(7)); SSRN 4601972 from 2023",
  "universe_filter": "UNVERIFIED. Paper uses >3,000 coins (CoinMarketCap-type data, 2015-2022). Minimum price/market-cap/volume filters and stablecoin treatment not read. Large/liquid-coin subsample exists (abstract) but its cutoff is unknown. Free substitute: Binance USDT-M or spot top-N by trailing quote volume.",
  "data": "Close, volume (and quote volume) daily. Indicators need price and volume; whether high/low are used is UNVERIFIED. Value weighting needs market cap, which is paid; paper uses market cap for weights (SNIPPET), substitute would be trailing quote volume or equal weight.",
  "signal": "28 technical indicators (families: momentum oscillators, moving averages, volume-based indicators, volatility measures; exact list and lookbacks UNVERIFIED, likely in the Cambridge supplement or paper appendix). Aggregation: cross-sectional combined elastic net (CS-C-ENet, Han-He-Rapach-Zhou 2024): each week regress next-week returns on lagged indicators cross-sectionally, then combine forecasts over a rolling window of past coefficient estimates. Window length UNVERIFIED (a 26-week figure floated in a search query was not confirmed anywhere).",
  "portfolio": "Quintiles on CTREND; long top quintile, short bottom; value-weighted (SNIPPET). Equal-weighted variant presumably reported (UNVERIFIED).",
  "rebalance": "Weekly (SNIPPET).",
  "parameters": "Elastic net penalty and mixing (alpha), cross-validation or fixed: UNVERIFIED.",
  "source_sample": "2015-2022, more than 3,000 coins.",
  "reported_performance": "Net Sharpe, drawdown NOT seen. A 3.87% per-week long-short figure appeared in a snippet, unlabelled gross/net, unreliable. Abstract claims it survives transaction costs and works in big, liquid coins.",
  "post_publication_evidence": "None found. Same group's later papers cite it; no independent out-of-sample test seen. Sample ends 2022, so 2023-2026 is a genuine out-of-sample window for a Binance test.",
  "known_weaknesses": "Complex ML aggregation with many unseen choices; ML crypto cross-section profits are concentrated in small illiquid coins (Cakici et al 2024); value weighting needs market cap; weekly rebalance with large turnover; authors-group evidence only; shorting needs perps (USDT-M ok)."
}
```

```json
{
  "id": "R2-C2",
  "name": "Liu-Tsyvinski-Wu crypto momentum (CMOM) and size (CSMB) quintile long-short",
  "source_url": "https://www.nber.org/papers/w25882",
  "source_date": "2019 NBER; Journal of Finance 2022 per one listing (venue conflict: another lists Economic Modelling 2020)",
  "universe_filter": "SNIPPET: coins with market cap above $1 million, CoinMarketCap data, 109 coins (2014) to 1,583 (2018). Further filters UNVERIFIED. For a liquid-only test, substitute top-N by trailing quote volume on Binance.",
  "data": "Close; market cap for size (paid; substitute by volume proxy or drop size).",
  "signal": "Momentum = past return over k weeks; the exact horizons (paper lists 1, 2, 3, 4 week and longer variants) were NOT seen in this run. Do not treat a 3-week lookback as verified.",
  "portfolio": "Weekly sort into quintiles; long top, short bottom (SNIPPET); weighting in headline table UNVERIFIED (paper reports equal- and value-weighted in separate places, from memory only).",
  "rebalance": "Weekly (SNIPPET).",
  "parameters": "Lookback weeks UNVERIFIED.",
  "source_sample": "2014-2018 (SNIPPET).",
  "reported_performance": "Not seen. Paper states significant excess returns for 9 or 10 factors; no Sharpe or net figures obtained.",
  "post_publication_evidence": "Later work (Grobys et al 2025; Fieberg et al 2023) finds momentum in large caps but crash-prone; Han-Kang-Ryu type results say cross-sectional momentum is weak after costs (secondary search summary only, not fetched).",
  "known_weaknesses": "Sample ends 2018, small-coin and bubble driven (2017); micro-cap profits do not survive costs; excluded by brief if micro-cap only."
}
```

```json
{
  "id": "R2-C3",
  "name": "Volatility-managed cross-sectional crypto momentum among large caps (Grobys et al.)",
  "source_url": "https://link.springer.com/article/10.1007/s11408-025-00474-9",
  "source_date": "2025",
  "universe_filter": "UNVERIFIED. Abstract says large-cap coins.",
  "data": "Close (returns); volatility estimate from daily returns.",
  "signal": "UNVERIFIED formation window; volatility management follows equity literature (Barroso and Santa-Clara style scaling of the momentum portfolio by its own trailing volatility) - this is an assumption, not read.",
  "portfolio": "Equal-weighted winner minus loser portfolios (abstract). Quantile cut UNVERIFIED.",
  "rebalance": "UNVERIFIED.",
  "parameters": "UNVERIFIED.",
  "source_sample": "UNVERIFIED.",
  "reported_performance": "Not seen. Abstract: severe crashes, volatility management mitigates them.",
  "post_publication_evidence": "None.",
  "known_weaknesses": "No parameters obtained; a single coin can flip results; sample specificity and bubbles flagged by authors."
}
```

```json
{
  "id": "R2-C4",
  "name": "Cryptocurrency factor momentum (Fieberg, Liedtke, Metko, Zaremba)",
  "source_url": "https://ideas.repec.org/a/taf/quantf/v23y2023i12p1853-1869.html",
  "source_date": "2023",
  "universe_filter": "UNVERIFIED (3,900+ coins, 2014-2022).",
  "data": "Needs 34 anomaly factor returns built from price, volume and market-cap data; many anomalies need market cap or other paid fields. Only the price/volume subset is free.",
  "signal": "Long factors with positive past return, short those with negative; lookback UNVERIFIED.",
  "portfolio": "Factor-level, not coin-level; UNVERIFIED.",
  "rebalance": "UNVERIFIED (likely weekly).",
  "parameters": "UNVERIFIED.",
  "source_sample": "2014-2022.",
  "reported_performance": "Not seen.",
  "post_publication_evidence": "None found.",
  "known_weaknesses": "Depends on rebuilding many factors; authors say it originates from price momentum, so a plain coin momentum test may capture it; low independent value."
}
```

C5 (large-cap short-term reversal) is not offered as a candidate: the two sources found say reversal vanishes or flips to momentum in the largest, most liquid coins and is paid mainly in illiquid pairs, so the objective filter (liquid universes) works against it. C6 (liquidity/turnover factor) was not researched to a paper with exact construction in this run.

### Inferences
- CTREND is the only candidate that matches the brief (long sample, liquid-coin evidence, cost survival claim, post-2022 out-of-sample window possible), but a codable version cannot be written from what was read. The cheapest next step is text extraction of the saved Cambridge supplement and main PDF to get the 28 indicator definitions, the window and the table of net Sharpe by size group.
- If CTREND cannot be reproduced exactly, a defensible simplification would be a transparent price/volume trend composite, but that would be a new strategy, not a replication, and should be pre-registered as such.
- The ML-cross-section literature suggests liquid-universe net Sharpe will be materially lower than headline numbers; this is an inference from Cakici et al and the reversal papers, not a measured result.

### Gaps
- CTREND: indicator list, lookbacks, regression window, penalty, universe filters, net and large-cap Sharpe, drawdown, turnover and cost assumptions: all unread (PDFs undecodable; SSRN and ResearchGate blocked).
- LTW: momentum horizons, Sharpe and weighting scheme.
- Grobys et al: everything quantitative.
- Factor momentum: construction and performance.
- No post-publication replication of any of these found.
- Liquidity/turnover factors and any other paper with exact construction not searched beyond the above.
- Whether the authors publish replication code: none found in searches.
