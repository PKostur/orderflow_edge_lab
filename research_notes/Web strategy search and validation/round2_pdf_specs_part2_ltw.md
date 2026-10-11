# Round 2 PDF specs, part 2: Liu-Tsyvinski-Wu (this file completes section 3 of round2_pdf_specs.md, whose placeholder says "see below")

Source read in full: webfetch-1791735374583-fm448j.pdf = NBER WP 25882, "Common Risk Factors in Cryptocurrency", May 2019 working-paper version. Page numbers are the printed page numbers (PDF page = printed + 2 for the main text; appendix tables A.x on printed 41-46). VERIFIED = seen on the page cited. UNVERIFIED = not seen or inferred. The JF 2022 published version was NOT read.

## 3. Liu-Tsyvinski-Wu momentum

### Takeaway
Weekly cross-sectional momentum: each week, sort coins into value-weighted quintiles on trailing k-week return (k = 1,2,3,4 significant; 8,16,50,100 not), hold one week, long Q5 short Q1. Reported H-L 2.7%/3.3%/4.1%/2.5% per week for 1/2/3/4-week lookbacks (2014-2018, coins with mcap >= $1M). The CMOM factor used by later work (including CTREND) is the 3-week version with a 30/40/30 tercile split. No trading costs and no short-borrow modelling. The effect is concentrated in larger coins (4.2%/week above median size, 0.6% not significant below), and shorting Bitcoin instead of the loser quintile removes significance for 1-, 2- and 4-week momentum.

### Spec (JSON)
```json
{
  "id": "LTW_CRYPTO_MOMENTUM",
  "name": "Cross-sectional weekly crypto momentum (r_{k,0}, k=1..4 weeks) and CMOM factor (3-week, terciles)",
  "source": "Liu, Tsyvinski, Wu, NBER WP 25882 (May 2019), 'Common Risk Factors in Cryptocurrency'",
  "pages": "printed pp.4 (data), 9 (Table 2 definitions), 10-11 (momentum, Table 4), 14 (Table 7), 16 (CMOM construction), 17 (Table 8), 26 (Table 11), 29 (Table 12), 30 (Table 13), 41 (Tables A.1, A.2), 46 (Table A.5)",
  "universe_filter": {
    "min_market_cap_usd": "1,000,000 [VERIFIED p.4]",
    "required_fields": "price, volume and market cap all present [VERIFIED p.4]",
    "outliers": "winsorize all NON-return variables at 1st/99th percentile each week [VERIFIED p.4]; returns themselves are not winsorized here (contrast CTREND, which truncates returns at 0.5/99.5)",
    "survivorship": "Coinmarketcap lists active and defunct coins [VERIFIED p.4]",
    "n_coins": "1,707 coins in total; 109 in 2014 rising to 1,583 in 2018 [VERIFIED p.1, p.5-6]",
    "min_volume_or_price": "none seen [VERIFIED by absence in Section 2]"
  },
  "data": {
    "source": "Coinmarketcap.com daily open/close/high/low, volume, market cap; price is volume-weighted across >200 exchanges [VERIFIED p.4]",
    "sample": "start of 2014 to end of 2018 (volume data available from last week of 2013) [VERIFIED p.1, p.4]",
    "week_definition": "each year divided into 52 weeks: first week = first seven days of the year; first 51 weeks have 7 days; last week has 8 days (9 days in 2016) [VERIFIED p.4 incl. fn2]. Weekly returns from daily CLOSE prices [VERIFIED p.4]. Weeks are anchored to Jan 1, not to a weekday.",
    "risk_free": "one-month Treasury bill rate [VERIFIED p.5]; CMKT = value-weighted return of all available coins minus risk-free [VERIFIED p.5]"
  },
  "signal": {
    "momentum_k": "r_{k,0} = k-week momentum (one-, two-, three-, four-, eight-, sixteen-, fifty-, hundred-week) [VERIFIED p.9 Table 2]; the explicit formula (cumulative return over the k weeks ending with the formation week) is UNVERIFIED but implied by the r_{k,0} notation",
    "timing": "sort at end of formation week; portfolio return tracked over the following week [VERIFIED p.2, p.8]",
    "significant_lookbacks": "1,2,3,4 weeks significant; 8,16,50,100 weeks not (16-week H-L 0.4%/week, insignificant) [VERIFIED p.10, p.14-15]"
  },
  "model": "none (single-characteristic sort)",
  "portfolio": {
    "baseline_strategy": "each week sort coins into quintiles on the characteristic; value-weighted; long quintile 5 (high past return), short quintile 1 [VERIFIED p.2, p.10]",
    "weights": "value-weighted (mean returns are time-series averages of weekly value-weighted portfolio excess returns) [VERIFIED p.11 Table 4 caption]",
    "CMOM_factor": "each week split coins into bottom 30% / middle 40% / top 30% on THREE-week momentum; value-weighted portfolios; CMOM = top minus bottom; 3-week chosen 'because it generates the largest long-short spread' [VERIFIED p.16 and fn7]. This lookback was selected in-sample.",
    "CSMB_factor": "same 30/40/30 split on market cap; CSMB = small minus big [VERIFIED p.16]"
  },
  "rebalance": "weekly [VERIFIED p.10-12]",
  "parameters": {"lookback_weeks_main": 3, "lookbacks_tested": [1,2,3,4,8,16,50,100], "quintiles": 5, "terciles_for_factor": "30/40/30", "holding_weeks": 1, "min_mcap_usd": 1000000},
  "source_sample": "2014-2018 weekly (about 260 weeks); full-sample, no out-of-sample split; 3-week lookback picked after the fact",
  "reported_performance": {
    "quintile_5_minus_1_mean_weekly_excess": "r1,0 2.7% (t=1.994); r2,0 3.3% (t=2.442); r3,0 4.1% (t=2.742); r4,0 2.5% (t=2.002) [VERIFIED p.10-11 Table 4]",
    "r3_0_quintile_means_weekly": "Q1 0.002, Q2 0.001, Q3 0.016, Q4 0.020 (t=2.091), Q5 0.043 (t=2.956) [VERIFIED p.11]",
    "insignificant_lookbacks": "r8,0 0.6%, r16,0 0.4%, r50,0 -0.8%, r100,0 -1.1% (all |t| < 1) [VERIFIED p.14 Table 7]",
    "CMOM_factor_stats": "mean 0.038/week, median 0.034, SD 0.184, skew 0.791, kurtosis 7.868 [VERIFIED p.41 Table A.1]; implied weekly Sharpe about 0.21, about 1.5 annualized (my arithmetic, not stated by the paper). CSMB mean 0.020, SD 0.143; CMKT mean 0.013, SD 0.117; corr(CMOM,CMKT) -0.001, corr(CMOM,CSMB) -0.033 [VERIFIED p.41]",
    "CAPM_alpha_r3_0": "H-L alpha 0.040 (t=2.652), market beta 0.101 (t=0.78) [VERIFIED p.17 Table 8]",
    "size_dependence": "double sort: below-median-size momentum H-L 0.006 (t=0.30), insignificant; above-median-size H-L 0.042 (t=2.57) [VERIFIED p.41 Table A.2; also p.3, p.28]",
    "bitcoin_short_variant": "long Q5, short Bitcoin: r1,0 0.009 (t=0.69), r2,0 0.018 (t=1.50), r3,0 0.030 (t=2.25), r4,0 0.014 (t=1.20); only the 3-week lookback is significant [VERIFIED p.29 Table 12]",
    "fama_macbeth": "all coins >$1M: no momentum lookback significant (r1 -0.002, r2 0.000, r3 -0.000, r4 -0.001); coins >$10M mcap: r1 0.005 (t=1.67), r2 0.007 (t=2.10), r3 0.007 (t=1.98), r4 0.003 (t=0.69) [VERIFIED p.30 Table 13]; paper attributes the discrepancy to FM weighting observations equally [VERIFIED p.28]",
    "tercile_version": "Table A.5 tercile H-L mean: r1 0.041 (t=3.72), r2 0.029 (t=2.70), r3 0.031 (t=2.84), r4 0.027 (t=2.52) [VERIFIED p.46]",
    "stock_factor_models": "Fama-French 3/Carhart/FF5 do not explain it: r3,0 FF3 alpha 4.2% (t=2.80) vs raw 4.1% [VERIFIED p.33-36]"
  },
  "cost_assumption": "None. The paper says its strategy 'does not take into account trading costs and the feasibility of short selling' [VERIFIED p.8] and tests only a Bitcoin-short variant as a feasibility check [VERIFIED p.27-30]. No turnover figures given.",
  "notes": [
    "Short selling most coins is infeasible; the Bitcoin-short variant keeps only 3-week momentum significant at 5%.",
    "Momentum is a large-coin effect in this sample; value-weighting makes the long leg large-cap dominated.",
    "This is the May 2019 working-paper version; the JF 2022 published version may differ (UNVERIFIED).",
    "Later evidence in the CTREND paper (JFQA 2025, sample Apr 2015-May 2022, read in full): CMOM median annualized Sharpe 0.89 under baseline design, 'rarely reaches' 2, Lo-test significant in only 49% of 55,296 designs, with a long left tail to Sharpe -4.47 (CTREND pp.3137-3139, VERIFIED). CTREND Figure 1 shows CMOM average return about 2%/week and Sharpe about 1.3 (read off a bar chart, approximate).",
    "LTW's 52-week calendar is year-anchored (7-day blocks from Jan 1, 8-9 days in the last week); CTREND does not state a week boundary; exact replication needs the same calendar."
  ]
}
```

## 4. Cross-paper caveats (inferences, not paper claims)

- CTREND and LTW use the same CoinMarketCap-style universe (>= $1M mcap, daily OHLCV, value-weighted weekly quintiles). Replication is exposed to the same data issues; CTREND itself flags wash-trading in volume data (p.3136) and finds that dropping volume indicators barely changes the median Sharpe (1.39 without vs 1.30 with, CS-C-ENet, Table 6 p.3137).
- Both crypto strategies are long-short with an unmodelled short leg in small, mostly unshortable coins. CTREND's top-100 variant (3.40% gross, 2.45% net at 30/40 bp, weekly turnover about 68%) is the more tradeable reading but still assumes shortable coins and no borrow cost.
- The FOMC even-week rule has no fitted parameters other than the choice of weeks and the 1994-2013 window (selected after observing the pattern); the authors call it a "novel finding" of that same sample.
- Not read: CTREND online supplement (indicator formulas, Tables B.1-B.10), the published JF versions of LTW and the FOMC-cycle paper.
