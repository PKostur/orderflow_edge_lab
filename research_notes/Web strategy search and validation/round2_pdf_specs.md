# Round 2 PDF specs: CTREND, FOMC cycle, (Liu-Tsyvinski-Wu section appended below)

Method note: PDFs were read in full via the Read tool (no `pages` param available; pdftoppm missing). Page numbers: CTREND = journal pagination 3116-3153 (PDF page = journal page - 3115). FOMC cycle = draft pagination (printed number; PDF page = printed + 1), Oct 2, 2015 NBER draft, not the published JF version. Lucca-Moench = printed pagination. VERIFIED = seen in the PDF text on the page cited. UNVERIFIED = not seen or inferred.

Files read (tool-results dir):
- webfetch-1791500794323-y2xu11.pdf = TradingAgents (arXiv 2412.20138), irrelevant to this task (LLM multi-agent; 3-month Jan-Mar 2024 backtest on AAPL/GOOGL/AMZN; the paper's own footnote on p.12 says its Sharpe 8.21 exceeds the plausible range).
- webfetch-1791730842325-0k2fhv.pdf = Lucca-Moench "Pre-FOMC Announcement Drift", NY Fed Staff Report 512 (companion to FOMC cycle).
- webfetch-1791735311426-onppgi.pdf = Cieslak-Morse-Vissing-Jorgensen "Stock Returns over the FOMC Cycle" (draft Oct 2, 2015).
- webfetch-1791734915744-2htigi.pdf = CTREND, JFQA 60(7), Nov 2025, pp.3116-3153 (main paper only).
- webfetch-1791735374583-fm448j.pdf = NBER w25882 (see LTW section).
- The CTREND online Supplementary Material (Appendix A indicator formulas, Tables B.1-B.10) was NOT retrieved (Cambridge page lists S0022109024000747sup001.pdf, 515 KB). Anything that depends on Appendix A is UNVERIFIED.

---------------------------------------------------------------------------------------------

## 1. CTREND (Fieberg, Liedtke, Poddig, Walker, Zaremba, JFQA 2025)

### Takeaway
CTREND is a weekly cross-sectional crypto signal: 28 technical indicators (ranked to [-0.5,0.5]) -> univariate Fama-MacBeth forecasts (value-weighted WLS, 52-week rolling) -> elastic-net forecast selection (alpha 0.5, lambda by corrected AIC, keep theta>0) -> equal-weighted mean of surviving forecasts -> value-weighted quintile long-short, weekly rebalance. Reported H-L 3.87%/week gross, Sharpe 1.94 (Apr 2015-May 2022); net 2.90%/week at 30/40 bp; long-short in 100 largest coins 3.40% gross, 2.45% net. Cost model charges only trading cost; no borrow/funding cost for the short leg appears anywhere in the main text.

### Spec (JSON; all values tagged)
```json
{
  "id": "CTREND_JFQA2025",
  "name": "CTREND cross-sectional crypto trend factor (CS-C-ENet)",
  "source": "Fieberg, Liedtke, Poddig, Walker, Zaremba, JFQA 60(7), Nov 2025, pp.3116-3153, doi 10.1017/S0022109024000747",
  "pages": "journal pp.3121-3129 (method), 3130 (Table 3), 3136-3139 (nonstandard errors), 3145-3148 (large-cap, costs)",
  "universe_filter": {
    "min_market_cap_usd": "1 million [VERIFIED p.3122]",
    "drop_if_mcap_exceeds_bitcoin": "yes, removes 10 daily obs [VERIFIED p.3122 incl. fn1]",
    "validity": "need non-missing close price, volume, market cap [VERIFIED p.3121]",
    "return_outliers": "truncate (drop) returns below 0.5th and above 99.5th percentile [VERIFIED p.3122]",
    "stablecoins": "excluded in baseline (bold 'Exclude' in Table 6) [VERIFIED p.3137]",
    "price_filter": "baseline >= $0 i.e. none; price >= $1 lowers median Sharpe 1.64 -> 1.13 [VERIFIED p.3137, 3139]",
    "min_volume": "none seen [UNVERIFIED absence beyond main text]"
  },
  "data": {
    "source": "Coinmarketcap.com daily open/high/low/close, volume, market cap [VERIFIED p.3121]",
    "sample": "Apr 2015 - May 2022, 423 weekly obs; 3,244 unique coins (text) / 3,245 (Table 1), under 100 coins in 2015 to over 2,000 in 2021 [VERIFIED p.3122]",
    "frequency": "daily data -> weekly signals/returns [VERIFIED p.3123, p.3129]",
    "week_boundary_day": "UNVERIFIED (not stated in main text)"
  },
  "signal": {
    "count": "28 indicators [VERIFIED p.3122]",
    "momentum_oscillators_5": {
      "rsi": "ratio of avg gains to avg losses over preceding 14 days [VERIFIED p.3123]; smoothing method UNVERIFIED (Appendix A)",
      "stochK": "price vs range of prices over 14-day period [VERIFIED p.3123]",
      "stochD": "3-day moving average of stochK [VERIFIED p.3123]",
      "stochRSI": "(rsi - lowest rsi over 14 days) scaled by range of rsi values [VERIFIED p.3123]",
      "cci": "compares average deviation of current price to a moving average [VERIFIED p.3123]; window UNVERIFIED"
    },
    "moving_averages_9": {
      "sma_3d,5d,10d,20d,50d,100d,200d": "7 simple MAs of daily close, each scaled by the closing price at end of each week [VERIFIED p.3123]; 400-1000d omitted as series too short [VERIFIED fn2 p.3123]",
      "macd": "(slow 26-day EMA minus fast 12-day EMA) of daily close, expressed as a percentage of the fast EMA (= PPO) [VERIFIED p.3123, fn3]; sign convention as written is slow minus fast",
      "macd_diff_signal": "macd minus 9-day EMA of macd [VERIFIED p.3123]"
    },
    "volume_10": {
      "volsma_3d,5d,10d,20d,50d,100d,200d": "7 SMAs of dollar volume, each normalized by current trading volume [VERIFIED p.3123]",
      "volmacd": "difference between two EMAs of dollar volume as percent of fast EMA (PVO) [VERIFIED p.3123, fn4]; EMA lengths UNVERIFIED (likely 12/26 by analogy)",
      "volmacd_diff_signal": "volmacd minus its signal line [VERIFIED p.3123]; signal length UNVERIFIED (9 by analogy)",
      "chaikin": "Chaikin money flow; window UNVERIFIED (Appendix A)"
    },
    "volatility_4": {
      "boll_mid": "20-day MA of close, scaled by current close [VERIFIED p.3124]",
      "boll_high/boll_low": "mid +/- 2 standard deviations of previous closes, scaled by current close [VERIFIED p.3124]",
      "boll_width": "(upper - lower)/middle [VERIFIED p.3124]"
    },
    "preprocessing": "each indicator transformed to cross-sectional rank mapped to [-0.5, 0.5] before estimation [VERIFIED p.3129]",
    "timing_of_inputs": "indicators lagged one period: z_{i,j,t-1} predicts r_{i,t}; baseline implementation lag = 0 (portfolio formed right after signal); a 1-day extra lag cuts median CS-C-ENet Sharpe 1.46 -> 1.24 [VERIFIED p.3128 eq.3, p.3136-3137 Table 6]",
    "variable_importance": "boll_mid, cci, macd score highest [VERIFIED p.3131]"
  },
  "model": {
    "name": "CS-C-ENet (Han, He, Rapach, Zhou 2024; Dong, Li, Rapach, Zhou 2022) [VERIFIED p.3127]",
    "step1_univariate_FM": "For each indicator j, cross-sectional regression r_{i,t} = a_{j,t} + b_{j,t} z_{i,j,t-1} + u each week; coefficients averaged over M periods (rolling) -> forecast r^j_{i,t+1} = abar_j + bbar_j z_{i,j,t} (eqs 4,5,7,8) [VERIFIED p.3127-3128]. Coefficients are smoothed over time (unlike Han et al. 2024) [VERIFIED p.3128]",
    "estimation_window": "fixed rolling window of 52 weeks; used to predict next week [VERIFIED p.3129]; M tied to the window (explicit M value UNVERIFIED but Table 6 'In-sample observations 52' baseline p.3137)",
    "weights": "all regressions minimize value-weighted (market-cap) sum of squared residuals [VERIFIED p.3129]",
    "step2_selection": "pooled regression r_{i,t} = xi + sum_j theta_j r^j_{i,t} + eta (eq.10) with elastic net; L1/L2 mixing parameter 0.5; regularization strength lambda chosen by corrected AIC [VERIFIED p.3128 fn7]; cross-sectional mean subtracted from returns only for the pooled variants (fn14 p.3136)",
    "step3_combine": "CTREND_{i,t+1} = simple (equal-weighted) average of the univariate forecasts with theta_j > 0 (eq.11); theta-weighting is an alternative (median Sharpe 1.30 vs 1.37) [VERIFIED p.3128-3129, p.3137]",
    "target": "next-week excess return of coin i (returns in excess of risk-free; risk-free construction UNVERIFIED) [VERIFIED p.3127 text 'excess return']",
    "alternatives_tested": "FM (multivariate), CFM, POLS, CPOLS, C-ENet; plain multivariate FM is noticeably worse/overfits [VERIFIED p.3136, 3139]; validation-sample variant (last 12 weeks held out for selection) lowers median Sharpe 1.47 -> 1.19 [VERIFIED p.3136-3140]"
  },
  "portfolio": {
    "sort": "rank on CTREND at start of each week into 5 quintiles; value-weighted; long top quintile, short bottom [VERIFIED p.3129]",
    "weights": "value-weighted by market cap in baseline; equal-weighted gives much higher Sharpe (median 1.47 vs 1.17 for CS-C-ENet) driven by small coins [VERIFIED p.3137]"
  },
  "rebalance": "weekly [VERIFIED p.3129]; holding 2 weeks: avg weekly return falls ~1.5 pts to 2.34%; significant at 5% up to 4-week holding [VERIFIED p.3148]",
  "parameters": {
    "n_indicators": 28,
    "window_weeks": 52,
    "enet_alpha": 0.5,
    "enet_lambda": "corrected AIC",
    "quintiles": 5,
    "truncation": "0.5%/99.5% of returns",
    "min_mcap_usd": 1000000
  },
  "source_sample": "Apr 2015 - May 2022 (423 weeks); out-of-sample in the sense of rolling re-estimation but every design choice (indicator set, 52w, alpha 0.5) is fixed ex ante from prior literature (p.3123: 'common estimation horizons ... to avoid data-snooping') [VERIFIED]; no post-May-2022 test seen",
  "reported_performance": {
    "gross_HL": "3.87% per week, t=5.19, weekly std 14.34%, annualized Sharpe 1.94 [VERIFIED p.3130 Table 3]",
    "quintiles_mean_weekly_pct": "L 0.12, Q2 0.93, Q3 1.12, Q4 2.72, H 3.98 [VERIFIED p.3130]",
    "alpha_CCAPM": "3.80% (t=5.03); alpha_LTW3: 2.62% (t=4.22); CMOM beta 0.79 (t=14.88) [VERIFIED p.3130]",
    "subperiods_HL": "first half (Apr 2015-early Nov 2018) 4.47% t=3.50; second half 3.26% t=4.25; low vol 5.46%, high vol 2.27%; bull 4.49%, bear 3.25% [VERIFIED p.3135 Table 5]",
    "robustness": "55,296 designs; median CS-C-ENet Sharpe 1.34, range -1.45 to 10.92; Lo-test significant in 79% of designs [VERIFIED p.3138-3139]",
    "net_of_cost_full_universe": "TO 68.46%/week; net HL 2.90% (t=3.89) at 30bp long/40bp short; 2.62% (t=3.53) at 40/50; 2.35% (t=3.16) at 50/60; breakeven TC 1.41%; BETC(5% significance) 0.88% [VERIFIED p.3147 Table 9 panel A]",
    "large_cap_100": "Top-100 coins by weekly mcap: gross HL 3.40% (t=4.48); net 2.45% (t=3.22) / 2.17% (t=2.86) / 1.90% (t=2.50); TO 68.21%; BETC 1.25%; BETC5% 0.70% [VERIFIED p.3147 Table 9 panel B]. By mcap: Top100 HL 3.39 (t=4.49), alpha_LTW 2.19; largest 50%: 3.84; 30%: 3.46; 20%: 2.74; 10%: 2.51 (t=3.01) [VERIFIED p.3145 Table 8A]. By liquidity (Amihud): Top100 3.30; 50%: 4.36; 10%: 2.20 [VERIFIED p.3145 Table 8B]",
    "price_filter_effect": "price >= $1 lowers median CS-C-ENet Sharpe from 1.64 (no filter) to 1.13 [VERIFIED p.3139]"
  },
  "cost_assumption": "30 bp on long-leg turnover and 40 bp on short-leg turnover (Bianchi et al. 2022), plus stress at +10bp each; turnover per Gu-Kelly-Xiu formula (eq.14) [VERIFIED p.3146-3147]. No short-borrow/funding/slippage-in-size modelling seen. Authors say 30/40 bp 'may be conservative' for larger coins [VERIFIED p.3146].",
  "notes": [
    "The shorted quintile is crypto coins, most of which cannot be shorted at 40 bp in practice; the paper is a factor-return study, not an execution study (inference).",
    "Value-weighted baseline is dominated by a few coins; Sharpe 1.94 is the full-sample, 2015-2022 figure, with a visible decline over time in raw returns (first half 4.47% -> second 3.26%) [VERIFIED p.3135].",
    "Strategy correlates strongly with LTW momentum factor (beta 0.79) [VERIFIED p.3130].",
    "UNVERIFIED items needed to code exactly: week boundary day/time, exact M for FM smoothing, risk-free used, Appendix A formulas (rsi smoothing, cci/chaikin windows, stoch definition), how coins with fewer than 52 weeks of history are handled, how ties/lists with <5 coins are handled, whether the signal is computed with end-of-week close of day t and held t+1..t+7."
  ]
}
```

---------------------------------------------------------------------------------------------

## 2. FOMC cycle (Cieslak, Morse, Vissing-Jorgensen, "Stock Returns over the FOMC Cycle", draft Oct 2, 2015)

### Takeaway
Define cycle time in trading days relative to each scheduled FOMC meeting day (day 0, second day for two-day meetings; weekends omitted, holidays kept as zero-return days). "Even weeks" are weeks 0 (days -1..3), 2 (9..13), 4 (19..23), 6 (29..33). Holding the US equity market only in even weeks and staying out in odd weeks, 1994-2013, gave excess return 11.58%/yr, st.dev 13.92%, Sharpe 0.83 versus buy-and-hold 8.47%/19.99%/0.42 (Table 3). The authors do not model transaction costs (they assert an ETF would make it very cheap). Beyond week 0 (also documented by Lucca-Moench) the biweekly effect is a 20-year, in-sample discovery with a weak individual significance (week 2 t=1.70).

### Spec (JSON)
```json
{
  "id": "FOMC_CYCLE_EVEN_WEEKS",
  "name": "Hold US equities in even weeks of FOMC cycle time (weeks 0,2,4,6), cash in odd weeks",
  "source": "Cieslak, Morse, Vissing-Jorgensen, 'Stock Returns over the FOMC Cycle', first draft Apr 23 2014, current draft Oct 2 2015 (NYU Stern hosted PDF); published later in JF 2019 (published version NOT read)",
  "pages": "draft printed pp.1, 4-6, 9-10, 56, 58",
  "universe_filter": "US stock market portfolio (Ken French market return) [VERIFIED p.5 fn3: 'stock returns and T-bill returns from Ken French's website']",
  "data": {
    "stock_return": "US market excess return = stock return minus 30-day T-bill return, daily; Ken French library [VERIFIED p.4-5 incl. fn3]",
    "meeting_dates": "eight scheduled FOMC meetings per year; calendar announced well in advance (e.g., 2013 schedule announced May 2012) [VERIFIED p.13, p.9]",
    "sample": "1994-2013, '20 years', 160 scheduled meetings; regressions N=5214 days [VERIFIED p.5, Table 1 p.56]. Pre-1994 check from 1982-09-27 (Figure 2B) [VERIFIED p.6]",
    "week7_days": "3 days over the sample fall in 'week 7' and are dropped [VERIFIED p.5 fn5]"
  },
  "signal": {
    "day_zero": "the day of the scheduled FOMC meeting; for two-day meetings, the second day (announcement day) [VERIFIED p.4]",
    "cycle_start": "FOMC cycle starts the day before a scheduled FOMC announcement day (day -1) and resets at each of the eight meetings [VERIFIED p.1]",
    "day_counting": "trading days, weekends omitted, holidays set to zero return: 10 days on the axis = 2 calendar weeks, 20 = 4 weeks [VERIFIED p.4]",
    "week_definitions": "Week -1: days -6 to -2. Week 0: days -1 to 3. Week 1: days 4 to 8. Week 2: days 9 to 13. Week 3: days 14 to 18. Week 4: days 19 to 23. Week 5: days 24 to 28. Week 6: days 29 to 33 [VERIFIED Table 1 note p.56; also p.5]",
    "even_weeks": "0, 2, 4, 6; odd weeks: -1, 1, 3, 5 [VERIFIED p.5, p.9 'weeks -1, 1, 3, 5']",
    "unscheduled_meetings": "analysis is on scheduled meetings (cycle resets at the eight scheduled meetings) [VERIFIED p.1, p.13]; treatment of unscheduled meetings in day counting UNVERIFIED",
    "overlap_rule_between_cycles": "UNVERIFIED. Figure 1 note says if a day is day -6 or closer to the next meeting, that 5-day forward return is not used in the right part of the graph [VERIFIED p.5], implying days within 6 days of the next meeting carry the next cycle's negative label; exact assignment for cycles shorter than 34 trading days is not stated."
  },
  "model": "none (calendar rule)",
  "portfolio": {
    "strategy_B": "stay out of the stock market in odd weeks; hold the market in weeks 0,2,4,6 [VERIFIED p.9 'investor stays out of the stock market in the odd weeks']",
    "return_calc": "annual excess return = compounded stock returns over days invested minus compounded T-bill returns over those same days; reported means, st.devs, Sharpe from annualized excess returns [VERIFIED p.9]",
    "off_days": "cash / not invested (T-bill implicitly) [VERIFIED p.9]; exact off-day return convention UNVERIFIED"
  },
  "rebalance": "calendar-driven; enter day -1 close (day -1 included in week 0), exit before week 1 (day 4); repeat for weeks 2,4,6 [INFERRED from week definitions; entry at close vs open of day t UNVERIFIED]",
  "parameters": {"even_weeks": [0, 2, 4, 6], "week0_days": "-1..3", "week2_days": "9..13", "week4_days": "19..23", "week6_days": "29..33"},
  "source_sample": "1994-2013 (in-sample discovery; the pre-1994 sample 1982-09 to 1993 shows a biweekly pattern in Figure 2B but is graphical only; post-2013 out-of-sample not in this draft)",
  "reported_performance": {
    "avg_5day_excess_return_pct": "week 0 0.57 (days -1 to 3); week 2 0.30 (days 9-13); week 4 0.42 (days 19-23); week 6 0.61 (days 29-33); odd weeks: week -1 about zero, week 1 -0.17, week 3 -0.17, week 5 -0.12 [VERIFIED p.5]",
    "regression_daily_pct": "Table 1 col(1): week0 dummy 0.136 (t=2.75), weeks 2/4/6 dummy 0.0995 (t=2.65), constant -0.021 (t=-0.96), N=5214; col(2): wk2 0.081 (t=1.70), wk4 0.108 (t=2.00), wk6 0.178 (t=1.99) [VERIFIED p.56]. Text: 13.6 bp and 10 bp higher per day [VERIFIED p.6]",
    "Table_3_strategies_annual_pct": "A buy&hold: mean 8.47, sd 19.99, Sharpe 0.42. B even weeks: 11.58 / 13.92 / 0.83. B week0 only: 4.76 / 9.06 / 0.53. week2 only: 2.44 / 6.78 / 0.36. week4 only: 3.02 / 6.69 / 0.45. week6 only: 0.93 / 1.57 / 0.59. C odd weeks (-1,1,3,5): -2.67 / 15.04 / -0.18. D long even, short odd: 14.24 / 21.78 / 0.65 [VERIFIED p.58]",
    "subperiods": "1994-2000, 2001-2007, 2008-2013 each show four peaks (graphical, Figure 2A); 2001-2007 is visibly weaker/noisier [VERIFIED p.6 text, p.44 figure; magnitudes not tabulated]",
    "international": "MSCI EM +19 bp/day in week 0 (t=3.77), +18 bp (t=4.75) in weeks 2,4,6 vs odd weeks (t+1 timing) [VERIFIED p.7, p.57]",
    "bonds": "10y Treasury even-week effect not significant [VERIFIED p.10]",
    "controls": "robust to reserve-maintenance dummies, macro-release counts, day-of-month/week FE, earnings announcements, payment-flow days (Table 5) [VERIFIED p.14-15, p.59]; effect is concentrated in even-week days following a Board discount-rate meeting within prior 5 days (Table 7: interactions 0.186 t=3.27 wk0, 0.197 t=3.05 wk2, 0.158 t=2.15 wk4, 0.168 t=1.44 wk6) [VERIFIED p.22-23, p.61]"
  },
  "cost_assumption": "None modelled. Authors state it 'could be implemented with very low transactions costs using an existing ETF' [VERIFIED p.9, a claim not a test]. No slippage, taxes, or bid-ask modelling.",
  "notes": [
    "Annual Sharpe uses annual excess returns (20 annual observations), so the 0.83 vs 0.42 comparison has very wide uncertainty; no standard error is given for the Sharpe difference [VERIFIED p.58 table has no s.e.].",
    "Weeks 0 and 6 have few days/data points (Panel B p.5, Figure 1B: ~160 obs through day ~17, falling to ~15-20 by days 29-33), so week 6 is thin. The 11.58%/yr mostly comes from weeks 0, 2, 4.",
    "Week 0's return is earned before the 2pm announcement on day 0 (Lucca-Moench), the post-1994 pre-announcement drift; the same draft says week 0 return is 0.451 (t=4.38) for day -1 + day 0 to 2pm vs 0.116 (t=0.72) after [VERIFIED p.66 Table 10].",
    "Authors attribute the pattern to Fed informal communication/leaks (p.28-36); that mechanism is argued, not proven.",
    "The draft's explicit later sample (post-2013) is not covered; the strategy requires knowing future FOMC dates (published ahead).",
    "Cycle time for day t is days since last meeting; the odd/even bucket for a given calendar day is determined by the meeting calendar, not by the calendar week, so calendar must be encoded from the Fed's published dates (Lucca-Moench Table B.1 lists all scheduled dates and announcement times 1994-2011 [VERIFIED p.56 of that paper]; meetings marked 'e' (1994-02-04, 03-22, 05-17, 07-06, 08-16, 1996-03-26) are excluded from Lucca-Moench's sample)."
  ]
}
```

### Companion spec: Lucca-Moench pre-FOMC drift (verified from the other saved PDF)
```json
{
  "id": "PRE_FOMC_DRIFT_LM",
  "source": "Lucca & Moench, 'The Pre-FOMC Announcement Drift', FRBNY Staff Report 512, Sep 2011 rev Aug 2013",
  "signal": "buy S&P 500 at 2pm ET the day before a scheduled FOMC announcement, sell about 15 minutes before the announcement (about 2pm on announcement day), cash otherwise [VERIFIED p.8-9]",
  "sample": "Sep 1994 - Mar 2011, 131 scheduled meetings (excludes 1996-03-26 and meetings where announcement was not ~2:15pm; 3 announcement-time exclusions flagged 'e' in Table B.1) [VERIFIED p.5-7, p.56]",
  "reported_performance": "mean 24h excess return 49 bp (0.488%, t>4.5, Table 2), 3.89%/yr vs 0.88%/yr on all other days, annualized Sharpe 1.14 (sqrt(8) x per-meeting Sharpe) [VERIFIED p.8-9, p.37 Table 2]; 98 of 131 positive [VERIFIED p.9]; excluding top/bottom 1% mean still 45 bp [VERIFIED p.10]; 1980-2011 (daily close-to-close pre-1994) mean 36 bp, Sharpe 0.92 [VERIFIED p.11 Table 4]; pre-1980 returns essentially zero [VERIFIED p.11]",
  "cost_assumption": "none modelled in the paper [VERIFIED by absence]; requires intraday execution at 2pm ET; for daily-bar tests the close-to-2pm window Sharpe 1.43 and close(t-2)-to-2pm 0.54% / Sharpe about 0.98 [VERIFIED p.9]",
  "caveat": "post-2011 behaviour not in this paper; note announcement times moved (12:30-2:00pm since Apr 2011) [VERIFIED p.5]"
}
```

---------------------------------------------------------------------------------------------

## 3. Liu-Tsyvinski-Wu (see below; section appended after the NBER PDF was read)
