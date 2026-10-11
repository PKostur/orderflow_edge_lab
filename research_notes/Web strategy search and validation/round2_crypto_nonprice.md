# Round 2: crypto strategies with non-price free signals, full-text and endpoint verification

Scope note: about 20 tool calls. Result in one line: only one candidate (Grobys et al. MVRV-Z / NUPL) is both codable in outline and backed by a verified free endpoint with more than 5 years of history, and even it is only partly specified because I could not read the full text. The Vaasa server (osuva.uwasa.fi, IP 128.214.223.188) refused every connection (ECONNREFUSED), and ScienceDirect/Elsevier returned 403 or a bare "Redirecting". All paper details below therefore come from search-engine summaries of the paper, not from my own reading, and two of those summaries disagreed (see Gaps). No backtests were run.

## 1. Grobys, Nasman, Sandretto: MVRV Z-score / NUPL / CVDD rules and a free MVRV source

### Takeaway
The rule family is "enter long at a low indicator level, exit when the indicator crosses a high threshold" for NUPL (exit 0.67 / 0.70 / 0.73) and MVRV Z-score (exit 5 / 6 / 7). Entry thresholds, the re-entry rule, sizing and the data vendor are unconfirmed. A free MVRV series exists and was verified (CoinMetrics community API, from 2010-07-30), so the signal can be built, but the paper's exact rules cannot be reproduced until its full text is read.

### Cited Findings
- Paper exists: Grobys, Nasman, Sandretto, "Using on-chain data to predict Bitcoin cycles", Research in International Business and Finance 2026, open access; abstract says the indicators beat buy-and-hold and Monte Carlo random entries; MVRV Z-score Sharpe 1.28 vs 0.45 buy-and-hold; sample 2013-12-07 to 2025-04-12 across three cycles — summary via search tool of [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0275531926002138) and [Vaasa repository](https://osuva.uwasa.fi/items/d5993292-4a47-4162-89d7-7ddf676ba319/full). I could not fetch either (403 and ECONNREFUSED).
- Thresholds as reported in one search summary of the paper (not seen by me in the primary text): NUPL exit 0.67 (conservative), 0.70 (moderate), 0.73 (aggressive), with entry at 0 and central exit 0.70 matching the indicator creators' levels; MVRV Z-score exit thresholds 5, 6, 7; CVDD thresholds not found; MVRV Z-score was the best performer in all versions; the paper cautions that exit thresholds are not fully objective and may reflect hindsight from the metric creators — search summary of [Vaasa bitstream](https://osuva.uwasa.fi/server/api/core/bitstreams/6575b90c-6140-44e7-a798-011a1793d134/content). A second search, run for the same facts, said it could not confirm the 0.70 exit, the entry at 0 or the data vendor. Treat the numbers as probable but unverified.
- Earlier-round level (Securities.io summary): MVRV Z < -0.2 as "fear", exit zone 5 to 7, NUPL > 0.75 as euphoria; no data provider named — [Securities.io](https://www.securities.io/de/using-on-chain-data-predict-bitcoin-cycles/).
- Thesis version (Nasman 2025) reports cumulative returns over 326,000% in the strongest cases — [OSUVA](https://osuva.uwasa.fi/items/48a4f9df-03ca-4b96-9072-07b462b14dfa/full).
- Free endpoint verified by GET: CoinMetrics community API returns `CapMVRVCur` daily for BTC. Query with start_time=2010-07-01 returned first rows 2010-07-30 (12.03290217), 2010-07-31 (12.05286591), 2010-08-01 (10.44892297); latest row seen 2026-10-10 (1.541127) — [CoinMetrics community API](https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=CapMVRVCur&frequency=1d&start_time=2010-07-01&end_time=2010-08-01&page_size=3). No key needed.
- Practitioner note: the latest cycle's MVRV peak was reported near 2.52, far under the 3.5 that preceded earlier tops, so fixed MVRV levels may have shifted — via search summary of [BIT Knowledge Hub](https://www.bit.com/knowledge-hub/mvrv-explained) (single secondary source).

```json
{
  "id": "R2-C1",
  "name": "Grobys-Nasman-Sandretto NUPL / MVRV Z-score threshold cycle timing (long at low level, exit at high threshold)",
  "source_url": "https://doi.org/10.1016/j.ribaf.2026.103486 (ScienceDirect PII S0275531926002138); thesis https://osuva.uwasa.fi/items/48a4f9df-03ca-4b96-9072-07b462b14dfa/full",
  "source_date": "2025 thesis; 2026 journal",
  "traded_asset": "BTC (spot implied)",
  "signal_data": {
    "endpoint": "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=CapMVRVCur&frequency=1d",
    "fields": "CapMVRVCur (MVRV ratio). For the Z-score also request CapMrktCurUSD and CapRealUSD. NUPL = 1 - 1/MVRV = (CapMrktCurUSD - CapRealUSD)/CapMrktCurUSD (algebraic identity, not checked against the paper's data).",
    "earliest_date_seen": "2010-07-30 for CapMVRVCur",
    "verified": "yes for CapMVRVCur (fetched). CapMrktCurUSD and CapRealUSD were requested in one call that returned 403, so they are NOT verified; verify before use.",
    "note": "The paper's vendor is not confirmed. CoinMetrics values can be revised, and the API tags some values 'flash' status, so a replication on current data is not point-in-time."
  },
  "signal": "NUPL: enter long when NUPL reaches the entry level (reported as 0), exit when NUPL >= 0.67 / 0.70 / 0.73 (conservative / moderate / aggressive). MVRV Z-score: Z = (MarketCap - RealizedCap) / stdev(MarketCap) (standard Glassnode definition; the paper's stdev window is UNKNOWN, expanding is the usual one); exit at Z >= 5 / 6 / 7; entry level UNKNOWN (Z < -0.2 appears in a secondary summary).",
  "holding/rebalance": "UNKNOWN: daily threshold check assumed. Re-entry rule, whether out of market means cash, and holding limits are not confirmed.",
  "sizing": "UNKNOWN, presumably 100% long or flat",
  "parameters": "NUPL exits 0.67/0.70/0.73, entry 0 (unverified); MVRV-Z exits 5/6/7; CVDD parameters not found",
  "publication_lag_handling": "UNKNOWN. Daily on-chain values for day t are known after the UTC close; a codable version should act at t+1.",
  "source_sample": "2013-12-07 to 2025-04-12, three cycles",
  "reported_performance": "MVRV-Z Sharpe 1.28 vs 0.45 buy-and-hold; beats Monte Carlo random entry; in-sample (thresholds taken from metric creators, whose levels were set on earlier cycles, so partly hindsight, as the paper itself warns).",
  "post_publication_evidence": "None; a 2026 paper and the post-2025 cycle top (MVRV ~2.5) is a live out-of-sample test in which Z likely never reached 5 (not verified here).",
  "known_weaknesses": "Roughly 3 independent trades, so near-zero statistical power; long-only exit rules fire a handful of times; thresholds fixed from earlier cycle tops; MVRV drifts lower each cycle; vendor data vintage unknown."
}
```

### Inferences
- With only ~3 round trips, any backtest on this signal is an anecdote, regardless of fidelity. It does not raise independent breadth for the repo's evidence-rate rule beyond one asset.
- MVRV and NUPL from one CoinMetrics field are cheap to build, but the Z-score's stdev window must be fixed before viewing data (the repo's pre-registration rule).

### Gaps
- Full text (data vendor, entry thresholds, re-entry, CVDD thresholds, costs, standard-deviation window) unreachable: osuva.uwasa.fi ECONNREFUSED on three URLs; ScienceDirect 403; Elsevier API 400. A human with a browser should open the open-access PDF.
- Exact CapRealUSD / CapMrktCurUSD availability on the community tier not confirmed.

## 2. Spot BTC ETF flow strategies with a free daily source other than Farside

### Takeaway
No published study with an exact rule and a free non-Farside flow source was found, and spot ETF history only begins 2024-01-11, so no candidate can meet the 5-year requirement.

### Cited Findings
- Only exact rule remains the Bitcoin Magazine Pro sign rule (+118.5% vs +81.7%, 2024-01 to 2025-03; round 1 candidate C1) — [Bitcoin Magazine](https://bitcoinmagazine.com/markets/bitcoin-etf-flow-strategy-beats-buy-and-hold). A second Bitcoin Magazine backtest (about 200% vs about 155%) was seen only as a result snippet; its rules are unread — [Bitcoin Magazine](https://bitcoinmagazine.com/markets/bitcoin-etf-strategy-btc-buy-hold).
- Academic ETF papers found test relationships, not rules: Mazur and Polyzos (J. Alternative Investments 2025) find net flows strongly related to BTC price levels (R-squared 95%), mostly outside ETF trading hours; a Pitt "Ledger" paper uses CoinGlass total net assets, 2024-01-11 to 2025-05-16 (352 daily observations), finds cointegration only at the 10% level and proposes no trading rule — [Ledger](https://ledger.pitt.edu/ojs/ledger/article/download/393/333?inline=1) (fetched); Mazur/Polyzos and Onishchenko (short-sale flows predict ETF returns up to 5 days) via search summary only — [Otago record](https://ourarchive.otago.ac.nz/esploro/outputs/journalArticle/Betting-Against-Bitcoin-Evidence-from-Spot/9926869882101891).
- Free flow sources named by search: SoSoValue and Farside feed an Apify actor (paid per row, 300 days of history) — [Apify](https://apify.com/gochujang/crypto-etf-flow-tracker); CoinGlass tracker used by the Pitt paper; Glassnode chart `institutions.UsSpotEtfFlowsAll` (login likely needed). I found no GitHub CSV. A guessed SoSoValue API path returned 404 (not their real route, so this shows nothing about availability).

### Inferences
- Not a viable candidate for a daily-signal screen: about 2.7 years of data, source overlaps the publishing sample, and same-day look-ahead was in the original.

### Gaps
- No verified machine-readable free flow endpoint (SoSoValue, issuer pages, GitHub). Not fetched: issuer holdings files (IBIT, FBTC), CoinGlass API.

## 3. Rules using DVOL, CoinMetrics community metrics, or DefiLlama stablecoin supply

### Takeaway
All three endpoints work without a key and have usable history, but I found no academic paper with an exact trading rule on any of them. Do not treat them as candidates; they are data sources only.

### Cited Findings
- Deribit DVOL: `get_volatility_index_data` with resolution=1D returned daily OHLC rows beginning 2021-03-24 (84.8, 95.94, 80.52, 95.04; field labels not in the response, assumed open, high, low, close); a query for 2018 returned an empty list. 284 rows for 2021-03-24 to 2021-12-31 — [Deribit API](https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&start_timestamp=1609459200000&end_timestamp=1640995200000&resolution=1D). That is about 5.5 years by October 2026. Note the resolution value 86400 returned empty and "1D" worked.
- DefiLlama stablecoin supply: `stablecoincharts/all?stablecoin=1` (USDT) is daily from 2017-11-29, fields `date`, `totalCirculating`, `totalCirculatingUSD`; the first values are flat at 110,105 (USD) for the first days, so early history is a placeholder-like stretch; the most recent date was not seen because the response was truncated — [DefiLlama](https://stablecoins.llama.fi/stablecoincharts/all?stablecoin=1).
- CoinMetrics community exchange flows: `FlowInExUSD` for BTC returned daily rows beginning 2015-02-14 (12.68M USD) when asked from 2015-01-01, with status "flash" (revisable) — [CoinMetrics](https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=FlowInExUSD&frequency=1d&start_time=2015-01-01&end_time=2015-02-15&page_size=2). `AdrActCnt` and `TxCnt` returned from 2009-02-14 in a fetch whose output was re-formatted by the fetch tool (not raw API JSON), so I rate it plausible but not raw-verified.
- Rules: USDT-supply timing by BDC Consulting (Sharpe 1.4577, sample end-2020 to March 2022) has no thresholds or lookbacks — [BDC Consulting](https://bdc.consulting/insights/cryptocurrency/a-new-study-finds-that-using-usdt). A search for DVOL, active-address or stablecoin trading papers found none with exact rules; results were off-topic (a 2015 social-signal paper, Glassnode's commercial "Sharpe Signal", and an LLM strategy preprint) — search tool summary, no single source.
- DVOL is described in the literature only as a variance-premium input (VRP = DVOL minus 30-day realized vol, definition only; Almeida et al. report average BVRP 0.14, no P&L) — [arXiv 2410.15195](https://arxiv.org/html/2410.15195v2).

### Inferences
- Any strategy on these sources would be a repo-invented specification, not "tested as published", so it falls outside the strategy-search-v1 rule.
- Honest candidate count: one partially specified (R2-C1), zero fully specified with a 5-year free endpoint. The ETF sign rule is fully specified but fails history and look-ahead.

### Gaps
- Not searched: SSRN/Quantpedia keyword lists, papers on active-address or transaction-count timing, Kimchi premium, and exchange-netflow rules with parameters; limited by the tool-call budget.
- DefiLlama latest date and the DVOL column labels not confirmed. Earliest DVOL date was inferred from the first row of a query starting 2021-01-01, so earlier data cannot be fully excluded for dates before 2021 beyond the empty 2018 result.
