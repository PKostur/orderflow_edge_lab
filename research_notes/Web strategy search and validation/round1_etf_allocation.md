# Round 1: published ETF allocation / rotation strategies, candidate specs

Scope: only what sources state; nothing was backtested. Most primary papers (SSRN) returned 403 or were unreadable, so rules come from secondary summaries (CXO Advisory, Quantpedia, R-bloggers, TradingView scripts). Every spec below is marked VERIFIED (two or more consistent sources) or UNVERIFIED (must be checked against the SSRN paper before coding). Allocate Smartly pages returned 404 or members-only, so no Allocate Smartly numbers are used.

## Candidate strategies (up to 6)

### Takeaway
Six candidates with codable rules. Only VAA-G12 has fully sourced B and T. The other Keller models still need exact T and cash-asset details checked against the SSRN PDFs. No candidate has a clean live post-publication track record in the sources found. Faber GTAA and GEM are borderline under the "no plain time-series trend" exclusion and are flagged.

### Cited Findings

Common definitions (secondary sources):
- 13612W momentum = (12*r1 + 4*r3 + 2*r6 + 1*r12)/4 (r = total return over 1/3/6/12 months), or "average of annualized total returns over 1,3,6,12 months" — [TradingView script](https://vn.tradingview.com/script/8vo7fX4M), [CXO VAA](https://cxoadvisory.com/?p=30082). The two descriptions are the same up to a constant scale; sign and ranking are identical.
- Trading friction assumed in Keller papers: 0.1% one-way — [CXO VAA](https://cxoadvisory.com/?p=30082), [CXO PAA](https://www.cxoadvisory.com/technical-trading/dual-momentum-with-multi-market-breadth-crash-protection).

```json
{
  "id": "C1",
  "name": "Keller & Keuning Vigilant Asset Allocation, VAA-G12",
  "source_url": "https://cxoadvisory.com/?p=30082 (summary); primary: Keller & Keuning 2017 SSRN 3002624 (not opened)",
  "source_date": "2017 (paper); first-hand date not verified",
  "universe": {"risky": ["SPY","IWM","QQQ","VGK","EWJ","VWO","VNQ","GSG","GLD","TLT","LQD","HYG"], "cash": ["SHY","IEF","LQD"]},
  "data": "Yahoo daily adjusted close, month-end. Earliest common date is set by the youngest fund (HYG/LQD/VNQ/GSG era); my recollection (not sourced) is about mid-2007, so first signal around mid-2008 after 12m lookback. Check.",
  "signal": "Monthly 13612W momentum of each risky asset. b = number of risky assets with negative momentum. B = 4. If b >= B: 100% in best-momentum asset of cash universe. Else: cash share b/B (rounded to multiples of 1/T) goes to best cash asset; remaining (1 - b/B) split equally across the top (1 - b/B)*T risky assets by momentum regardless of sign.",
  "rebalance": "Monthly, at month-end close (source says rebalance monthly; exact day not specified beyond month-end)",
  "sizing": "Equal weight across T top assets, scaled by (1 - b/B)",
  "parameters": {"B": 4, "T": 2, "momentum_weights": [12,4,2,1], "friction_one_way": 0.001},
  "source_sample": "Global 17-proxy sample Dec 1969-Dec 2016 split in halves; VAA-G12 out-of-sample Dec 1993-Dec 2016; 'recent' sample Dec 2006-Dec 2016. Many pre-ETF returns simulated.",
  "reported_performance": "VAA-G12 B=4,T=2: in-sample CAGR 21%, MaxDD -6%, Sharpe 1.24; out-of-sample CAGR 10%, MaxDD -13%, Sharpe 0.51. Average cash exposure about 60% across universes. B,T were optimized in-sample.",
  "post_publication_evidence": "None found. The only OOS is the authors' own 1993-2016 half, which pre-dates publication.",
  "known_weaknesses": "In-sample to OOS drop is large (CAGR 21% to 10%, Sharpe 1.24 to 0.51). Snooping and simulated pre-ETF data admitted in CXO critique. Short global OOS. Concentration in 2 assets. Tickers VWO vs EEM and EFA vs VEA vary between sources."
}
```
Source for the rules and numbers: [CXO Advisory on VAA](https://cxoadvisory.com/?p=30082). Status: VERIFIED for B=4, T=2 and performance (single secondary source; the TradingView copy of G4 figures is flagged by its own author as a poor translation).

```json
{
  "id": "C2",
  "name": "Keller & Keuning Defensive Asset Allocation, DAA-G12",
  "source_url": "https://www.cxoadvisory.com/strategic-allocation/multi-class-momentum-portfolio-with-canary-crash-protection/ ; primary SSRN 3212862 (403)",
  "source_date": "July 2018",
  "universe": {"risky_G12": ["SPY","IWM","QQQ","VGK","EWJ","VWO","VNQ","GSG","GLD","TLT","HYG","LQD"], "canary": ["VWO","BND"], "cash": ["SHY","IEF","LQD"]},
  "data": "Yahoo daily adjusted close, month-end. BND is the late-starting fund (my recollection, unsourced: April 2007), so first signal after 12 months, about mid-2008. Check.",
  "signal": "13612W momentum. b = number of canary assets (VWO, BND) with non-positive momentum. B = 2. If b >= 2: 100% best cash asset. Else cash share = b/B (rounded to multiples of 1/T) to the best-momentum asset of SHY/IEF/LQD; the rest equal-weighted in the top (1 - b/B)*T risky assets.",
  "rebalance": "Monthly, month-end",
  "sizing": "Equal weight over top T risky assets scaled by (1 - b/B)",
  "parameters": {"B": 2, "T": "UNVERIFIED (not stated in any retrieved source; CXO says 'set by backtest'; my unsourced recollection is T=6 for G12)", "momentum_weights": [12,4,2,1]},
  "source_sample": "Canary selection 1926-1970 (using S&P 500 only); in-sample parameter optimization 1971-1993; out-of-sample 1994-Mar 2018; VAA-vs-DAA comparison Mar 2008-Mar 2018.",
  "reported_performance": "DAA CAGR higher than VAA in 3 of 4 universes, but larger max drawdowns in all four (per CXO). Quantpedia lists indicative performance 16% for 1970-2018, volatility not given. Exact tables are images, not retrieved. Average cash fraction often less than half of VAA's.",
  "post_publication_evidence": "None verified. An unsourced Spanish Substack claims only five negative years since 1973, worst -8.4%, no methodology (treat as unreliable).",
  "known_weaknesses": "Canary pair chosen from pre-1971 data with S&P 500 only; short recent test; higher drawdowns than VAA; T unverified."
}
```
Sources: [CXO DAA](https://www.cxoadvisory.com/strategic-allocation/multi-class-momentum-portfolio-with-canary-crash-protection/), [Quantpedia #849](https://vvv.quantpedia.com/?p=25576), [R-bloggers KDA (DAA-based variant)](https://www.r-bloggers.com/right-now-its-kdaasset-allocation/), [Yago Garcia Substack](https://yagogarcia.substack.com/p/estrategia-daa-la-proteccion-efectiva). The R-bloggers variant (10 risky incl. RWX, min-variance weights, top 5, optional leverage) is NOT the paper's DAA and is not a candidate.

```json
{
  "id": "C3",
  "name": "Keller & Keuning Protective Asset Allocation, PAA2 (high protection)",
  "source_url": "https://www.cxoadvisory.com/technical-trading/dual-momentum-with-multi-market-breadth-crash-protection ; primary SSRN 2759734 (not opened)",
  "source_date": "2016 (CXO summary Apr 26, 2016)",
  "universe": {"risky": ["SPY","QQQ","IWM","VGK","EWJ","EEM","IYR","GSG","GLD","HYG","LQD","TLT"], "safe": ["IEF"]},
  "data": "Yahoo daily adjusted close, month-end; earliest common date set by HYG/GSG/EEM era (about 2007, unsourced). Another source substitutes VNQ for IYR and DBC for GSG (QuantConnect), so check the paper.",
  "signal": "MOM = price / SMA(12 monthly prices, as described: SMA of monthly prices) - 1. n0 = number of risky assets with MOM <= 0. Safe share = min(1, n0/6) (high protection; 12 = low, 9 = medium). The remaining share is split equally among the top 6 risky assets with positive MOM (hold fewer if fewer qualify; the unfilled share goes to safe).",
  "rebalance": "Monthly",
  "sizing": "Safe share n0/6 into IEF; rest equal weight across up to 6 positive-MOM risky assets",
  "parameters": {"lookback_months": 12, "protection_divisor": 6, "top_n": 6, "friction_one_way": 0.001},
  "source_sample": "Monthly data Dec 1969-Dec 2015, pre-ETF simulated; in-sample 1971-1992 (72-combination grid: 4 lookbacks x 3 protection x 6 top-N); out-of-sample 1993-2015.",
  "reported_performance": "In-sample Sharpe 1.06 (60/40: 0.33). Out-of-sample Sharpe 1.00, MaxDD -8.8%, CAGR 10.4% vs 8.2% for 60/40. Parameters picked in-sample, 1993-2015 'out-of-sample' had prior use by the authors.",
  "post_publication_evidence": "None found.",
  "known_weaknesses": "72 combinations searched; admitted possible data-snooping; pre-inception simulated returns overstate; sensitive to universe; unfilled-share treatment (to IEF) should be checked in the paper; SMA vs 13-point average definition should be checked (BAA uses 13-price average)."
}
```
Sources: [CXO PAA](https://www.cxoadvisory.com/technical-trading/dual-momentum-with-multi-market-breadth-crash-protection), [QuantConnect forum](https://www.quantconnect.com/forum/discussion/3152). Status: rules and numbers from CXO, consistent with QuantConnect summary on divisor formula.

```json
{
  "id": "C4",
  "name": "Keller Bold Asset Allocation (BAA), offensive/defensive with canary",
  "source_url": "https://cxoadvisory.com/momentum-investing/complex-offensive-defensive-asset-class-momentum ; primary SSRN 4166845 (PDF unreadable)",
  "source_date": "July 2022 (paper PDF metadata); CXO summary Aug 10, 2022",
  "universe": {"canary": ["SPY","VWO","VEA","BND"], "offensive_top6": ["SPY","QQQ","IWM","VGK","EWJ","VWO","VNQ","DBC","GLD","TLT","HYG","LQD"], "defensive_top3": ["TIP","DBC","BIL","IEF","TLT","LQD","BND"]},
  "data": "Yahoo daily adjusted close, month-end. BIL (about 2007) and BND (2007) limit start; unsourced recollection.",
  "signal": "Canary score = 13612W momentum. If none of the four canary assets has negative momentum: offensive mode, hold equal-weighted top 6 of offensive universe ranked by price / mean(last 13 monthly prices incl. current). Otherwise defensive mode: top 3 of defensive universe by the same ratio, equal weight, and any of the top 3 with ratio below BIL's replaced by BIL. CXO text is ambiguous ('none (any)'): the Keller paper rule (my recollection, unsourced) is offensive only if ALL canary assets have non-negative momentum, i.e. any negative triggers defensive. Verify before coding.",
  "rebalance": "Monthly",
  "sizing": "Equal weight 1/6 offensive, 1/3 defensive",
  "parameters": {"canary_momentum_weights": [12,4,2,1], "offensive_top_n": 6, "defensive_top_n": 3, "ranking_window_prices": 13, "friction_one_way": 0.001},
  "source_sample": "Dec 1970-Jun 2022, modeled returns before ETF inception.",
  "reported_performance": "Not retrievable (CXO paywalled after intro; paper PDF not parsed). Describes the strategy as 'aggressive'. In-sample/out-of-sample split not stated.",
  "post_publication_evidence": "None found; paper dated Jul 2022 so any post-publication window is only about 4 years.",
  "known_weaknesses": "Performance claims unverified; very concentrated; ambiguity in canary rule; modeled pre-ETF data; most recent and thus least-tested of the Keller family."
}
```
Source: [CXO BAA summary](https://cxoadvisory.com/momentum-investing/complex-offensive-defensive-asset-class-momentum).

```json
{
  "id": "C5",
  "name": "Antonacci Global Equities Momentum (GEM) dual momentum  [BORDERLINE vs exclusion rule]",
  "source_url": "https://cxoadvisory.com/momentum-investing/a-few-notes-on-dual-momentum-investing ; https://hedgefundalpha.com/strategies/global-equity-momentum-a-craftsmans-perspective/",
  "source_date": "Original paper 2012; book 2014 (some sources say 2015)",
  "universe": {"US_equity": "SPY (S&P 500 proxy)", "ex_US_equity": "ACWX or EFA (paper used MSCI ACWI ex-US; ETF choice UNVERIFIED)", "bond_fallback": "AGG (paper used Barclays US Aggregate; ETF choice UNVERIFIED)", "cash_reference": "BIL or SHY as T-bill proxy (UNVERIFIED)"},
  "data": "Yahoo daily adjusted close, month-end. ACWX starts 2008-03 (unsourced recollection), EFA from 2001.",
  "signal": "12-month total return. Absolute filter: if SPY 12m return > T-bill 12m return, then pick the higher 12m return of SPY and ex-US; else hold the bond fund. (T-bill comparison is from Antonacci's book, not stated in the retrieved pages; the hedgefundalpha page says the strategy moves to bonds when US stocks show negative trend and the original used 12 month lookback for both.)",
  "rebalance": "Monthly",
  "sizing": "100% in one asset",
  "parameters": {"lookback_months": 12},
  "source_sample": "1974-2011 (2012 paper), extended 1950-2018 by authors with OOS 1950-1973 and 2012-2018.",
  "reported_performance": "CXO: 1974-2013, monthly, gross: GEM 17.43% annual return, std 12.64%, Sharpe 0.87, max drawdown 22.7% vs ACWI 9.55%. Gross of costs and taxes. Extended-period figures not given in retrieved text.",
  "post_publication_evidence": "Hedgefundalpha says performance 'attractive both in- and out-of-sample' incl. 2012-2018 but gives no numbers. One blogger replication: slightly worse than Antonacci, below 17% annualized, and flagged 12 months as the best of 324 tested parameterizations (data-mining concern). Commenter reports ~33% drawdown starting Jan 2022 for a related ADM variant (unverified comment). Unverified: no independent post-2018 numbers retrieved.",
  "known_weaknesses": "Long bond bull market in sample; only one position at a time; ETF proxies differ from paper indexes; 324-parameterization sensitivity noted. Partly time-series trend, so check against the pre-registered exclusion."
}
```
Sources: [CXO](https://cxoadvisory.com/momentum-investing/a-few-notes-on-dual-momentum-investing), [Hedgefundalpha](https://hedgefundalpha.com/strategies/global-equity-momentum-a-craftsmans-perspective/).

```json
{
  "id": "C6",
  "name": "Faber GTAA 5-asset SMA10 timing  [BORDERLINE: time-series trend on several indices, likely excluded by rule]",
  "source_url": "https://www.cxoadvisory.com/technical-trading/long-term-outperformance-from-trends-defined-by-moving-averages ; primary SSRN 962461",
  "source_date": "2007, updated 2013",
  "universe": {"indices_in_paper": ["S&P 500","MSCI EAFE","10-yr Treasury","GSCI","NAREIT"], "etf_proxy_UNVERIFIED": ["SPY","EFA","IEF","GSG or DBC","VNQ"]},
  "data": "Yahoo daily adjusted close, month-end; VNQ from 2004, GSG from 2006.",
  "signal": "For each asset at month-end: if price > SMA(10 months) hold the asset, else hold cash (T-bills; ETF proxy BIL/SHY).",
  "rebalance": "Monthly, month-end, equal 20% weight per asset",
  "sizing": "20% per asset when invested, else cash",
  "parameters": {"sma_months": 10, "weights": 0.2},
  "source_sample": "1973-2012 (five assets); S&P 500 1901-2012; out-of-sample check 2006-2012.",
  "reported_performance": "Five assets 1973-2012 gross: timing 10.5% return, 7.0% std, Sharpe 0.73, MaxDD -9.5% vs buy-and-hold 9.9%, 10.3%, 0.44, -46.0%. 13-asset version 12.0% / Sharpe 0.94. Gross of costs and taxes, using indexes.",
  "post_publication_evidence": "Faber's own 2006-2012 check: timing won 3 of 7 years; sample was largely 2008 driven (CXO notes the dependence on rare conditions like 2008). Figures on the CXO page for that window may contain a transcription error.",
  "known_weaknesses": "Index data not ETFs; 10-month choice may be snooped; benefit concentrated in 2008. This is the type of strategy the brief says already failed in this repo (trend on ETFs), so likely excluded."
}
```
Source: [CXO Faber](https://www.cxoadvisory.com/technical-trading/long-term-outperformance-from-trends-defined-by-moving-averages).

### Inferences
- C1 to C4 are one family (same author, same universe overlap, 13612W, breadth rule) and are highly correlated; they test one idea (breadth-based crash protection), not four independent ones. Running all four inflates the trial count with little added independent breadth.
- Rule-clarity ranking: C1 (B, T and performance sourced) > C3 > C2 (T missing) > C4 (canary wording ambiguous, performance missing) > C5 > C6.
- VAA's published in-sample to OOS decay (CAGR 21% to 10%, Sharpe 1.24 to 0.51) suggests expectations for the whole family should be near the OOS column, not the headline figures.

### Gaps
- Could not open any SSRN primary paper (403/unparsed PDF); exact DAA T, DAA cash-asset rule, BAA performance table, ETF-level universe in PAA, and ETF substitution for GEM/Faber need checking against the PDFs.
- Allocate Smartly pages returned 404 or members-only, so no independent post-publication tracking numbers were found for any candidate. No audited live record found for DAA, VAA, PAA, BAA.
- ADM (Accelerating Dual Momentum): rule summaries disagree. Engineered Portfolio article ([link](https://engineeredportfolio.com/2018/05/02/accelerating-dual-momentum-investing/)) uses mutual funds VFINX, VINEX, VUSTX with score = sum of 1/3/6-month returns and long Treasuries as fallback; a TradingView/portfoliodb summary ([link](https://es.tradingview.com/script/LyF7R2tF)) uses SPY, SCZ, then higher of TLT/TIP by 1-month return, with the mean of 1/3/6-month returns. Allocate Smartly says SCZ data starts 1989 and its 2021 extension cut the 30-year SWR from 9.0% to 6.6% ([source](https://allocatesmartly.com/accelerating-dual-momentum/)), which is a sign of fragility when the sample was extended. ADM was not included as a candidate because the rules conflict across sources and SCZ has only about 6 years of history before 2008 gap (SCZ listed 2007, unsourced).
- Adaptive Asset Allocation (ReSolve): sources only confirm 6-month momentum, top 5 assets, monthly (via a replication, [R-bloggers](https://www.r-bloggers.com/2023/12/adaptive-asset-allocation-replication/)); the weighting scheme and universe were not confirmed, so not specified.
- Not covered in this round: Quantpedia free-entry sector rotation, risk parity variants (e.g. All Weather / permanent portfolios), bond/commodity relative strength rotations. Next round should look there, particularly for assets outside the crypto/trend family given the repo's evidence-rate rule.
- Date/ticker inception facts marked "unsourced recollection" are not from the fetched sources.
