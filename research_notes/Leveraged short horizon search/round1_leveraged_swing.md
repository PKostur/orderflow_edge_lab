# Leveraged 1-3 day crypto perp strategies and safe-leverage literature (round 1)

Scope note: no backtests were run. Full text was read for only three papers: Kitron and Wengrowicz (arXiv 2608.21888), Cheng et al. (arXiv 2102.04591) and Bui and Nguyen (arXiv 2602.11708). SSRN returned HTTP 403 for the Habeli et al. and Batista da Silva and Fernandes pages, so those entries rest on search-result abstracts and are marked UNVERIFIED. Honest headline: I found NO published, fully specified strategy designed for 1-3 day leveraged perp holding with verified parameters. The candidates below are the closest items, each with stated gaps.

## Q1. Which published, fully specified crypto strategies suit 1-3 day leveraged perp holds (outside the exclusions)?

### Takeaway
Only one candidate (AdaptiveTrend) has an exact codable spec read from full text, and it is a trend variant on 6h bars with no stated leverage, internal inconsistencies, and overlap with the repo's "no new trend variants" veto. The other three are leads with abstract-level detail only. No paper tests post-liquidation-cascade reversal on daily bars; the one paper that names the test calls it an open falsification test.

### Cited Findings

Candidate 1 (full text read, many parameters UNVERIFIED):

```json
{
  "id": "C1",
  "name": "AdaptiveTrend (6h momentum + ATR trailing stop, 70/30 long-short, monthly asset selection)",
  "source": "Bui and Nguyen, Talyxion Research, arXiv:2602.11708v1 (12 Feb 2026), cs.CE, non-peer-reviewed, authors are a trading firm",
  "pages": "Algorithm 1 and Eqs 2-3 p.2; Eqs 4-5 and Table 1 p.3; Tables 2-3 p.4; Tables 4-6 p.5",
  "asset_universe": "150+ Binance USDT perpetual swaps; long candidate set = top K_L=15 by market cap; short candidate set = bottom K_S by market cap (K_S value NOT stated); market cap from CoinGecko daily (p.3)",
  "bar_interval": "6-hour OHLCV (H6) (p.2, p.4 Table 5)",
  "signal": "MOM_t = (P_t - P_{t-L}) / P_{t-L}; long when MOM > theta_entry, short when MOM < -theta_entry_s (Eq 2, p.2). L and theta_entry are grid-searched monthly per asset on the prior month (p.3). Monthly filter: asset admitted only if its prior-month optimised-in-sample Sharpe >= 1.3 (longs) or >= 1.7 (shorts) (Eq 4, p.3).",
  "entry_exit": "Entry at the 6h close when MOM crosses threshold and no position open. Exit only via ATR trailing stop: S_t = max(S_{t-1}, P_t - alpha*ATR_t), initialised P_t - alpha*ATR; close when P_t < S_t (Eq 3, Algorithm 1, p.2). Only the long side is written out; short side described as symmetric entry only. No take-profit published.",
  "holding_period": "Not stated. Trailing-stop exit, 142 trades/month across portfolio (Table 4, p.5), turnover 134% (Table 5). Implied hold per trade cannot be derived from the paper.",
  "sizing_and_leverage": "Capital split lambda=0.7 to longs, 0.3 to shorts, equal weight within each leg: w_long = 0.7/n_L, w_short = 0.3/n_S (Eq 5, p.3). NO leverage, margin mode or position cap is stated anywhere; reported vol 16.8% implies roughly unlevered or modestly levered book. Leverage is UNPUBLISHED.",
  "parameters": {
    "alpha_ATR_multiplier": "default 2.5, plateau 2.0-3.5 (p.4 Sec 5.4, Fig 2) - VERIFIED p.4",
    "lambda": "0.70 (p.3) - VERIFIED",
    "gamma_L_gamma_S": "1.3 / 1.7 (p.3) - VERIFIED",
    "K_L": "15 (p.3) - VERIFIED",
    "K_S": "UNVERIFIED (not stated)",
    "L_lookback": "UNVERIFIED (grid not published)",
    "theta_entry": "UNVERIFIED (grid not published)",
    "ATR_period_k": "UNVERIFIED (not stated)",
    "fees_slippage": "taker 4 bps per trade, linear slippage vs 5-min volume, 8h funding charge/rebate (p.3 Sec 4.2) - VERIFIED; slippage coefficient UNVERIFIED"
  },
  "source_sample": "Data Jan 2021-Dec 2024; IS Jan-Dec 2021; OOS Jan 2022-Dec 2024 (36 months) (p.3). Text on p.3 also quotes a Jan 2022-Oct 2025 curve (Fig 1), inconsistent with the 2024 end date.",
  "reported_performance": "Net of 4 bps costs, OOS: ann. return 40.5%, vol 16.8%, Sharpe 2.41, MDD -12.7%, Calmar 3.18 (Table 1, p.3). Gross (0 bps) Sharpe 2.87; 8 bps Sharpe 2.01; 12 bps 1.62 (Table 4, p.5). Timeframe table: H1 1.54, H4 2.08, H6 2.41, H8 2.18, H12 1.91, D1 1.63 (Table 5). Bear regime -4.2% annualised, Sharpe -0.31 (Table 2). Leverage used: not reported.",
  "post_publication_evidence": "None found (paper is 8 months old at time of search; no replication located).",
  "known_weaknesses": [
    "Sharpe arithmetic: (40.5% - 4.5%)/16.8% = 2.14, not 2.41; 2.41 = 40.5/16.8 with no risk-free deduction, contradicting the stated rf=4.5% (p.3 Sec 4.4). Reported Sharpe is therefore not reproducible from the paper's own numbers.",
    "Cumulative return ~140% over OOS (Fig 1) versus 40.5% annual return over 3 years does not reconcile cleanly (1.405^3 = 177%).",
    "Per-asset monthly grid search of (theta, alpha, L) on one month of data then Sharpe >= 1.3 gate selects noise; ablation shows 'fixed parameters' Sharpe 1.34 vs 2.41 (Table 3), i.e. nearly all the claimed edge comes from in-sample re-optimisation.",
    "Text claims H6 'aligns with the 4-times-daily funding cycle' (p.4) but Binance and the paper's own cost model use 8h funding (3 per day).",
    "Survivorship: universe by market cap rank, delisted coins not discussed. Short leg = bottom-cap coins with $5-10M capacity (p.5).",
    "It is a trend/momentum variant on a multi-coin crypto universe: falls under the repo's 'no new trend variants' veto and is not independent breadth.",
    "No leverage, liquidation, or tail-risk analysis despite being pitched for perps."
  ]
}
```

Candidate 2 (abstract only, spec UNVERIFIED):

```json
{
  "id": "C2",
  "name": "Volatility-scaled crypto market and strategy portfolios (Moreira-Muir style)",
  "source": "Habeli, Barakchian, Motavasseli, 'Adaptive Risk Allocation in Crypto Markets: Evaluating Volatility-Scaled Portfolios', SSRN 5090097 (https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5090097). Full text NOT fetched (HTTP 403).",
  "pages": "UNVERIFIED",
  "asset_universe": "crypto market portfolio plus seven crypto strategies (per search-result abstract); coin list UNVERIFIED",
  "bar_interval": "UNVERIFIED",
  "signal": "scale exposure by inverse of recent realised volatility (abstract-level only); window UNVERIFIED",
  "entry_exit": "UNVERIFIED",
  "holding_period": "UNVERIFIED",
  "sizing_and_leverage": "Abstract says the effect 'remains effective even under tight leverage constraints'; cap values UNVERIFIED",
  "parameters": "all UNVERIFIED",
  "source_sample": "UNVERIFIED",
  "reported_performance": "Abstract: volatility scaling raises Sharpe and produces abnormal returns for certain strategies, especially momentum and the market portfolio. Numbers UNVERIFIED.",
  "post_publication_evidence": "None found",
  "known_weaknesses": ["Spec cannot be coded without the PDF; Moreira-Muir scaling is known to be weak after costs in equities (secondary summaries in search results), no crypto-perp cost treatment known"]
}
```

Candidate 3 (abstract only, spec UNVERIFIED):

```json
{
  "id": "C3",
  "name": "Semivolatility timing of Bitcoin exposure",
  "source": "Batista da Silva and Fernandes, 'Upside risk and return timing in Bitcoin', SSRN 7226305 (https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7226305). Full text NOT fetched (HTTP 403).",
  "pages": "UNVERIFIED",
  "asset_universe": "Bitcoin (abstract-level)",
  "bar_interval": "UNVERIFIED",
  "signal": "separate downside and upside semivolatility; per abstract, ordinary volatility management backfires in Bitcoin because vol spikes often accompany rallies; semivolatility timing rules said to beat buy-and-hold and standard vol-managed strategies. Formula UNVERIFIED.",
  "entry_exit": "UNVERIFIED",
  "holding_period": "UNVERIFIED",
  "sizing_and_leverage": "UNVERIFIED",
  "parameters": "all UNVERIFIED",
  "source_sample": "UNVERIFIED",
  "reported_performance": "UNVERIFIED",
  "post_publication_evidence": "None found",
  "known_weaknesses": ["Single asset (BTC): does not raise independent breadth for the repo", "Direction of finding (do not de-risk after vol spikes) is itself informative for leverage rules"]
}
```

Candidate 4 (secondary summary only, spec UNVERIFIED; weekend/Monday effect tested beyond the 10-coin 8h setup):

```json
{
  "id": "C4",
  "name": "Monday Asia Open effect: intraday Bitcoin trend strongest from Sunday ~19:00 New York for ~24h",
  "source": "Concretum Group, 'Seasonality in Bitcoin intraday trend trading' (https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/), practitioner blog by the authors of Zarattini-Pagani-Barbon; summary fetched, full study/PDF not read",
  "pages": "n/a (web page)",
  "asset_universe": "Bitcoin",
  "bar_interval": "intraday (exact interval UNVERIFIED)",
  "signal": "ensemble of high-frequency trend models, long-short, volatility-targeted to 20% annualised (page summary); entry rule UNVERIFIED",
  "entry_exit": "UNVERIFIED",
  "holding_period": "Intraday; effect window ~24h Sunday evening to Monday. Not 1-3 days.",
  "sizing_and_leverage": "Volatility target 20% annualised; leverage implied by the target, cap UNVERIFIED",
  "parameters": "UNVERIFIED",
  "source_sample": "2018-2025; effect stronger after mid-2020",
  "reported_performance": "Benchmark gross-of-fees Sharpe about 1.6 (long-short vol-targeted); long-only vol-targeted BTC Sharpe just below 0.8. Net numbers not reported in summary.",
  "post_publication_evidence": "None found",
  "known_weaknesses": ["Gross of fees", "BTC only", "Authors themselves say the mechanism is only one plausible explanation", "Intraday horizon does not match 1-3 day hold"]
}
```

Other cited findings (not candidates):
- Kitron and Wengrowicz test short-horizon reversal on 183 Binance spot pairs, 15-minute bars, 2025-01-01 to 2026-02-11, plus a frozen holdout 2026-02-12 to 2026-08-08. Reversal is real (class-mean AUC 0.531 versus 0.499 for stocks; holdout gap +0.020) but the gross edge peaks near 1.3 bp per trade against a 5 bp cheapest round trip, so it is "not exploitable under benchmark spot-cost assumptions" (abstract p.1; Sec 5.2 p.11-12, Fig 8). Signal decays to no-skill by 4h (Fig 2 p.5). Effective independent crypto observations about 2.5 for 183 pairs (p.4). — [arXiv 2608.21888](https://arxiv.org/pdf/2608.21888)
- Same paper (p.13, Limitations and falsification): a reversal after moves pushed by forced liquidation orders, weaker than after matched ordinary flow-driven moves, would be the "informational" prediction; this test is described as open. It confirms I found no published daily-bar post-liquidation reversal test. — [arXiv 2608.21888](https://arxiv.org/pdf/2608.21888)
- Same paper: reversal conditioning on perp basis, funding rate, funding clock, volatility and session is flat (p.11, App F p.23). — [arXiv 2608.21888](https://arxiv.org/pdf/2608.21888)
- Zaremba et al. (2021, IRFA 78:101908) report daily reversal over 3,600+ coins, concentrated in illiquid coins, while the largest, most liquid coins show daily momentum (search-result summary, full text not read). — [IDEAS](https://ideas.repec.org/a/eee/finana/v78y2021ics1057521921002349.html)
- Zarattini, Pagani, Barbon, "Catching Crypto Trends" (SFI RP 25-80): Donchian ensemble with volatility-based sizing on top-20 liquid coins, Sharpe above 1.5 and alpha 10.8% versus BTC net of fees (search-result summary). Full text not read; excluded as a trend variant overlapping the repo's DON8 core. — [IDEAS](https://ideas.repec.org/p/chf/rpseri/rp2580.html)
- Calendar effects: Baur et al. (7 exchanges, 15M observations) found time-varying, non-persistent effects, with lower weekend volume and higher Monday returns; Yaya found no day-of-week return effects across several coins; Quantpedia's summary of a Monday-long strategy says results mostly not different from random trading (search-result summaries). Ali, Du and Majeed (2025) note the weekend benchmark-price ambiguity for crypto. — [Quantpedia](https://quantpedia.com/are-there-any-simple-calendar-effects-in-bitcoin-market/)
- Search for liquidation-cascade papers found only event studies of the Oct 10 2025 cascade (Hyperliquid, BTC) and early-warning-signal papers (arXiv 2607.27070, 2608.03616), not post-cascade return tests. — [arXiv 2607.27070](https://arxiv.org/pdf/2607.27070)

### Inferences
- The binding constraint for the repo is not finding strategy ideas but finding ones that are (a) 1-3 day, (b) leverage-explicit, (c) outside the crypto-factor/trend overlap. None of the located papers meets all three.
- C1's value is mainly as a stop-loss template (ATR trailing stop, alpha about 2.5 on 6h bars) and as a cautionary example of a Sharpe that does not reconcile and of parameters re-optimised monthly; any codable test would need the missing L, theta, k and K_S pre-registered, which the paper does not supply.
- Kitron and Wengrowicz plus Zaremba et al. together suggest short-horizon reversal in liquid coins exists statistically but is thin relative to costs, which argues against levering a daily reversal rule; levering a thin edge increases fee drag proportionally.
- A post-liquidation reversal candidate would be original research (the forced-flow contrast is an open test per p.13), not a replication, and requires liquidation feed data (free sources not verified here).

### Gaps
- Full texts of Habeli et al., Batista da Silva and Fernandes, Hung-Liu-Yang (SSRN 4241996), Zarattini et al. and Zaremba et al. were not obtained; SSRN blocked fetches. Next step: try author sites (abarbon.com/papers/catching-crypto-trends) or the Swiss Finance Institute PDF.
- No paper found on daily-bar post-liquidation-cascade reversal; no paper found on stop-loss plus leverage rules for liquid perps with verified parameters.
- No weekend/Monday study found that is both multi-coin and perp-based and out-of-sample.
- Moreira-Muir applied to Bitcoin: no standalone peer-reviewed test found; closest are C2 and C3 (abstract-level).

## Q2. What does the literature say about safe leverage, liquidation frequency and risk of ruin for crypto perps?

### Takeaway
The only empirical, full-text-verified source is Cheng et al. (BitMEX, 2020): to keep the 1-day margin-call probability at 1%, perp longs need about 32.6% margin (about 3x) and shorts about 21% (about 4.8x), and a normal-distribution assumption understates the required margin by at least half. No source found computes growth-optimal or terminal-ruin leverage for crypto perps specifically; fat-tailed Kelly theory says to use a fraction of Kelly.

### Cited Findings
Cheng, Deng, Wang, Yu, "Liquidation, Leverage and Optimal Margin in Bitcoin Futures Markets", arXiv:2102.04591 (Applied Economics 2021), full text read. Page numbers are PDF pages.
- Data: BitMEX XBT perpetuals; daily liquidation, open interest, OHLC from Coinalyze for 29 Jan 2020 to 3 Feb 2021 (372 days); 5-minute prices 1 Jan 2017 to 6 Feb 2021 (431,346 obs) (p.6). Maximum leverage on venue 100x (p.6).
- Daily forced liquidations averaged 3.51% of open interest for longs and 1.89% for shorts; mean daily liquidations about 20M USD long and 10M USD short; worst long day 843M USD on 12 Mar 2020 when BTC fell about 50% (p.2-3, Table 4 p.21). Max long liquidation ratio 169% of open interest in a day (Table 4, p.21).
- Implied minimum leverage of traders liquidated on a day: mean 58.13x long, 59.94x short, median about 56x (Table 4, p.21; inferred from daily OHLC assuming entry at the day open and liquidation at the day's low/high, so it is a lower bound on leverage, p.10).
- Speculation index (volume/open interest) mean 3.75 versus 0.15 for S&P 500 (p.3, p.10).
- Daily perp price changes (inverse-contract definition): minimum -82.67%, skew -3.67, kurtosis 65.36, SD 4.76% (Table 1 p.18). Daily 8h SD 2.57%.
- Margin required for a given margin-call probability, perpetual futures, GEV tail model (Table 3, p.20), long / short:
  - 1-day, p=0.01: long 32.56%, short 21.01%, common 26.10%. Normal-distribution equivalent: 11.22% long, 10.94% short.
  - 1-day, p=0.001: long 72.10%, short 34.50%.
  - 8-hour, p=0.01: long 21.05%, short 14.76%; p=0.001: long 46.98%, short 26.34%.
  - 1-hour, p=0.01: long 12.50%, short 9.88%.
  - 5-minute, p=0.01: about 5.2% long, 4.1% short.
- Authors' recommendation: 3x for longs and 5x for shorts at a 1% daily margin-call probability (abstract p.1, conclusion p.11). The margin is the full initial margin needed to survive the daily extreme, so margin-call probability here is per sampling block, not per trade.
- Authors state the normality assumption underestimates optimal margins by at least half (p.9, p.11).
- Tail index is higher on the long side for perps, and the long-side tail parameter for daily returns is more than double the short side (p.7).
Source: [arXiv 2102.04591](https://arxiv.org/pdf/2102.04591)

Other items (search-result summaries only, full text not read; treat as UNVERIFIED):
- A PKU/Fields-Institute talk abstract on hedging with automatic liquidation reports that following the optimal strategy a hedger can bring liquidation probability under 1% with leverage mostly below 5x, using minute data from five exchanges. It is a hedger's problem. — [Fields talk](https://gfs.fields.utoronto.ca/talks/Hedging-Automatic-Liquidation-and-Leverage-Selection-Bitcoin-Futures)
- Fat-tailed Kelly with parameter uncertainty, "Leverage and Uncertainty" (arXiv 1612.07194): tail weight shrinks the Kelly fraction and can push growth negative for plausible tail parameters. Generic, not crypto-calibrated. — [arXiv 1612.07194](https://arxiv.org/pdf/1612.07194)
- Hsieh and Barmish, "On Kelly Betting: Some Limitations" (arXiv 1710.01787): Kelly theory breaks down under drawdown constraints. Generic. — [arXiv](https://arxiv.org/abs/1710.01787v1)
- Oct 2025 cascade: a news account reports more than 19 billion USD of leveraged positions closed in a day, about 3.2 billion USD in one minute. Journalistic, not verified against exchange data. — [CryptoSlate](https://cryptoslate.com/crypto-leverage-trading-in-focus-how-leverage-trading-data-tracks-retail-stress-from-liquidations-to-early-warnings/)
- Diar report for ZUBR (sponsored) claimed 75% of liquidations in early 2020 were against the prevailing sentiment and that 20x leverage disadvantages most retail traders; sponsor conflict noted. — [Crowdfund Insider](https://www.crowdfundinsider.com/2020/04/160859-report-calls-cryptocurrency-derivative-trading-gambling-due-to-high-leverage/)
- Habeli et al. abstract says volatility-scaled strategies still work under tight leverage constraints (cap size UNVERIFIED). — [SSRN](https://papers.ssrn.com/sol3/Delivery.cfm/5090097.pdf?abstractid=5090097&mirid=1)

### Inferences
- Rule-of-thumb arithmetic from Cheng Table 3 (my calculation, not a published statement): for a 1-day hold with a stop only at liquidation, 1/margin gives about 3.1x for longs and 4.8x for shorts at p=0.01 (1/0.3256, 1/0.21), and only about 1.4x for longs at p=0.001 (1/0.721). A stop-loss placed well inside the liquidation price changes the ruin problem, but the paper does not model stops, funding or gap-through slippage.
- The sample (2020 BitMEX, includes the 12 Mar 2020 crash) is one extreme-heavy year plus 2017-2021 for the tail fit; inverse-contract long skew does not apply to Binance USDT-margined linear perps, so the long/short asymmetry should not be transferred directly (inference; the paper only tests inverse BitMEX contracts).
- Leverage used by traders liquidated (about 58-60x) tells us about who gets liquidated, not about outcomes of disciplined 2-5x books.

### Gaps
- No academic account-level study of retail leveraged crypto-perp outcomes found (search returned industry reports only).
- No published risk-of-ruin or growth-optimal leverage figure calibrated to crypto perps found; only generic fat-tailed Kelly results.
- Cheng et al. table is at 1-day sampling blocks, no 2-3 day horizon, no linear (USDT-margined) contracts, no funding or stop-loss modelling; post-2021 data absent.
- No full text found for Moreira-Muir-on-crypto leverage rules (C2, C3).
