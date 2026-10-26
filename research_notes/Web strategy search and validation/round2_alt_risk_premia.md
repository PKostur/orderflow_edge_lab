# Round 2: published alternative risk premia / anomalies implementable with US ETFs and free data

## Which candidates have exact published parameters, low equity correlation and high Sharpe?

### Takeaway
No candidate meets all of: exact published parameters, ETF-implementable, low equity correlation, net Sharpe >= 1 and post-publication support. Four candidates have enough detail to code (A to D). A and D are long-biased equity and will correlate with SPY. B and C come from single-author Quantpedia blog tests with no net-of-cost numbers. Several requested ideas (bond carry timing, currency ETF carry/value, USO/USL, hedged VIX ETPs) had no fully specified source I could read, so they are skipped or in Gaps. Fetched this session: Quantpedia pages, r-bloggers, CXO Advisory. The PDFs of Cieslak et al. and Keloharju et al. downloaded as binary and could not be read (no PDF renderer), so figures from those papers are second-hand. Marked below.

### Cited Findings

#### Candidate A: FOMC-cycle even-week equity (Cieslak, Morse, Vissing-Jorgensen)

```json
{
  "id": "A_fomc_even_week",
  "name": "Stock returns over the FOMC cycle: hold equities in even weeks (0,2,4,6) of FOMC cycle time",
  "source_url": "https://papers.ssrn.com/abstract=2687614 (Journal of Finance 74(5), 2201-2248; NYU draft https://stern.nyu.edu/sites/default/files/assets/documents/cycle_paper_cieslak_morse_vissingjorgensen.pdf)",
  "source_date": "working paper 2014/2015; JF 2019",
  "universe": ["SPY (replication used SPY; paper used CRSP-type US stock market return, T-bill as cash)"],
  "data": "Yahoo SPY adjusted close from 1993-01-29 (replication used 1994-01-01); cash leg: FRED DTB3 or TB3MS (cash leg in paper unverified); FOMC scheduled-meeting dates: federalreserve.gov FOMC historical calendars (free, manual)",
  "signal": "Cycle time: week 0 begins on day -1, the day before a scheduled FOMC announcement day; resets at each scheduled meeting (8 per year). Even weeks = 0,2,4,6. Replication entry: open at close when phase signal crosses above 0.5; exit when it crosses below 0.5; hold 5 calendar days. Exact day-index to trading-day mapping is UNVERIFIED beyond the blog's code description.",
  "portfolio": "Long SPY during even weeks, cash/T-bills in odd weeks (100% of equity). Paper also reports long even / short odd (via CXO).",
  "rebalance": "about 26 round trips per year (about 525 trades 1994-2015 in replication)",
  "parameters": {"even_weeks": [0,2,4,6], "holding_calendar_days": 5, "cost_bp_in_replication": 5, "scheduled_meetings_only": true},
  "source_sample": "1994-2013 (paper draft); CXO summary 1994-2015, 176 meetings",
  "reported_performance": "CXO summary (gross, excess over T-bills): even-week stocks 11.8% avg excess, 13.3% sd, Sharpe 0.88; buy-hold 8.3%, 19.1%, Sharpe 0.43; long even/short odd 14.8%, 21.1%, Sharpe 0.70. Blog replication SPY 1994-2015-03: gross ann ret 11.29%, sd 13.82%, Sharpe 0.82; net of 5bp 8.55%, Sharpe 0.62 (rf=0); buy-hold 9.15%, sd 19.35%, Sharpe 0.47. Correlation to equities not reported but long-only SPY in about half the weeks, so high (inferred).",
  "post_publication_evidence": "Authors say pattern holds in 2014-2016 after first draft (via search summary, not read in full). Yun & Kwon (Finance Research Letters 2023) find even-week pattern in low-risk anomalies for 1994-2020 scheduled meetings. A Univie thesis could not confirm it for European indices. No clean post-2015 out-of-sample net-of-cost test found. A 2024 CIRANO paper notes the rule lacks a theoretical foundation.",
  "known_weaknesses": "High equity beta (not a low-correlation diversifier); net Sharpe about 0.6 after 5bp round trip; paper itself blames Fed information channel that could change; FOMC calendar changes over time; in-sample replication; hedged long-even/short-odd version has lower Sharpe 0.70 and extreme turnover."
}
```
- CXO figures and rule — [CXO Advisory](https://www.cxoadvisory.com/?p=28978)
- Blog replication details and numbers — [r-bloggers FOMC cycle quantstrat](https://www.r-bloggers.com/2015/03/fomc-cycle-trading-strategy-in-quantstrat/)
- Paper abstract-level facts (equity premium earned in even weeks since 1994, JF 2019) — [SSRN](https://papers.ssrn.com/abstract=2687614), [Duke Scholars](https://scholars.duke.edu/publication/1136749)
- Later work — [Yun & Kwon FRL 2023](https://strathprints.strath.ac.uk/88240/1/Yun-Kwon-FRL-2023-Biweekly-performance-of-low-risk-anomalies-over-the-FOMC-cycle-3.pdf), [CIRANO 2024](https://cirano.qc.ca/en/summaries/2024s-02)

#### Candidate B: Front-running seasonality in country ETFs (Quantpedia, April 2025; Heston-Sadka / Keloharju et al. lineage)

```json
{
  "id": "B_country_etf_frontrun_seasonality",
  "name": "Country ETF cross-sectional front-running seasonality (rank on month T-11 return)",
  "source_url": "https://quantpedia.com/front-running-in-country-etfs-or-how-to-spot-and-leverage-seasonality/",
  "source_date": "2025-04 (data to 2025-02)",
  "universe": ["SPY","EWU","EWG","EWQ","EWI","EWD","EWN","EWP","EWK","EWL","EWC","EWJ","EWW","EWM","EWA","EWS","EWY","EWT","EWZ","EWH","EZA","FXI","INDY"],
  "data": "Yahoo adjusted close (article says Yahoo free EOD download was discontinued; use whatever source works). Monthly data from 2000. Late starters: EZA (2003), FXI (2004), INDY (2009).",
  "signal": "At each month-end t, rank all ETFs cross-sectionally on their return in month T-11 (e.g. at end of March, rank on prior May's return, to pick for April).",
  "portfolio": "Long-only. Final: equal-weighted average of six strategies holding top 3,4,5,6,7,8 ETFs. Within-strategy weights not stated (assume equal: UNVERIFIED). Benchmark: equal-weight all 23 ETFs.",
  "rebalance": "monthly",
  "parameters": {"rank_lag_months": 11, "top_n_set": [3,4,5,6,7,8], "n_universe": 23},
  "source_sample": "2000 to 2025-02",
  "reported_performance": "NOT AVAILABLE in text: performance tables are images; no CAGR/Sharpe/DD/correlation numbers seen. Author states single-ETF variant had a significant downturn since 2019 and that some higher individual results have low credibility.",
  "post_publication_evidence": "None. The 3-8 range was chosen because the middle performed best (in-sample selection). Underlying academic evidence: Heston & Sadka (JFQA 2010) report same-month seasonality for Canada, Japan, 12 European countries, >1%/month global strategy excess, sample 1985-2006 (via search summary); Keloharju-Linnainmaa-Nyberg (JF 2016) report similar seasonalities in international stock indices, commodities, anomalies (country index parameters NOT verified, PDF unreadable).",
  "known_weaknesses": "Long-only equity ETFs, so high correlation to SPY; author says drift is weaker in equities than commodities; tuned top-N range; no costs; no numbers seen; the Quantpedia signal is the author's own front-running variant, not the paper's exact same-month signal (paper uses T-12 style lags)."
}
```
- Spec — [Quantpedia country ETF front-running](https://quantpedia.com/front-running-in-country-etfs-or-how-to-spot-and-leverage-seasonality/)
- Heston-Sadka summary — [IDEAS/RePEc](https://ideas.repec.org/a/cup/jfinqa/v45y2010i05p1133-1160_00.html)
- Heston-Sadka stock version (decile long-short, top 30% NYSE/AMEX, 1965-2002): about 8.6%/yr, Sharpe 0.38, costs not deducted, returns largely eliminated after demeaning by seasonal average — [Quantpedia #125](https://quantpedia.com/strategies/12-month-cycle-in-cross-section-of-stocks-returns)
- KLN meta-strategy across 15 anomalies 1.88%/month (t=6.43) and stock-level 13%/yr — search summary of [NBER w20815](https://www.nber.org/papers/w20815)

#### Candidate C: Front-running commodity sector seasonality (Quantpedia, Dec 2024)

```json
{
  "id": "C_commodity_sector_frontrun",
  "name": "Commodity sector ETF time-series front-running seasonality (X-11)",
  "source_url": "https://quantpedia.com/traders-guide-to-front-running-commodity-seasonality/",
  "source_date": "2024-12",
  "universe": ["DBA","DBB","DBE","DBP"],
  "data": "Yahoo adjusted close, daily, 2007-01 to 2024-06 (DBA/DBB/DBE/DBP start 2007)",
  "signal": "At each month-end, for each ETF compute percentile of the monthly return of month X-11 (prior year's following month) within that ETF's trailing 12 monthly returns. Exact percentile formula and tie handling UNVERIFIED.",
  "portfolio": "Top 50% percentile: +25% each; bottom 50%: -25% each; net exposure -100% to +100%.",
  "rebalance": "monthly",
  "parameters": {"lag_months": 11, "weight_per_etf": 0.25, "split_percentile": 0.5},
  "source_sample": "2007-01 to 2024-06",
  "reported_performance": "Model 2 (X-11): CAR 6.71%, vol 12.10%, Sharpe 0.55, MaxDD -20.43%. Naive X-12: CAR -4.54%, Sharpe -0.40, MaxDD -60.26%. Plus correlation filter (windows unspecified, found after the fact): CAR 7.62%, Sharpe 0.81, MaxDD -11.98%. Correlation to equities not reported (long-short sector exposure, plausibly low: inferred only). Costs not stated.",
  "post_publication_evidence": "None.",
  "known_weaknesses": "4 ETFs, 17.5 years, single author, in-sample; the X-11 vs X-12 choice differs by 11 Sharpe points of sign, which suggests a specification search; filter not reproducible; Sharpe below 1; no costs; no academic grounding for the front-running shift in this exact form."
}
```
- All numbers — [Quantpedia commodity front-running](https://quantpedia.com/traders-guide-to-front-running-commodity-seasonality/)

#### Candidate D: Betting against beta in country equity indices (Frazzini & Pedersen) via country ETFs

```json
{
  "id": "D_bab_country_etf",
  "name": "BAB in country equity indexes, country-ETF implementation",
  "source_url": "http://pages.stern.nyu.edu/~lpederse/papers/BettingAgainstBeta.pdf (rules summarized at https://quantpedia.com/strategies/betting-against-beta-factor-in-country-equity-indexes)",
  "source_date": "paper 2014 (JFE); Quantpedia page undated",
  "universe": "Country ETFs; ticker list NOT given on the page (13 instruments from Table 2 of paper, names not read). Could reuse the Candidate B iShares list but that is my assumption, not the source.",
  "data": "Yahoo adjusted close; benchmark: MSCI US index (page); proxy such as SPY is UNVERIFIED; rf FRED TB3MS",
  "signal": "Beta of each country vs MSCI US over 1-year rolling window; rank ascending by beta.",
  "portfolio": "Low-beta portfolio long, high-beta portfolio short, weights by ranked betas (formula not on page; paper uses rank-based weights, not verified here), each rescaled to beta 1 at formation, so zero-cost zero-beta.",
  "rebalance": "monthly, calendar month-end",
  "parameters": {"beta_window_years": 1, "n_instruments_in_paper": 13},
  "source_sample": "1980-2009 (as listed on Quantpedia)",
  "reported_performance": "about 6.8%/yr (0.55%/month), vol 13.08%, Sharpe 0.51, max DD -46.56% (flagged 'not stated' on the same page, treat as unverified). Paper-level US stock BAB Sharpe 0.78, 1926-2012-03, not country. Hedge value rated 'Partially'.",
  "post_publication_evidence": "Quantpedia out-of-sample section empty. None read.",
  "known_weaknesses": "Sharpe 0.51 gross, not >=1; ETF history short (country ETFs from 1996); leverage needed for beta-1 scaling and zero-beta construction conflicts with repo no-leverage rule; paper returns are not ETF returns; crowding warning."
}
```
- Spec and stats — [Quantpedia BAB country](https://quantpedia.com/strategies/betting-against-beta-factor-in-country-equity-indexes)

#### Weaker or sector-level items (no coded spec of quality)
- Quantpedia US sector front-running (XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY; Yahoo 1998-12 to 2024-09; rank on same-month prior year shifted one month; best variant holds 2 ETFs long): performance tables are images, no numbers seen; true seasonality at best comparable to benchmark — [Quantpedia sectors](https://quantpedia.com/front-running-seasonality-in-us-stock-sectors/). Long-only equity so high SPY correlation; not recommended.
- Sector momentum long-short (3 best vs 3 worst of 9 SPDR ETFs, 12-month lookback, 1-month hold, 1999-2023): article says high sector correlation and ETFs reduced traditional long-short sector momentum; numbers not seen. Also falls under the repo's momentum exclusions in spirit — [Quantpedia](https://quantpedia.com/how-to-improve-etf-sector-momentum/)
- FX carry (Quantpedia): long 3 highest-rate and short 3 lowest-rate currencies, monthly; source Deutsche Bank carry index 1989-2009 return 7.27%, vol 9.6%, Sharpe 0.29, DD -32.05%; no ETF implementation listed; not hedge for equities. Rejected — [Quantpedia FX carry](https://quantpedia.com/strategies/fx-carry-trade)
- VIX: Quantpedia says short-vol leg is unsuitable as an equity hedge. A 2026 Quantpedia Awards paper claims Sharpe 1.0, equity correlation about 15%, but it is the author's own promotional claim and I read no parameters. Not specifiable — [Quantpedia VIX term structure](https://quantpedia.com/strategies/exploiting-term-structure-of-vix-futures)

### Inferences
- None of A to D clears the bar of net Sharpe >= 1 with a verifiable low-correlation profile. The best low-correlation candidate is C (long/short time-series commodity seasonal), but it has Sharpe 0.55 and weak evidence.
- A is the best-documented but is equity timing with an in-sample net Sharpe about 0.6 and high correlation to SPY; it is also not an independent-breadth asset (SPY only), which conflicts with the repo evidence-rate rule for new work. Its one real advantage is a short time-to-answer on daily P&L.
- B and C use assets outside the 10-coin crypto factor, so they raise breadth, but Sharpe expectations should be about 0.5 or lower; a pre-registered test is the only way to judge them.
- Sample-selected parameters in B (top 3-8) and C (X-11 vs X-12, correlation filter) must not be re-tuned; use the stated values.

### Gaps
- Could not read PDFs (no renderer): exact Cieslak et al. tables (net-of-cost results, subperiods, 2014-2016 holdout), Keloharju et al. country-index and commodity tables, Heston-Sadka international results. Needs text-extractable copies.
- No fully specified source found for: bond term-premium/carry timing with FRED yields and Treasury ETFs, currency-ETF carry/value (FXE, FXY, etc.), USO vs USL term-structure pair, hedged VIX ETP strategy, ETF-level BAB with ticker list. Searches returned only descriptions or promotional claims.
- Quantpedia country and sector ETF tables (CAGR, Sharpe, drawdown) are images; numbers not recoverable from text.
- No post-2015 out-of-sample net-of-cost test of the FOMC even-week rule found.
- Equity correlation figures were not reported by any source for A to D.
