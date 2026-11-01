# Round 1: Calendar, event and volatility-premium strategies on free daily data

Scope note: no backtests were run. Everything below is what sources state. Several figures come from secondary summaries (Quantpedia, blogs); this is flagged per item. Primary PDFs for Lucca-Moench (NY Fed SR512) and Ko-Yang could not be text-extracted by the fetch tool, so their details come from secondary summaries.

## Q1. Which published, fully specified candidates can be coded on free daily data?

### Takeaway
Six candidates are listed. Only three have a daily-data rule that matches the published rule closely (turn-of-month, overnight, VIX-ratio short-vol). Pre-FOMC and pre-holiday are published on intraday or CRSP data and need a daily proxy. Option-expiration week has conflicting window definitions across sources. Post-publication evidence is negative or weak for pre-FOMC (post-2015) and pre-holiday (large caps), and mixed for turn-of-month and overnight.

### Cited Findings

**C1. Turn-of-the-month, SPY**
```json
{
  "id": "C1_TOM",
  "name": "Turn-of-the-month (last trading day of month through 3rd trading day of next month)",
  "source_url": "https://quantpedia.com/Screener/Details/41 ; McConnell & Xu, Financial Analysts Journal 2008 (https://www.cfapubs.org/doi/pdf/10.2469/faj.v64.n2.11 ; SSRN 917884)",
  "source_date": "Lakonishok & Smidt 1988 (original); McConnell & Xu 2008",
  "universe": ["SPY"],
  "data": "Yahoo daily adjusted close SPY, from 1993-01-29; optional cash proxy ^IRX or FRED DTB3. Long history alt: ^GSPC (1950) for price-only",
  "signal": "Be long at the close of the trading day before month-end (day -1) and exit at the close of trading day +3 of the new month (4 trading days of returns: days 0,+1,+2,+3 per ETFdb/Quantpedia wording). Note ambiguity: Quantpedia says 'buy one day before month-end, sell at close on third trading day of new month' and that 'some papers say 4 days'; McConnell-Xu table uses days -1 to +3 returns, i.e. entry at close of day -2. Code both and pre-register one.",
  "holding": "4 trading days per month (about 5 to 6 closes), flat/cash otherwise",
  "sizing": "100% long during window, 0% otherwise, no leverage",
  "parameters": {"entry_day": -1, "exit_day": 3, "window_days": 4},
  "event_calendar": "Not needed beyond the NYSE trading calendar (derive from SPY date index)",
  "source_sample": "McConnell & Xu: 1926-2005 US; Quantpedia OOS 1987-2005; paper reports effect in 31 of 35 countries",
  "reported_performance": "Quantpedia summary of paper: mean daily return 0.15% on turn days vs 0.01% other days (diff 0.15%, t=7.81); about 7.2% annual, vol 6.9%, Sharpe 1.04 (Quantpedia estimates, in-sample; transaction costs not reported)",
  "post_publication_evidence": "Maberly & Waggoner (Atlanta Fed WP 2000-11): TOM effect in S&P 500 futures disappears after 1990 (https://www.atlantafed.org/research/publications/wp/2000/11.aspx). Journal of Financial Planning 2011: in ETF era effect is concentrated on first trading day of month (https://www.financialplanningassociation.org/article/journal/APR11-turn-month-anomaly-age-etfs-reexamination-return-enhancement-strategies). ETFtrends/Norgate 2024 analysis (1980-Q3 2024) reports significance (practitioner, not verified): https://www.etftrends.com/etf-strategist-channel/turn-month-effect/ . Quantpedia notes Carchano & Tornero 2011 found it the only persistent calendar effect in S&P 500 futures.",
  "known_weaknesses": "Long-only equity beta, so any strategy return must be compared with time-in-market-matched beta, not zero. Window ambiguity. Effect may have shrunk to day +1 only. Only about 17% time in market so total P&L is small."
}
```

**C2. Pre-FOMC announcement drift, SPY daily proxy**
```json
{
  "id": "C2_PREFOMC",
  "name": "Pre-FOMC announcement drift",
  "source_url": "https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr512.html (Lucca & Moench; J. Finance Feb 2015). Daily-data replication: https://www.r-bloggers.com/2015/03/update-on-the-pre-fomc-announcement-drift/",
  "source_date": "NY Fed SR512 Sept 2011 (rev. 2013); Journal of Finance 2015",
  "universe": ["SPY"],
  "data": "Yahoo daily adjusted close SPY from 1993-01-29. Paper itself uses S&P 500 index and futures with intraday timing.",
  "signal": "Published rule is a 24-hour window ending at the scheduled FOMC announcement (approx. 2:15pm ET), which is NOT reproducible on daily bars. Daily proxy used in the R-bloggers replication: hold SPY from close of day before scheduled meeting announcement day to close of announcement day, scheduled meetings only; the same post also found a T-1 effect.",
  "holding": "1 trading day (close T-1 to close T) in the proxy; 24h in the paper",
  "sizing": "100% long on event days, flat otherwise",
  "parameters": {"entry": "close T-1", "exit": "close T (announcement day)", "meetings": "scheduled only", "window_hours_in_paper": 24},
  "event_calendar": "Federal Reserve FOMC historical materials and calendars (federalreserve.gov/monetarypolicy/fomc_historical_year.htm and fomccalendars.htm), free. Scheduled vs unscheduled flag must be set by the coder; the R-bloggers post used scheduled only.",
  "source_sample": "Lucca & Moench: 1994-2011 (per NY Fed summary, 33bp avg excess return on FOMC days vs ~1bp other days; premium accounts for more than 80% of US equity premium over the past 17 years). Pre-1994 close-to-close shows essentially no premium.",
  "reported_performance": "In-sample (paper): about 33bp per FOMC day. R-bloggers daily SPY replication Jan 1994-Mar 2011, 138 meetings: mean excess 0.33% (SD 1.17%), diff vs non-FOMC days +0.31%, CI 0.11% to 0.50%. Out-of-sample Apr 2011-Jan 2015, 31 meetings: mean 0.26% (SD 1.37%), CI about -0.21% to +0.82%, not significant; T-1 return -0.16%.",
  "post_publication_evidence": "Kurov, Wolfe & Gilbert ('The Disappearing Pre-FOMC Announcement Drift', Finance Research Letters 2021; draft https://www.skidmore.edu/economics/documents/KurovWolfeGilbert-TheDisappearingPre-FOMC-Announce-Drift-200914.pdf): extended to Dec 2019, drift essentially disappears after 2015. Boguth, Gregoire & Martineau 2019: drift limited to meetings with press conferences. Ignatieva & Ohashi 2025 (Applied Economics, https://ideas.repec.org/a/taf/applec/v57y2025i17p2021-2037.html) report a real but short-lived drift (details not read).",
  "known_weaknesses": "Daily close-to-close proxy includes post-announcement reaction hours on day T, which is a different return from the paper's pre-announcement window. About 8 events per year so about 8 x 30 = 240 events in total; very low power. Post-2015 evidence is against it. Scheduled-meeting classification needs care."
}
```

**C3. Overnight (close-to-open) drift in SPY**
```json
{
  "id": "C3_OVERNIGHT",
  "name": "Overnight vs intraday returns: buy SPY at close, sell at next open",
  "source_url": "Cliff, Cooper & Gulen, 'Return Differences between Trading and Non-trading Hours: Like Night and Day' (SSRN, 2008); Alpha Architect replication https://alphaarchitect.com/trading-costs-wipe-out-the-overnight-return-anomaly/ (page not fetchable, 403; figures from search snippet); CXO https://www.cxoadvisory.com/calendar-effects/buy-at-the-close-and-sell-at-the-open",
  "source_date": "2008 (Cliff et al.); Alpha Architect 2020-06-16",
  "universe": ["SPY"],
  "data": "Yahoo daily Open and Close (use unadjusted Open/Close for day returns but adjust for splits/dividends consistently; dividends are paid on ex-date and affect open), from 1993-01-29",
  "signal": "Every trading day: enter at close of day t, exit at open of day t+1. No conditioning.",
  "holding": "close to next open, every day",
  "sizing": "100% long overnight, flat intraday",
  "parameters": {"entry": "close", "exit": "next open", "conditioning": "none"},
  "event_calendar": "None",
  "source_sample": "Cliff et al.: 1993-2006 intraday data across stocks, indexes, futures, ETFs (per search summary). Alpha Architect: SPY Jan 1993-Jan 2020.",
  "reported_performance": "Alpha Architect (via snippet): cumulative price returns 717% overnight, 627% buy-and-hold, 12% intraday, 1993-2020, but concluded trading costs wipe out the anomaly (source title). Other paper on S&P futures 1998-2019: close-close 4.5% p.a., overnight 3.1%, intraday 1.4% (https://conference.nber.org/conf_papers/f78239/f78239.pdf), which also argues the premium is earned in a 1-hour window before the European open.",
  "post_publication_evidence": "Alpha Architect 2020 argues costs eliminate it. Lou, Polk & Skouras (JFE 2019, https://personal.lse.ac.uk/polk/research/TugOfWar.pdf) is cross-sectional, not an index timing test. Quantpedia notes OHLC open prices can mislead (https://quantpedia.com/dangers-of-relying-on-ohlc-prices-the-case-of-overnight-drift-in-gdx-etf/). Berkman et al. 2012 attribute part of the pattern to attention-driven retail buying at the open (secondary, via search summary).",
  "known_weaknesses": "Yahoo 'Open' for SPY is the opening auction/first print, not necessarily executable; 2 trades per day so costs and slippage dominate; backtesting on OHLC flatters it (Quantpedia notes small difference vs 9:31 execution). Dividend handling around ex-date creates artefacts."
}
```

**C4. Option-expiration week, large caps**
```json
{
  "id": "C4_OEW",
  "name": "Option-expiration week effect (long S&P 100 in expiration week, cash otherwise)",
  "source_url": "https://quantpedia.com/strategies/option-expiration-week-effect ; Stivers & Sun SSRN 1571786 (https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1571786)",
  "source_date": "Stivers & Sun, SSRN 2010 (year not stated on Quantpedia page)",
  "universe": ["OEF (S&P 100 ETF) or SPY"],
  "data": "Yahoo daily adjusted close OEF (from 2000-10-23) or SPY (from 1993); ^OEX index price from 1983 as long-history alt",
  "signal": "Hold during option-expiration week, otherwise cash. Quantpedia text: 'the week before options expiration (the Friday before each 3rd Saturday)'. SOURCE CONFLICT: Quantpedia's composite seasonal case study (https://quantpedia.com/quantpedias-composite-seasonalcalendar-strategy-case-study/) instead says buy SPY at close on the Friday before the 2nd Saturday of each month and sell at close of the following Thursday. The two windows differ by a week. Must be resolved against the Stivers-Sun paper before coding; not resolved here.",
  "holding": "about 5 trading days per month",
  "sizing": "100% long in window, cash otherwise",
  "parameters": {"window_definition_A": "week ending on 3rd Friday", "window_definition_B": "Fri before 2nd Saturday close to following Thursday close", "frequency": "monthly"},
  "event_calendar": "Third Friday of each month (derive from the calendar; shift to Thursday when the Friday is an exchange holiday)",
  "source_sample": "Quantpedia backtest 1988-2010; Stivers & Sun high-O/S test 28 stocks 1996-2008",
  "reported_performance": "Quantpedia estimates (not the paper): 9.3% annual incl. cash at ~4%, vol 8.7%, Sharpe 0.61, max DD -15.14%; weekly return 0.528% in OEW. Composite-strategy page quotes 4.93% annual, max DD 20.39% for the SPY version. In-sample.",
  "post_publication_evidence": "None found. Quantpedia page does not discuss decay. Both halves of 1996-2008 positive (67.9bp and 70.7bp), which is in-sample.",
  "known_weaknesses": "Window definition conflict; Quantpedia's return numbers are its own estimates; SPY version differs from S&P 100 stocks used in paper; cash-yield assumption drives much of reported return."
}
```

**C5. VIX / VIX3M term-structure short-volatility timing**
```json
{
  "id": "C5_VIXRATIO",
  "name": "Implied-volatility ratio timing of short-vol ETN (VIX/VIX3M below 1 and below its 60d SMA)",
  "source_url": "http://www.r-bloggers.com/?p=158208 ('Which Implied Volatility Ratio Is Best?', QuantStrat TradeR syndication). Secondary variant: QuantConnect community algorithm using vixRatio < 0.95 (https://www.quantconnect.com/terminal/cache/embedded_backtest_4c5d053d3f4e3efdfb726f3b19cab329.html)",
  "source_date": "Not stated in fetched content (blog post; likely about 2017, unverified)",
  "universe": ["^VIX", "^VIX3M (formerly ^VXV)", "^VXMT (6-month; check Yahoo availability)", "SVXY as substitute for the delisted XIV (SVXY leverage changed from -1x to -0.5x in Feb 2018)"],
  "data": "CBOE daily CSVs for VIX3M, VXMT, VIX (cboe.com, free); Yahoo ^VIX, ^VIX3M, SVXY (from 2011-10-04). Original used a long-history XIV file.",
  "signal": "For ratio R in {VIX/VIX3M ('short'), VIX/VXMT ('medium'), VIX3M/VXMT ('long')}: go long the short-vol product when R < 1 AND R < SMA(R, 60). Otherwise out of the market. Signal lagged 2 days before being applied to product returns.",
  "holding": "while condition true, re-evaluated daily",
  "sizing": "100% long short-vol product or flat",
  "parameters": {"ratio_threshold": 1.0, "sma_length": 60, "signal_lag_days": 2, "qc_variant_threshold": 0.95},
  "event_calendar": "None",
  "source_sample": "Not stated in the article",
  "reported_performance": "Blog, XIV returns, in-sample, no costs: VIX/VIX3M annualized return 0.5485, Sharpe 1.416, worst drawdown 0.5247; VIX3M/VXMT annualized 0.6386, Sharpe 1.686, worst DD 0.3358. QuantConnect variants (self-published): CAGR 8.8% with DD 65.5%, Sharpe 0.39 in one version; CAGR 16.4%, DD 17.8%, Sharpe 0.87 in another.",
  "post_publication_evidence": "None found for this exact rule. XIV was terminated after Feb 2018 so the published instrument cannot be traded; no out-of-sample study located.",
  "known_weaknesses": "Three ratios tested and the best one chosen in the post (selection bias). Instrument substitution (XIV to SVXY at half the leverage) changes the strategy. Feb 2018 short-vol collapse; XIV return series is not on free Yahoo. ETN/ETF decay from contango roll is embedded in the series. Sample period unstated."
}
```

**C6. Pre-holiday effect (Ariel 1990; Ko and Yang)**
```json
{
  "id": "C6_PREHOLIDAY",
  "name": "Pre-holiday effect: long on the trading day before NYSE holidays",
  "source_url": "Ariel (1990) 'High stock returns before holidays' (J. Finance); Ko & Yang, Critical Finance Review vol 13 (2024): https://cfr.ivo-welch.org/published/papers/ko2021pre.pdf (PDF text not extractable; findings via search summary)",
  "source_date": "Ariel 1990; Ko & Yang CFR 2024 (working paper June 2021)",
  "universe": ["SPY"],
  "data": "Yahoo daily adjusted close SPY from 1993",
  "signal": "Hold the close-to-close return of the last trading day before each NYSE market holiday. Exact holiday list used by Ariel/Ko-Yang was not retrieved; coder must pre-register the NYSE holiday set (the paper's list could not be read).",
  "holding": "1 trading day per holiday (about 8 to 9 per year)",
  "sizing": "100% long on event days",
  "parameters": {"event_day": "last trading day before holiday", "holiday_list": "not retrieved from primary source"},
  "event_calendar": "NYSE holiday calendar (free, nyse.com); can also be inferred from gaps in SPY dates, but multi-day gaps include weekends",
  "source_sample": "Ariel: CRSP 1963-1982",
  "reported_performance": "Ariel: pre-holiday average returns 9 to 14 times other days; proportion of rising stocks 85.6% equal-weighted, 75% value-weighted CRSP vs 55.8% and 53.8% other days (in-sample, via search summary)",
  "post_publication_evidence": "Ko & Yang: effect now exists only among small firms; for large firms differences are insignificant, especially after 1990 (via search summary of the paper). SPY test therefore expected to be null; useful mainly as a pre-registered negative control.",
  "known_weaknesses": "Large-cap null after 1990 per the later study; very few trades; holiday definition not confirmed."
}
```

### Inferences
- C1 and C3 are the most mechanically reproducible on Yahoo daily data. C3 is cost-dominated, so it should be judged with an explicit cost assumption.
- C2 daily proxy does not equal the published 24-hour intraday window; a daily test is a weaker test than the paper, and the evidence after 2015 suggests the effect is gone.
- C5 cannot be tested "as published" because XIV is delisted; any SVXY test is a modified strategy and the ratio-selection step in the post is a multiple-testing issue.
- C6 is a low-prior candidate and best treated as a control.

### Gaps
- Primary-text confirmation of C1 window (day -1 entry vs day -2), C4 window (3rd-Friday week vs earlier), and C6 holiday list.
- Date of the C5 blog post and sample period; Yahoo availability of ^VXMT not checked.
- Alpha Architect page returned 403, so its figures come from a search snippet.

## Q2. Which candidates were screened out, and why?

### Takeaway
VIX-futures basis and options-based volatility-premium strategies fail the free-data rule; the 2026 QuantConnect dual-VIX strategy lacks complete published thresholds; month-end flow papers give effects but no codable rule in what was retrieved.

### Cited Findings
- Simon & Campasano VIX futures basis: sell nearest VIX future with at least 10 trading days to maturity when daily roll (front future minus VIX divided by business days to settlement) exceeds +0.10 (buy if below -0.10), hold 5 trading days, hedge with E-mini S&P futures. Backtest 2007-2011 indicative 19.67% p.a. (Quantpedia estimate); Quantpedia's own later out-of-sample test was slightly negative, "alpha is deteriorating". Excluded because it needs VIX futures and E-mini data, which are not on free Yahoo daily data. — [Quantpedia](https://quantpedia.com/strategies/exploiting-term-structure-of-vix-futures); paper: [EFMA PDF](http://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2013-Reading/papers/VIX%20paper_EFMA.pdf)
- QuantConnect 'dual VIX signal' VRP harvest: expected VRP = VIX minus annualized stdev of last 10 daily SPY returns, plus VIX/VIX3M term structure; short VIXY, SPY as collateral; author-reported Sharpe 0.729 for Jan 2016-Jul 2026. Sources disagree on 10-day vs 21-day window and give no single entry threshold, so it is skipped for lack of complete published parameters. Self-published backtest. — [QuantConnect research](https://www.quantconnect.com/research/21143/harvesting-the-volatility-risk-premium-with-a-dual-vix-signal/)
- Month-end liquidity (Rinne, Suominen, Vaittinen) reports return reversals around the last monthly settlement day T-3, stronger with mutual-fund ownership; Etula et al. in RFS 2020. No exact trade rule retrieved. — [OUP RFS](https://academic.oup.com/rfs/article/33/1/75/5494694)
- Treasury month-end: Hartley & Schwarz (2019) report positive, significant Treasury returns in the last days of the month linked to insurer rebalancing; NY Fed (Sept 2024) shows Treasury trading volume concentrated on the last trading day. No codable rule retrieved. — [NY Fed Liberty Street](https://libertystreeteconomics.newyorkfed.org/2024/09/end-of-month-liquidity-in-the-treasury-market/); [Wharton Rodney White Center paper](https://rodneywhitecenter.wharton.upenn.edu/wp-content/uploads/2019/12/17-19.Schwarz.pdf)
- VIX9D/VIX crossover (long SVXY when VIX9D below VIX, exit on cross-over) appears on a TradingView idea; no sample or performance retrieved, so skipped. — [TradingView](https://www.tradingview.com/chart/VIX/)  (search result list only; page not read)

### Inferences
- A pre-registered Treasury/month-end candidate could be built from Hartley-Schwarz (TLT/IEF last-days-of-month long) but the exact days were not confirmed, so I did not specify it.

### Gaps
- No academic VIX term-structure rule on free index data (spot VIX/VIX3M) with an explicit published out-of-sample study was found.
- Payday anomaly, FOMC-cycle (Cieslak et al.) and VRP-timing papers using intraday realized variance were not examined.

## Q3. Which have credible post-publication evidence?

### Takeaway
Credible, documented post-publication tests exist for pre-FOMC (decayed after 2015), pre-holiday (large caps null after 1990), and turn-of-month (mixed, shrinking to day +1). Overnight has a costs-based refutation. Option-expiration week and the VIX-ratio rule have no post-publication tests found.

### Cited Findings
- Pre-FOMC drift disappeared after 2015 in extended sample — [Kurov, Wolfe, Gilbert](https://www.skidmore.edu/economics/documents/KurovWolfeGilbert-TheDisappearingPre-FOMC-Announce-Drift-200914.pdf)
- Daily SPY out-of-sample 2011-2015 positive but insignificant — [R-bloggers](https://www.r-bloggers.com/2015/03/update-on-the-pre-fomc-announcement-drift/)
- TOM gone after 1990 in futures (Atlanta Fed) and concentrated on day 1 in ETF era — [Atlanta Fed](https://www.atlantafed.org/research/publications/wp/2000/11.aspx); [FPA](https://www.financialplanningassociation.org/article/journal/APR11-turn-month-anomaly-age-etfs-reexamination-return-enhancement-strategies)

### Inferences
- Suggested priority if only some candidates are run: C1, C3, C5 (with the SVXY caveat), then C4 once the window is resolved, then C2 and C6 as likely-null checks.

### Gaps
- Evidence cited in Q3 comes from search summaries and secondary pages; none was independently re-estimated.
