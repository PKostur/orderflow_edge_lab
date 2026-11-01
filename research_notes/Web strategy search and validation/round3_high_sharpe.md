# Round 3: published strategies with long-sample net Sharpe >= 1.5, low equity correlation, testable on free daily data

Research date 2026-10-11. About 14 tool calls. Three primary PDFs read in full (Lou-Yan-Zhang May 2013 draft, Hartley-Schwarz Nov 2019, Savor-Wilson June 2013 draft). Page numbers below are PDF page numbers of those files. No backtests were run.

## Q1. Do Treasury auction-cycle effects (Lou, Yan & Zhang 2013) have an ETF implementation that reaches net Sharpe >= 1.5?

### Takeaway
No. The published net Sharpe is 0.84 (1998-2008 only), the trade needs on-the-run 2y/10y notes and 6m bills (CRSP), and the post-2010 evidence says the effect weakened. It is not testable "exactly as published" on Yahoo ETFs.

### Cited Findings
- Sample Jan 1980 to Jun 2008; 332 2y, 210 5y, 132 10y note auctions; prices from CRSP daily Treasury file; auction dates from the Treasury website (p.7) — [Lou, Yan, Zhang (HKUST copy of May 2013 draft)](https://ifr.hkust.edu.hk/uploads/upload/files/20250212/f5cba4b7e2aa3ada8477ad2fc38fab02.pdf)
- Strategy (p.2, p.14-15, Table V p.38): short on-the-run 2y note, long duration-matched mix of on-the-run 6m bill and 10y note, from t days before the auction date to the auction day; reverse (long 2y, short the hedge) from auction day to t days after. t ranges 1..10. Hedge weights roughly 20% 10y and 80% 6m bill (p.16) — same source
- Table V Panel A (1980-2008, gross, 319 obs): Sharpe 1.08 at t=10, 1.20 at t=7. Panel B (1998-2008, gross, 116 obs): Sharpe 1.44 at t=10. Panel C (1998-2008, after special-repo funding and bid-ask spreads): Sharpe 0.84 at t=10, 0.73 at t=7, and for t<=6 trading costs make it unprofitable (p.16, p.38) — same source
- Cost model: bid-ask 1.46 bp per leg-set, two round trips per month = 2.92 bp/month (p.16) — same source
- Authors compare 0.84 with currency carry 0.59-0.95 and stock momentum 0.47-0.75 (p.16) — same source
- A web-search summary quoted "1.44 pre-cost and 0.9 post-cost"; the paper itself says 0.84 net, so treat 0.9 as a rounding or paraphrase error — contradicted by the paper above; search summary at [Dufresne discussion / search result](https://www.epfl.ch/labs/sfi-pcd/wp-content/uploads/2021/07/Discussion-of-Anticipated-and-Repeated-Shocks-in-Liquid-Markets-2011.pdf) (that PDF could not be text-extracted)
- 2y-note-only effect: 5-day post-auction return exceeds 5-day pre-auction return by 8.89 bp (t=2.93); 5y: 22.54 bp (t=3.67); 10y: 23.84 bp (t=1.78) (p.1, p.10, Table III p.34) — same source
- Post-2010 weakening: Somogyi, Wallen, Xu (2025) report pre-2010 post-auction yield declines of 1.5 bp concentrated in strong-demand auctions, reversed after 2010; also dealers moved from net short to net long Treasuries after the GFC — [Somogyi-Wallen-Xu 2025](https://finance.darden.virginia.edu/wp-content/uploads/2025/12/Somogyi_Wallen_Xu_2025_What_Treasury_Auctions_Reveal_About_Investor_Demand.pdf) (found via search summary, not read in full)
- Amin and Tedongap attribute the price pressure to slow-moving capital rather than dealer capacity and report a >45% fall in the TIPS auction share allocated to primary dealers — [ESSEC listing](https://faculty.essec.edu/research/the-changing-landscape-of-treasury-auctions) (abstract-level only)
- No ETF-level or post-2008 replication of the Lou-Yan-Zhang trade was found. A vendor sells a TLT "auction week" seasonal system (about 5 trades a year, about 3-day holds) with paywalled, hypothetical results — [Trade Machine](https://trademachine.substack.com/p/strategy-seasonal-long-trade-in-tlt)

### Inferences
- Net 0.84 is about half the 1.5 bar even in the favourable 1998-2008 window, before any post-publication decay. A 3-leg note/bill trade replaced by SHY/IEF/TLT would change the hedge and lose the on-the-run effect that the paper says drives the result for the auctioned security.
- The auction calendar itself is free (TreasuryDirect), but ETF proxies are a different strategy from the published one.

### Gaps
- Did not read Amin-Tedongap or Somogyi et al. in full. No free source for on-the-run note prices.

## Q2. Do macro-announcement-day effects (Savor & Wilson) give a low-equity-correlation strategy with Sharpe >= 1.5?

### Takeaway
No. The effect is long equity (beta) on about 9 days a quarter, so correlation to the S&P 500 is high by construction. The headline "Sharpe" is a per-announcement-day figure scaled by sqrt(252), not the Sharpe of a tradable annual return stream, and the premium is contested.

### Cited Findings
- Announcement days = BLS inflation (CPI before Feb 1972, PPI after), BLS employment situation, and scheduled FOMC rate decisions from 1978; unscheduled FOMC meetings excluded; sample 1964-2011; announcement days are 11.34% of trading days (p.6, Table 5 p.64) — [Savor & Wilson "Asset Pricing: A Tale of Two Days", June 2013](https://faculty.wharton.upenn.edu/wp-content/uploads/2013/06/draft20130612pp-full.pdf)
- Market excess return 10.6 bp on announcement days vs 1.0 bp on other days (Table 4 Panel B, p.62); about 74% of cumulative market log excess return earned on announcement days (Table 5 p.64) — same source
- Figure 10 (p.52) plots the annualized market Sharpe on announcement days at roughly 1.6 (bar read from the chart, not a printed number), versus roughly 1.35 for turn-of-month days and roughly 0.8 for January; non-announcement days about 0.15 — same source. The authors say announcement-day volatility is only slightly higher, so the Sharpe is "an order of magnitude" higher (p.4)
- Earlier paper (1958-2009): 11.4 bp vs 1.1 bp (p.3) — same source
- Critiques: Management Science "Is There a Macro-Announcement Premium?" estimates the premium as small after removing monetary-policy surprises and small-sample noise — [INFORMS](https://pubsonline.informs.org/doi/10.1287/mnsc.2024.06960); an AEA 2022 paper says the concentration may reflect inadvertent sample selection of announcement sets and a day-of-month effect — [AEA program](https://aeaweb.org/conference/2022/preliminary/paper/ktNibY2Y)
- 2025-era NBER survey figure quoted in search results: 10.68 bp vs 0.93 bp over 1961-2023, 44 announcement days a year, 4.65% a year, about 71% of the equity premium — [NBER w31923](https://www.nber.org/system/files/working_papers/w31923/w31923.pdf) (search summary only, not read)

### Inferences
- My arithmetic, not a source claim: 10.6 bp mean on roughly 36-44 days a year is about 4% a year of excess return; with about 1% daily vol over those days that is an annual-stream Sharpe nearer 0.6-0.7, not 1.6. The 1.6 comes from sqrt(252) scaling of a daily ratio that only applies on the event days.
- Excluded families (pre-FOMC drift, turn-of-month) overlap conceptually with this one.

### Gaps
- Bond-side announcement-day returns (SW JFQA 2013) were not retrieved. Post-2013 out-of-sample Sharpe was not found.

## Q3. Do alternative-risk-premia (ARP) index methodologies, cross-asset carry/value, or defensive/quality ETF timing offer a replicable >= 1.5 net Sharpe?

### Takeaway
Nothing found that is both fully specified and ETF-testable. Bank ARP rulebooks were not found in free form, the published ARP Sharpe evidence is back-test or short live record, and cross-asset carry/value papers use futures and forwards.

### Cited Findings
- No ARP index rulebook with signal formulas was found; results were press releases and fact sheets (Wilshire Systematic Cross Premia, Bloomberg/GSAM ARP indices, STOXX) — [Wilshire release](https://www.businesswire.com/news/home/20210812005714/en/Wilshire-Announces-Launch-of-Systematic-Cross-Premia-Index-Powered-by-Wilshire), [Bloomberg/GSAM](https://www.theasset.com/article/41674/bloomberg-gsam-launch-alternative-risk-premia-indices)
- Graham Capital defines momentum as trailing 12-month return divided by 12-month daily return stdev, with value and carry on futures/forwards across commodities, equities, bonds, FX — [Graham Capital note](https://www.grahamcapital.com/wp-content/uploads/2023/07/Directional-Cross-Sectional-Risk-Premia_Graham_October-2017.pdf) (search summary)
- Practitioner views: back-tests impressive, live record short; correlation of ARP funds with US equities reported around 0.5-0.7 in one Quantica-style estimate; about 30 uncorrelated strategies needed to reach Sharpe 2 as a theoretical estimate — [Cambridge Associates](https://www.cambridgeassociates.com/insight/alternative-risk-premia-funds-an-attractive-diversifier-sterling-edition/), [Hedge Fund Journal](https://thehedgefundjournal.com/la-francaise-investment-solutions/)
- Hartley-Schwarz month-end Treasury effect (see candidate 2 below): Sharpe about 1, not 1.5

### Inferences
- Multi-asset ARP baskets reach high Sharpe only through many-strategy diversification, leverage and futures, which the brief excludes. No ETF-only version with published net Sharpe >= 1.5 was found.

### Gaps
- Not searched in this round: defensive/quality factor ETF timing rule sets (QMJ, low-vol timing) and country-ETF carry/value. From general knowledge (unsourced here) their published Sharpe ratios are well below 1.5. Treat as unverified.

## Candidate list (JSON)

Candidate 1 (does not clear the bar; included for completeness):

```json
{
  "id": "LYZ2013_AUCTION_2Y",
  "name": "Treasury 2-year auction cycle hedge trade (Lou, Yan, Zhang)",
  "source_url": "https://ifr.hkust.edu.hk/uploads/upload/files/20250212/f5cba4b7e2aa3ada8477ad2fc38fab02.pdf",
  "pages": "2, 14-16, Table V p.38",
  "universe": "On-the-run 2y note, 10y note and 6m bill (CRSP). No exact free equivalent. Closest Yahoo proxies SHY, IEF, BIL are a different strategy.",
  "data": "Auction dates: TreasuryDirect auction archive (2y notes monthly since 1980s). Prices: none free for on-the-run notes. ETF proxies: SHY from 2002-07-26, IEF from 2002-07-26, BIL from 2007-05-30.",
  "signal": "Short 2y, long duration-matched 6m bill (about 80%) and 10y (about 20%) from t trading days before each 2y auction to auction day; reverse from auction day to t days after. Published t=10 (best net).",
  "portfolio": "Single long-short spread, duration matched",
  "rebalance": "Twice per month, around each 2y auction",
  "parameters": "t=10 days: VERIFIED p.38. Hedge weights 20/80: VERIFIED p.16 (approximate, from duration estimates). Costs 1.46 bp per round trip: VERIFIED p.16.",
  "source_sample": "1980-2008 gross; 1998-2008 net",
  "reported_performance": "Net Sharpe 0.84 (1998-2008, t=10); gross 1.44 (1998-2008) and 1.08 (1980-2008). Correlation to equities not reported.",
  "post_publication_evidence": "None found for the trade. Somogyi-Wallen-Xu 2025 report post-2010 auction price patterns reversed or weakened (UNVERIFIED for this exact trade).",
  "known_weaknesses": "Net Sharpe below 1.5 in its own sample; needs CRSP on-the-run notes and repo; ETF proxy changes the strategy; effect weakened after 2010; 116 monthly obs in the net sample."
}
```

Candidate 2 (best ETF-testable lead; Sharpe about 1, does not clear 1.5):

```json
{
  "id": "HS2019_EOM_TSY",
  "name": "Predictable end-of-month Treasury returns (Hartley & Schwarz)",
  "source_url": "https://rodneywhitecenter.wharton.upenn.edu/wp-content/uploads/2019/12/17-19.Schwarz.pdf",
  "pages": "6-7 (strategy, Sharpe), 14-15 (on-the-run and futures), Tables 1, 3, 4, 7 pp.25-31",
  "universe": "Paper uses smoothed zero-coupon curve (Gurkaynak-Sack-Wright) at 2y, 5y, 10y, plus on-the-run 2/5/10/30y and futures. ETF proxies, not the published instruments: SHY, IEF, TLT.",
  "data": "Yahoo adjusted close: SHY and IEF from 2002-07-26, TLT from 2002-07-30. Financing proxy FRED DTB3 or SOFR (SOFR only from 2018-04); paper used overnight GC repo. GSW curve itself is free on the Fed site (feds200628), which would allow an exact-signal test back to 1990.",
  "signal": "Hold long the Treasury for the last t trading days of each calendar month, buying at the close t days before the last trading day and selling at the last day's close. Excess return = log price change minus GC repo accrual (eq. 1, p.4).",
  "portfolio": "Long-only duration exposure, financed at repo; flat otherwise",
  "rebalance": "Monthly, 12 short windows a year",
  "parameters": "t between 1 and 5 days: VERIFIED. Best Sharpe at t=2-3 (p.7). 2y Sharpe 0.97/1.11/1.10 at t=1/2/3; 5y 1.04/1.07/1.04; 10y 0.85/0.87/0.88 (Table 3 p.26). Exact t not pre-registered by authors: choose t=2 or 3 before looking, UNVERIFIED as 'the' published choice.",
  "source_sample": "1990-2018, 12 obs per year",
  "reported_performance": "Annualized Sharpe about 1 after transaction costs (abstract, p.2 intro); table Sharpe values are on excess returns, bid-ask 2-3 bp said to 'barely make a dent' at 10y (p.7). Correlation to equities: not reported (gap). On-the-run Sharpe for last day only about 1.0 (Table 7).",
  "post_publication_evidence": "None independent found. Authors' own 5-year windows 2015-2019 show smaller but still positive significant means (Table 4 p.27); Bai-Perron tests find no break (p.8). Paper itself flags regulatory changes could weaken it.",
  "known_weaknesses": "Sharpe about 1 not 1.5; sample ends 2018; ETF distributions and different duration change the signal; may share a month-end/turn-of-month mechanism with excluded turn-of-month tests; GC repo financing unavailable free pre-2018; only 12 short windows a year so low statistical power per subperiod; the effect is one-day dominated (last day 2y 0.03%, 10y 0.14% per Table 5) so ETF close-to-close tests are noisy."
}
```

Candidate 3 (does not clear the bar; high equity correlation):

```json
{
  "id": "SW2013_ANNDAY_EQUITY",
  "name": "Long equities only on scheduled macro announcement days (Savor & Wilson)",
  "source_url": "https://faculty.wharton.upenn.edu/wp-content/uploads/2013/06/draft20130612pp-full.pdf",
  "pages": "6 (dates), 52 (Figure 10), 62 (Table 4), 64 (Table 5)",
  "universe": "SPY (from 1993-01-29) or ^GSPC (from 1950); paper uses CRSP value-weighted index",
  "data": "Yahoo SPY/^GSPC daily; BLS release calendars (CPI/PPI, employment) and Federal Reserve FOMC calendar, all free",
  "signal": "Be long the index on days when CPI (before Feb 1972) or PPI (after), the Employment Situation, or a scheduled FOMC decision is released; flat otherwise. Close-to-close on the release date as the paper's daily returns.",
  "portfolio": "Long-only equity on about 11% of days",
  "rebalance": "Event calendar",
  "parameters": "Announcement set: VERIFIED p.6. FOMC dates only from 1978 and scheduled only: VERIFIED p.6. Timing convention (close-to-close on release date vs prior close) UNVERIFIED for 8:30 releases.",
  "source_sample": "1964-2011 (earlier version 1958-2009)",
  "reported_performance": "Mean excess 10.6 bp on announcement days vs 1.0 bp otherwise (Table 4). Annualized Sharpe on announcement days about 1.6 read from Figure 10 (not printed). That is a per-day ratio scaled by sqrt(252), not the Sharpe of the tradable annual stream, which my arithmetic puts nearer 0.6-0.7. Correlation to equities: not reported, but the position is the equity index.",
  "post_publication_evidence": "Contested: Management Science paper finds a small premium once monetary surprises and small-sample effects are removed; AEA 2022 paper argues selection of announcement sets. NBER 2025 survey says 10.68 bp vs 0.93 bp on 1961-2023 (search summary only).",
  "known_weaknesses": "High S&P correlation by construction; tradable Sharpe far below 1.5; announcement sets were chosen ex post; overlap with excluded pre-FOMC drift and turn-of-month; costs and timing (8:30 release vs close) not modelled."
}
```

I found no further candidate that meets the bar and is fully specified on free data, so I am not listing candidates 4 and 5.

## Overall assessment

No candidate plausibly clears a long-sample net Sharpe of 1.5 with low S&P correlation on free ETF or index data. The Treasury auction-cycle trade has a published net Sharpe of 0.84 on 1998-2008 only and cannot be run on ETFs as published. The end-of-month Treasury effect (Hartley-Schwarz) is the only fully specified, free-data-testable lead, but its own reported Sharpe is about 1 and it comes from one in-sample paper that ends in 2018 with no independent out-of-sample replication found. Savor-Wilson announcement-day equity returns are equity beta, and the quoted Sharpe near 1.6 is a per-event-day figure that does not translate into an annual-stream Sharpe near that level. ARP index methodologies are not available as free rulebooks, and the published evidence for multi-asset premia relies on diversification across many strategies, futures and leverage. My judgement is that the honest ceiling for these ideas on ETF data is roughly 0.5-1.0 net Sharpe, and the deflated-Sharpe gate of 1.5-1.9 is unlikely to be met. If the team still wants a Treasury-based test, the end-of-month effect is the cleanest one to pre-register, but only as a low-expectation, diversification-oriented check (possibly using the free GSW yield curve for an exact signal test) and not as a candidate to pass the gate.
