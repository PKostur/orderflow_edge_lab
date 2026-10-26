# Round 1: perpetual-futures-specific signals, 4h to 1d holding (Binance USDT-M)

Method note: full texts read via the Read tool (PDFs saved by WebFetch). Full texts actually read: (a) Pengfei Luo PhD thesis, Univ. of Edinburgh 2024/2025 (Chapters 3 and 4 are the perpetual-futures work; the Chapter 3 material corresponds to the SSRN/J. Futures Markets paper on perpetual futures returns); (b) Kim and Hansen, arXiv 2607.09426v2 (July 2026). SSRN pages returned HTTP 403, so abstracts for the other papers are from search snippets only and are marked as such. No backtests were run.

## Q1. Is the Binance archive metrics data available as described (earliest date, columns)?

### Takeaway
Earliest BTCUSDT metrics file is 2020-09-01 (verified by direct S3 listing). The CSV column names could NOT be verified: the zip is binary, WebFetch cannot unzip, and no bash/unzip tool was available to this agent. The column list below is from memory and must be checked locally with one file.

### Cited Findings
- S3 listing for prefix data/futures/um/daily/metrics/BTCUSDT/ shows the first keys `BTCUSDT-metrics-2020-09-01.zip` (+ .CHECKSUM), then 2020-09-02, 2020-09-03...; listing is IsTruncated=true with NextMarker `...BTCUSDT-metrics-2022-01-13.zip.CHECKSUM` (page is 1000 keys; later pages not read, so latest date not verified here) — [S3 listing](https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/futures/um/daily/metrics/BTCUSDT/)
- One file was downloaded read-only (BTCUSDT-metrics-2024-01-15.zip, 11.4KB); it is a zip containing `BTCUSDT-metrics-2024-01-15.csv`; contents not decoded — [file](https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2024-01-15.zip) (local copy: C:\Users\007pe\.claude\projects\C--Users-007pe-src-orderflow-edge-lab\52e86723-5fec-4dba-8734-e0df4dec673a\tool-results\webfetch-1791798091100-esuboe.bin; unzip it locally with `python -I` into a fresh directory)
- A third-party catalog describes this feed as 5-minute UM metrics: open interest, top-trader long/short ratios, taker buy/sell volume ratio — [CDD catalog](https://api.cryptodatadownload.com/static/catalog/CDD_Data_Catalog.html) (secondary source, no header verified)
- The binance-public-data GitHub README does not document the metrics files — [repo](https://github.com/binance/binance-public-data)

### Inferences
- UNVERIFIED (from memory): header is `create_time, symbol, sum_open_interest, sum_open_interest_value, count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio, count_long_short_ratio, sum_taker_long_short_vol_ratio`, rows every 5 minutes, create_time as a "YYYY-MM-DD HH:MM:SS" UTC string. Confirm with one file before coding. Check the first rows of each coin for gaps and for the start date of each non-BTC symbol.
- Treat the history before listing dates of each altcoin as absent; the OI/long-short fields are exchange-computed snapshots (long/short ratios are account-share ratios of "top traders" by margin, definition from vendor commentary, not primary).

### Gaps
- Exact columns, latest file date, per-symbol start dates, missing-day rate.

## Q2. Which published, fully specified strategies exist for 4h-1d horizons on perp-specific signals?

### Takeaway
Only a few. Best-specified are the Luo thesis Chapter 3 perpetual-futures sorts (basis; signed taker price-volume imbalance), Chapter 4 category momentum (daily), and Kim-Hansen order-imbalance forecasts (4-12h; economically too small). I found NO published, fully specified strategy using Binance OI change, long/short ratios, funding-rate change, or OI-drop liquidation reversals; those remain practitioner commentary. Searches for OI-return predictability returned only vendor/news pages and an OI misreporting paper.

### Cited Findings
- Search for papers testing OI change or top-trader long/short ratio as return predictors found none; vendor claims (e.g., ratio above 3 contrarian) have no methodology — [Sharpe.ai](https://www.sharpe.ai/futures/bitcoin/long-short-ratio), [Cointelegraph](https://cointelegraph.com/markets/bitcoin-open-interest-15b-analyst-warns-20-btc-price-dip)
- Liquidation-cascade preprint (seven cascades 2022-2025): no single price/leverage/order-flow metric warned before all seven; falling variance of taker buy/sell ratio preceded cascades with usable data in 6 events; shifts event to event — [CryptoSlate summary](https://cryptoslate.com/?p=551122), [arXiv 2608.03616 listing](https://ideas.repec.org/p/arx/papers/2608.03616.html) (abstract level only)
- Giagkiozis and Said: exchange-reported BTC perp open interest is inconsistently quoted across large venues, a data-quality warning for OI signals — [arXiv 2310.14973](https://arxiv.org/abs/2310.14973)
- Fayez Junior (SSRN 6701738), abstract via search snippet only: long-short cross-sectional portfolios on ten Binance USDT perps using OHLCV and funding signals found no exploitable alpha at the 8h horizon — [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6701738) (403, not read)
- He, Manela, Ross, von Wachter / arXiv 2212.06888: no-arbitrage bounds for perps; snippet says deviations are large and a simple strategy earns large Sharpe even at highest Binance cost tier. This is basis-arbitrage/carry (excluded class), not fetched in full — [arXiv](https://arxiv.org/abs/2212.06888v2)

### Inferences
- The funding-rate-change, OI-drop reversal and long/short-ratio families are open: any spec would be our own invention, so it cannot be labeled "published". Under the repo evidence-rate rule these would need pre-registration anyway.

### Gaps
- No full-text source for OI/LSR/funding-change strategies. Try practitioner repos or Binance Research reports in a later round.

## Q3. Candidate specifications (JSON, exact where the full text allows)

### Takeaway
Four candidates. C1 and C2 are best specified and are 8-hour-hold cross-sectional sorts across all Binance perps. C3 is daily but depends on CoinMarketCap category labels. C4 is the OI/order-imbalance-type signal but is too small to trade.

### Cited Findings

**Common caveat for C1/C2 (from the thesis data section, p.81, p.83):** universe is every Binance USDT perp listed at least one day with daily dollar volume above 1 million USD; data are Binance 1-hour data; sample 2020-01-01 to 2023-07-01; contract counts 3 (2019), 79 (2020), 126 (2021), 149 (2022), 190 (2023) cumulative; weekly mean of equal-weighted portfolio returns; t-stats Newey-West 4 lags. Source: [Luo thesis PDF, Edinburgh](https://era.ed.ac.uk/handle/1842/43608) (bitstream 1da6437c-a50f-4d48-add9-fdf5158c1e8b). Local copy: C:\Users\007pe\.claude\projects\C--Users-007pe-src-orderflow-edge-lab\52e86723-5fec-4dba-8734-e0df4dec673a\tool-results\webfetch-1791798151174-uv2oic.pdf

```json
{
  "id": "C1",
  "name": "Log-basis quintile sort, 8h holding (Holding strategy), perps",
  "source": "Pengfei Luo, 'Three Essays on Futures Expected Returns', PhD thesis, Univ. of Edinburgh, 2024, Chapter 3; paper version: Cao, Zhai and Luo (2024) 'Anatomy of cryptocurrency perpetual futures returns', J. Futures Markets (forthcoming per thesis reference list); SSRN 6365329 lists authors as Cao, Luo, Cheng, Dong (author list conflict, unresolved)",
  "pages": "thesis pp.60-61 (definitions), 81-85 (data, Table 19), 116-120 (Tables 35-36)",
  "asset_universe": "All Binance USDT-M perps with >=1 day listing and daily dollar volume >1M USD (about 79 to 190 contracts over 2020-2023)",
  "bar_interval": "1h bars sampled at the 8h funding settlement grid (00:00, 08:00, 16:00 UTC)",
  "signal_data": "UNVERIFIED mapping. Thesis uses Binance 1h perp prices F and spot prices S. Archive options: data/futures/um/daily/klines/{SYM}/1h/ (perp close) and data/spot/daily/klines/{SYM}/1h/ (spot close); premiumIndexKlines (data/futures/um/daily/premiumIndexKlines/{SYM}/1h/) is NOT identical to ln(F/S) (it is a bounded impact-price premium), so using it is a substitution to be pre-registered, not the paper spec. Funding realized per interval from data/futures/um/monthly/fundingRate/{SYM}/ (path from memory).",
  "signal": "y_t = ln(F_t) - ln(S_t) measured at each funding settlement t (Eq. 26-27, p.61). Each 8h, sort the universe into 5 quintiles on y_t (also tested: raw basis F/S - 1).",
  "entry_exit": "Enter at t (immediately after funding payment at t), exit at t+8h at next funding settlement. Portfolio '1-5' = long lowest-basis quintile, short highest-basis quintile (Table 19). Holding return = perp log price change + realized funding yield (funding 'proxied by realized opposite funding payments', p.83).",
  "holding_period": "8h (one funding cycle), rebalanced every 8h",
  "sizing": "Equal-weighted within quintile, absolute weights sum to 1 per portfolio (p.83-84). No leverage specified.",
  "parameters": {
    "quintiles": "5 (VERIFIED p.83)",
    "holding_8h": "VERIFIED p.60, 84",
    "newey_west_lags": "4 (VERIFIED, Table 19 note)",
    "min_volume_filter_1M_USD_daily": "VERIFIED p.81",
    "exact timestamp of basis measurement (close of 1h bar before settlement?)": "UNVERIFIED",
    "whether short leg uses perp price only": "UNVERIFIED"
  },
  "source_sample": "2020-01-01 to 2023-07-01 (model calibration data stated Jan 2020-Jul 2023, p.70)",
  "reported_performance": "Log-basis 1-5 portfolio: mean 2.66% per week, t=9.54 (Table 19, p.85); raw basis 1-5: 1.98% per week, t=8.46. Decomposition for log-basis 1-5: spot 0.28% (t=1.25), term 2.11% (t=26.22), funding fee yield 0.26% (t=8.71). Quintile 1 holding mean 4.17% (t=3.49) vs quintile 5 -0.93% (t=-0.55). Single-factor alpha vs market/BTC/ETH/BNB/XRP 2.61%-2.66% per week (Table 20). Sharpe ratio not reported for this strategy. Costs: NOT applied in Chapter 3 (no fee/slippage discussion found). Gross figures only. Annualized by authors as about 138% (p.84).",
  "post_publication_evidence": "None found. No independent replication located. Basis-momentum (BM) variants show same sign structure (p.89).",
  "known_weaknesses": "Mostly 'term return' (basis convergence), i.e. the signal is basis mean reversion between settlements, which is partly mechanical and overlaps funding/basis-carry class the repo excludes; equal-weighted across many illiquid small perps, 2020-2021 listing boom; weekly aggregation of 8h returns unclear (compounded vs summed); 8h round trips cost far more than edge per trade unless gross per 8h is large; short leg requires borrowing-free perp short (fine) but crowded in squeezes; thesis footnote era data excludes post-2023-09 4h funding regime for about one third of contracts (p.214-215); author-list conflict on SSRN; no costs."
}
```

```json
{
  "id": "C2",
  "name": "Signed taker price-volume imbalance quintile sort (positive, linear), 8h holding",
  "source": "Luo thesis Chapter 3, same universe/data as C1 (Tables 23, 29)",
  "pages": "p.93 (definition, Table 23), p.99-102 (Table 29), p.113 (Fig 8), p.120 (Table 36 rows 24-31)",
  "asset_universe": "Same as C1",
  "bar_interval": "8h aggregates built from 1h taker flow",
  "signal_data": "UNVERIFIED mapping. Archive klines columns taker_buy_quote_volume and quote_volume at data/futures/um/daily/klines/{SYM}/1h/ give taker-buy and taker-sell dollar volume (sell = quote_volume - taker_buy_quote_volume).",
  "signal": "PVI_L,t = mean over the past L days (3 eight-hour contracts per day) of [price-taking-buyer price*volume minus price-taking-seller price*volume] per 8h window (Table 23, p.93). Sort into quintiles on PVI. Tested L = 1d, 7d, 14d, 21d, 28d, 56d, 112d, 350d.",
  "entry_exit": "Long highest-PVI quintile (1), short lowest (5), held 8h from t to t+8h, rebalanced every 8h. Table labels column '1-5' as High-minus-Low.",
  "holding_period": "8h",
  "sizing": "Equal-weighted quintile portfolios",
  "parameters": {
    "lookback_L_days": "1 or 7 best, VERIFIED in Table 29 p.102; others weaker",
    "scaling_of_PVI": "UNVERIFIED: definition is unscaled dollar imbalance (not divided by volume), so ranking mixes size with imbalance; not stated whether normalized"
  },
  "source_sample": "2020-01-01 to 2023-07-01",
  "reported_performance": "1-5 weekly mean: L=1d 1.38% (t=5.92), L=7d 1.39% (t=5.92), L=14d 1.21% (t=5.25), L=21d 1.23% (t=5.16), L=28d 1.17%, L=56d 0.81% (t=3.56), L=112d 0.90%, L=350d 0.53% (t=2.53) (Table 29, p.102). Funding-fee leg 0.08% per week. One-factor FBAS alpha not significant for unscaled 1/7/14-day versions; two-factor model alphas insignificant (Table 37). No Sharpe, no costs reported.",
  "post_publication_evidence": "None found.",
  "known_weaknesses": "Unscaled imbalance is likely a proxy for coin size/volume in the cross-section (thesis itself shows the price-volume factor subsumes size and momentum, p.57); all 63 significant strategies are explained by two factors, so this is not independent of C1; no costs; same sample/universe issues as C1; wash-trading volume concern flagged by the author (p.95)."
}
```

```json
{
  "id": "C3",
  "name": "Category (sector) momentum, 7-day rank, 1-day hold, daily rebalanced",
  "source": "Luo thesis Chapter 4 (category momentum in perpetual futures)",
  "pages": "p.149-152 (data), p.158-161 (Table 42, Panel B), p.170-178 (Table 43, trading frictions), p.175-176, p.188 (Table 45)",
  "asset_universe": "30 value-weighted CoinMarketCap category portfolios built from Binance perps (selected from 128 categories: 50 with >=10 coins, minus 20 with >70% coin overlap); average 25 perps per category; BTC/ETH-containing categories hold about 50%/20% of cap",
  "bar_interval": "daily (end-of-day close)",
  "signal_data": "Binance perp daily closes (data/futures/um/daily/klines/{SYM}/1d/); category membership and market cap from CoinMarketCap (NOT a free historical-membership archive; point-in-time membership is UNVERIFIED and likely lookahead-contaminated if current labels are used)",
  "signal": "Rank the 30 category portfolios on past L=7-day return (value-weighted within category).",
  "entry_exit": "Long equal-weighted top 5 categories, short equal-weighted bottom 5, hold H=1 day, rebalance daily (overlapping-ranking construction of Jegadeesh-Titman used when H>1).",
  "holding_period": "1 day",
  "sizing": "Half-dollar long / half-dollar short, equal-weight across the 5+5 categories",
  "parameters": {
    "L_7d_H_1d": "VERIFIED Table 42/43",
    "top_bottom_5": "VERIFIED p.161",
    "coin_weights_within_category": "value weights, VERIFIED p.149",
    "category_overlap_threshold_70pct": "VERIFIED p.153 (but chosen after seeing the data)"
  },
  "source_sample": "Returns evaluated 2020-01-01 to 2024-07-01; categories formed from Oct 2019",
  "reported_performance": "CCM(7,1): winners-minus-losers 1.93% per week, t=3.98 (Table 43 Panel A); CSMB/3-week-momentum-adjusted 1.18% per week, t=2.83. Per day about 0.28% gross. Authors' costs: perp commission 0.025% one-way, 'total about 0.1% per dollar one-way' incl spread and impact; net 0.18% per day = 1.26% per week (66% of gross) with turnover about 100% per day (p.174). Skipping a week between ranking and holding: 0.49% per week, t=0.99 (not significant). Holding H>=7: 0.95% per week, adjusted not significant. No Sharpe ratio reported. Alpha vs CMKT/CSMB/CMOM/FBAS/FPRV: CCM(7,1) alpha 0.0017 per day (t=3.58) (Table 46).",
  "post_publication_evidence": "None found.",
  "known_weaknesses": "Category lists are CoinMarketCap tags (time-varying, retroactive tagging risk); 30 of 128 categories chosen after looking at overlap statistics; buy-side drives most profit in a 2020-2024 bull sample (authors' own explanation, p.177); strongest only at 1-day hold, disappears after skipping a week; high turnover; BTC/ETH categories dominate; heavy overlap of coins across categories; author's cost assumption is a claim with no execution test; same-universe/sector-factor concerns under repo rule against more trend variants on the same coins (this one needs coins beyond the 10-coin set but is still a crypto-factor trend variant)."
}
```

```json
{
  "id": "C4",
  "name": "Quarter-hour opening taker-order-imbalance sign, 4-12h forecast",
  "source": "Chan Kim and Peter R. Hansen, 'The Quarter-Hour Effect: Periodic Algorithmic Trading and Return Predictability in Cryptocurrency Futures', arXiv:2607.09426v2 (16 Jul 2026)",
  "pages": "p.5-7 (data, OI definition), p.34-40 (Section 6, regressions, Tables 5, A.4-A.7), p.30 and p.52 (Table A.3, economic magnitude)",
  "asset_universe": "Six Binance USDT perps: BTC, ETH, XRP, SOL, DOGE, ADA",
  "bar_interval": "10-second bars at each quarter-hour opening; horizons 4h, 8h, 12h",
  "signal_data": "Binance aggTrades (data/futures/um/daily/aggTrades/{SYM}/), fields price, quantity, timestamp, is_buyer_maker. This is NOT the metrics/open-interest file; 'OI' in the paper means order imbalance, not open interest.",
  "signal": "OI_t = sum_k V_k*D_k / sum_k V_k over the first 10 seconds of each :00/:15/:30/:45 (D=+1 if isBuyerMaker is False). Forward cumulative log return from last trade price at t over horizon l regressed on OI_t with clock-time interaction: r_{t,t+l} = a + b*OI_t + b1*OI_t*I(b=1) + b5*OI_t*I(m%5==0,b=1) + b15*OI_t*I(m%15==0,b=1) + g'W_t. Predictive slope of interest is CFE_15min = b + b1 + b5 + b15.",
  "entry_exit": "Not a trading rule in the paper. A rule would be: go in the direction of sign(OI) at each quarter-hour opening, hold 4-12h.",
  "holding_period": "4h to 12h",
  "sizing": "Not specified",
  "parameters": {
    "window_10s": "VERIFIED p.10",
    "horizons_4h_8h_12h": "VERIFIED p.36",
    "HAC_bandwidth": "equal to horizon in 10s steps, VERIFIED Table A.4",
    "trade_rule_threshold_or_sign": "UNVERIFIED (author-free choice)"
  },
  "source_sample": "2021-01-01 to 2024-10-31; roughly 131,700 quarter-hour openings per asset",
  "reported_performance": "CFE_15min at 12h in bp per unit OI (raw): BTC 6.39 (t=3.34), ETH 5.40, XRP 7.78, SOL 6.73 (t=1.79), DOGE 11.33, ADA 5.10 (Table A.4); sign-of-OI version: BTC 2.73 bp, ETH 2.38, XRP 3.08, SOL 3.64, DOGE 4.80, ADA 3.44 (Table A.5). At 4h: sign version 0.75 to 2.08 bp, several insignificant. Authors state the predictable component of the 10-second opening return is about 0.5 bp per boundary (about one tenth of a standard taker fee 5 bp; one twentieth of a round trip) (p.30, Table A.3), and they explicitly decline to present a net-of-cost strategy. Binance standard-tier fees 5 bp taker/2 bp maker (footnote 6). No Sharpe ratio.",
  "post_publication_evidence": "Paper has an independent data-validation/replication study by W. Kimbrough per acknowledgments (details not found); no out-of-sample post-sample evidence beyond Oct 2024.",
  "known_weaknesses": "Effect size (2 to 6 bp per trade at 4-12h) is a fraction of 14 bp round trip; overlapping returns across many quarter-hours; tick-level aggTrades needed (large downloads); results are regressions, not a trading rule; SOL 8h insignificant; funding-time quarter-hours excluded as robustness but regime differences unclear; cites Binance data errors fixed March 2026."
}
```

### Inferences
- C1 and C2 share the same two-factor structure: all 63 significant strategies (Table 37-38) have insignificant alpha after FBAS (basis) and FPRV (price-volume) factors, so they are not independent evidence; treat C1+C2 as one finding.
- Cross-check of the C1 headline: 2.66%/week over 21 eight-hour periods is about 12.7 bp per 8h on a long-short book if the weekly figure is a sum of 8h returns; paying 14 bp round trip on both legs each 8h would exceed that. This arithmetic rests on an assumption (weekly mean = sum of 21 periods) that I could not verify.

### Gaps
- Whether Table 19 weekly returns are 21-period sums or compounded; turnover of the basis sort; any cost analysis for Chapter 3 (none found).
- Point-in-time category membership for C3.

## Q4. Does a 14 bps round-trip cost leave a published edge at this horizon?

### Takeaway
Not credibly, on what is published. Costs were either not applied (C1, C2), reported only as a claim with a 0.1% one-way assumption (C3), or shown by the authors themselves to dominate the effect (C4: about 0.5 bp gross per boundary against a 10 bp round trip at standard taker fees).

### Cited Findings
- Authors of C4 state the predictable component is about one twentieth of a round-trip cost; Binance standard fees 5 bp taker, 2 bp maker over 2021-2024 — [arXiv 2607.09426](https://arxiv.org/pdf/2607.09426) p.30
- C3 authors report 1.93% per week gross, 1.26% net under their 0.1% one-way assumption with about 100% daily turnover, and loss of significance when one week is skipped or horizons exceed one day — thesis Chapter 4 p.174, Table 43 — [thesis](https://era.ed.ac.uk/handle/1842/43608)
- C1/C2: no cost treatment found in Chapter 3 — same thesis.

### Inferences
- C3 is the only candidate with published net numbers; its gross edge is about 28 bp/day. Net of 14 bp round trip on full daily gross turnover that is about 14 bp/day before funding, slippage in small categories and the lookahead risk in category labels, leaving roughly 1% a week at best; the 70%-retained claim does not survive a conservative haircut for bull-market sample and retroactive tags. Rate it unproven.
- C1/C2 could survive only if gross per 8h exceeds roughly 28 bp on two-leg turnover, which the headline numbers only approach under a favorable (and unverified) aggregation reading.
- Because 14 bp is above the standard-tier taker round trip (10 bp), maker-fill assumptions are the only way to lower costs; none of the papers model queue risk.

### Gaps
- A cost-aware replication is needed to settle this; per brief, none was run here.
