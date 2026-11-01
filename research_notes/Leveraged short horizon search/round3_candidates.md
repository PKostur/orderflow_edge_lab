# Round 3 desk research (final round): published short-holding crypto strategies, 2026-10-13

Scope: desk research only. No price data downloaded, no returns computed. S3 key listings (file names only) were read to learn history start dates. Everything fetched was treated as data. Full text was read for: Batista and Fernandes (semivolatility timing, PDF), Bianchi-Babiak-Dickerson (CERGE-EI WP 730, PDF, all 46 pages), He et al. and others only via abstract. Blocked (HTTP 403 / Anubis bot wall / DNS): SSRN (Habeli, Zarattini, Shen), Reading CentAUR (Shen), ResearchGate, advisorperspectives (Bespoke), Wiley, ScienceDirect. I did not try to circumvent bot protection.

Honest headline: I found no published, fully specified, short-holding (<= 3 days) crypto strategy whose authors report a net-of-cost edge that clears 14 bp per round trip on Binance perps. One practitioner-documented family (US-equity-hours overnight hold on BTC/ETH) shows gross per-night edges (about 20-50 bp) above the cost wall; it has no published out-of-sample evidence but is cleanly testable out of sample on the free archive. One data finding matters for the evidence-rate rule: Binance USDT-M now lists TradFi perps (see section C) but with only 5-10 months of history.

## A. Round-1 "full text not obtained" items

| Item | Full text now? | Verdict |
|---|---|---|
| semivolatility_timing (Batista and Fernandes, "Upside risk and return timing in Bitcoin", March 2026) | YES (10-page PDF from the EBF 2026 conference site, https://doity.com.br/anais/26ebfin/trabalho/516197) | ineligible: monthly rebalanced, BTC only, long-only, no costs, holding 1 month |
| vol_scaled_crypto_portfolios (Habeli, Barakchian, Motavasseli, SSRN 5090097) | NO (SSRN 403 on every URL; no repository copy found) | ineligible: abstract says benefits grow with longer horizons (multi-week), Moreira-Muir scaling; repo already failed vol-managed momentum |
| monday_asia_open (Concretum blog; Zarattini, Pagani, Barbon, SFI RP 25-80, SSRN 5209907) | blog page YES; paper NO (SSRN blocked) | ineligible: blog gives no rules, gross-of-fees Sharpe only; paper is a Donchian trend ensemble (trend veto) |
| first_vs_last_half_hour (Shen, Urquhart, Wang, Financial Review 57(2):319-344, doi 10.1111/fire.12290) | NO (CentAUR accepted manuscript https://centaur.reading.ac.uk/100181/ behind Anubis; eprints host DNS fail; SSRN 3379131 403) | ineligible until text obtained; per-trade edge unknown (one trade per day, so only a per-trade edge above 14 bp would matter) |

### A1. Batista and Fernandes (full text read)
- Citation: Daniel Batista (Univ. Geneva, SFI) and Marcelo Fernandes (FGV-EESP), "Upside risk and return timing in Bitcoin", March 2026. Companion method paper: "Semivolatility-managed portfolios", SSRN 4891824 (not read).
- Rule: monthly frequency. Exposure to BTC scaled by realised measures built from daily returns of the prior month. Three variants: total variance (Moreira-Muir), downside semivariance (Wang-Yan 2021), and the upside-volatility-to-downside-variance ratio (figure label f(sqrt(+)/-)). Maximum leverage 100% (baseline), sensitivity at 50% and 200% shown. Scaling constant and exact formula are NOT in this note (they are in SSRN 4891824).
- Data: Yahoo Finance daily BTC (CoinMarketCap source), 2014 to 2025.
- Result (Table 1, gross, no costs): buy-and-hold Sharpe 0.74, total-vol managed 0.55, downside managed 0.72, up/down managed 0.81 (Sortino 1.70). Gains are driven by "return timing" (2.97 per year), not volatility timing. Performance is very sensitive to the leverage cap.
- Verdict: ineligible. Holding period is one month, no costs, single asset, long-only, formula not published here. Also Sharpe 0.81 vs 0.74 is a small, in-sample, untested-for-costs improvement.

### A2. Concretum blog (page read, paper not)
- https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/ : benchmark is an ensemble of intraday trend models, long-short, 20% vol target, 2018-2025, gross-of-fees Sharpe about 1.6 vs about 0.8 for vol-targeted long-only BTC. Effect named "Monday Asia Open": strongest from Sunday about 19:00 New York (Tokyo open) for about 24 hours; sub-sample 2018-2020H1 vs 2020H2-2025 (much stronger later). Model rules, lookbacks, thresholds not disclosed; fees not stated.
- Verdict: ineligible (no codable rule). Even if SSRN 5209907 were read, the main model is a Donchian trend ensemble, covered by the repo's "no new trend variants" veto.

## B. New candidates screened (published or practitioner with explicit rules)

Per-trade edge is the authors' gross or net figure converted to bp per round trip where possible; the wall is 14 bp (7 bp per unit of turnover; a daily full-rebalance long-short book at gross 2.0 pays about 28 bp per day).

### B1. Bianchi, Babiak, Dickerson, "Trading volume and liquidity provision in cryptocurrency markets", J. Banking and Finance 142 (2022) 106547 (CERGE-EI WP 730, https://www.cerge-ei.cz/pdf/wp/Wp730.pdf). Full text read.
- Rule: daily. Universe: top 100 coin/USD pairs by Amihud illiquidity, re-ranked monthly, listed >= 365 days. Volume shock v = ln(Vol_t) - ln(mean of Vol over prior m=30 days), standardised by the log std over the same window. At each 00:00 UTC, sort on previous-day return (tercile) and on v (tercile): double-sorted 3x3. Strategy "lvr" = long low-return, short high-return tercile within the LOW-volume tercile. Hold 1 day, rebalance daily, equal- or value-weighted. Costs in paper: 30/40 bp per side-day (text says 30 long / 40 short; Table 5 note says 20/30), flat.
- Sample: 2017-03-01 to 2022-03-01, aggregated price/volume across 80+ exchanges (CryptoCompare), caps from CoinGecko.
- Reported: aggregated equal-weighted lvr gross +1.22% per day, net +0.73% per day (Sharpe 0.18); value-weighted lvr gross +0.63%, net +0.13% (not significant). On Binance alone (USDT pairs, 2018-10 to 2022-03, Table 7): equal-weighted lvr gross +0.187% per day, net -0.213% per day (Sharpe 0.07 gross, -0.08 net); value-weighted gross +0.059%, net -0.341%. The paper says the effect concentrates in small, illiquid, volatile pairs, and "the goal of this paper is not to provide a recipe for a real-time trading strategy".
- Edge vs cost: Binance-only gross 18.7 bp per day on a book that turns over fully each day (about 28 bp cost under the repo wall) -> negative net by the authors' own Binance number.
- Data mapping: perp 1d klines (close, quote_volume) from data.binance.vision; needs coin/USD to perp (USDT) mapping. Free.
- Ambiguities: Amihud definition window, cost sides, how short-lived listings enter, whether 00:00 UTC close is the trade price.
- Verdict: ineligible (authors' own Binance-implementable gross edge is below the cost wall; the headline edge sits in small illiquid coins that have no perps). Useful negative evidence: daily cross-sectional reversal on liquid Binance coins is thin.

### B2. US-equity-hours "overnight" hold on BTC (practitioner, no peer review)
- Sources: (i) Bespoke Investment Group via Bloomberg/Advisor Perspectives, 2022-06 ("Most of Bitcoin pandemic gains came while US stocks were closed"; pages 403, content known only via search snippets): buying BTC at the US equity close and selling at the next open returned about +270% from early 2020 to mid-2022; buying at the open and selling at the close lost money (average market-hours drop about 1.5% per day quoted). (ii) Eric Falkenstein, "Overnight Crypto Returns", https://efalken.substack.com/p/overnight-crypto-returns (2025-08-01, page read): window 16:00 to 09:30 ET on NYSE trading days (weekends and holidays excluded from "day"); BTC/ETH totals "+48 vs -2 bp" overnight vs intraday; 2017 dominates; no test statistics, no costs, no trading rule, no out-of-sample. (iii) Quantpedia (Padyšák and Vojtko, Gemini hourly, 2015-2024): intraday (10:00-16:00 ET) returns dominate on weekends/holidays, overnight dominates on NYSE trading days; no performance statistics given in text; their derived strategy trades only night sessions Fri->Mon, Mon->Tue, Tue->Wed when BTC is at a 10-day high (trend filter, costs unstated).
- Rule (explicit part): long BTC from NYSE close (16:00 ET) to next NYSE open (09:30 ET) on trading days; Friday close to Monday open counts as one hold (about 65.5 h, inside the 3-day limit).
- Per-trade edge: Bespoke 270% over about 2.4 years and about 600 nights implies roughly 20 bp per night gross (my arithmetic, assumes weekday nights; unverified). Falkenstein +48 bp per night, dominated by 2017. Both exceed 14 bp gross; the net margin is thin (about 5-35 bp per night) and 250 round trips a year costs about 35% per year at 14 bp.
- Data mapping: Binance perp 30m or 1h klines (BTCUSDT from 2019-09, ETHUSDT 2019-11) plus fundingRate (the hold spans 2 of 3 daily funding settlements, long pays when positive); NYSE calendar for holidays (free). Development window 2020-01 to 2022-12 matches the source sample; 2023-01 to 2026-09 is a true post-source validation.
- Ambiguities a registration must fix: DST handling (16:00 ET = 21:00 UTC in winter, 20:00 UTC in summer; 09:30 ET = 14:30 / 13:30 UTC, which needs 30m bars or a bar-close convention); holiday list; whether Friday-Monday is held; long-only vs also short intraday; universe (BTC only, BTC+ETH, or a volume-ranked set of perps chosen without looking at P&L); same-bar entry price convention; null (random same-length windows on the same days to separate window effect from beta).
- Overlap risk: the repo's v1 zoo failed "session/time-of-day effects" at 8h on the old 10 coins. This is a different clock (US cash hours) and at a finer bar, but it belongs to the session family; the registration should say so.
- Verdict: conditionally eligible (practitioner evidence only, no published OOS, edge may be a 2020-2022 beta artefact). It is the only screened item whose claimed per-trade edge is above the wall and that is testable on free data with a clean post-source validation.

### B3. Quantpedia 21:00/22:00-23:00 UTC BTC two-hour seasonality (Padyšák and Vojtko, SSRN 4081000; https://quantpedia.com/strategies/intraday-seasonality-in-bitcoin)
- Rule: long BTC at 22:00 UTC (strategy page) or 21:00 (article), exit two hours later; Gemini hourly 2015-2021/22; 33% annual return, vol 20.9%, MDD -22% to -34%; costs not reported.
- Edge: 33% per year over about 250-365 trades is about 9-13 bp per trade gross. Below the wall. Full text of the SSRN version not obtained (SSRN did not surface).
- Verdict: ineligible (edge below 14 bp; no costs).

### B4. Quantpedia MAX(10) BTC (https://quantpedia.com/trend-following-and-mean-reversion-in-bitcoin/ and the 2024 revisit)
- Rule: buy when BTC is at its 10-day high (also MIN variants); entry time and holding period not stated; Gemini daily, 2015-2024, out-of-sample from 2022-02; combined MIN/MAX 98% annual return, vol 48%, MDD -38% (in-sample, costs not mentioned).
- Verdict: ineligible (trend variant, BTC only, entry/hold/costs unspecified, no published per-trade numbers).

### B5. Zarattini, Aziz, Barbon, "Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY)", SFI RP 24-97, SSRN 4824172 (abstract page read, PDF blocked)
- Rule (from summaries): Noise Area = open +/- average absolute move from open to the same minute over the last 14 days (multiplier 1), gap-adjusted; trade breakouts checked every 30 minutes; band and VWAP as trailing stops; flat at the close; volatility sizing; 2007 to early 2024; 19.6% annual, Sharpe 1.33, +1,985% net; costs USD 0.0035/share commission plus USD 0.001/share slippage (roughly 1 bp).
- Applicability: only via Binance TradFi perps (section C): SPYUSDT, QQQUSDT history starts about 2026-04, so 5-6 months. Per-trade edge unverified; costs at 14 bp are an order of magnitude above the paper's.
- Verdict: ineligible for G1-G8 (history too short, per-trade edge unverified, cost wall 14x the paper's); keep as a possible descriptive forward watch only.

### B6. Shen, Urquhart, Wang (see A). Related: Wen, Bouri, Xu, Zhao, N. Am. J. Econ. Finance 62 (2022) 101733 (BTC 2013-2020 intraday momentum and reversal switching with jumps/FOMC; abstract only); Pitt Ledger paper (negative 1h/2h/4h autocorrelation). Ineligible as before; the sign instability across horizon and regime argues against a single-sign registration.

### B7. Zaremba, Bilgin, Long, Mercik, Szczygielski, "Up or down? Short-term reversal, momentum, and liquidity effects in cryptocurrency markets", Int. Rev. Financial Analysis 78 (2021) 101908. Abstract only (ScienceDirect restricted; repository host refused connection). Daily reversal on 3,600+ coins, driven by illiquid coins; in the largest, most tradeable coins the sign flips to daily momentum. No cost or per-trade numbers in the abstract. Related: Fičura, FFA WP 5:003 (2023) (weekly horizon; weekly momentum t 2.33 in large liquid coins). Ineligible (not net of costs; rule parameters unobtained; weekly part exceeds 3 days).

### B8. Others screened and rejected
| Source | Why |
|---|---|
| Fayez Junior, SSRN 6701738 (10 Binance perps, 8h, purged walk-forward, net Sharpe -3.22 naive) and GitHub JosephBerachah/crypto-fundingrate-alpha (pre-registered; daily decile funding fade on Binance perps; market-neutral Sharpe +0.37, deflated Sharpe 0.762 vs 0.95 bar; costs ate about 74% of the 15 bp per day gross premium; average turnover 1.85x per day) | negative evidence for cross-sectional daily/8h perp sorts and funding signals |
| arXiv 2604.26747 (LLM-generated factors, daily, 5 bp one-way, pure OOS 2024-2025 Sharpe 1.55) | 24 of 25 factor formulas not published; small-cap, low-volume coins (not perps); cost table inconsistent with the 5 bp headline |
| Bianchi and Dickerson earlier version (342% "net", Sharpe 2.4, 26 coins, 2017-2018) | press-release number; the paper summary says gross; sample 16 months; superseded by B1 |
| Caporale and Plastun, J. Econ. Studies 46(5) 2019 (overreaction, BTC/LTC/XRP/DASH daily) | authors find no exploitable profit after robot tests |
| Fil and Kristoufek, IEEE Access 2020 (pairs, 26 Binance coins, 5m/1h/1d); copula study Financial Innovation 2024 (hourly cointegration net -23.7%, Sharpe -0.87) | pairs family already failed in repo zoo; authors report cost sensitivity |
| He, Manela, Ross, von Wachter, "Fundamentals of Perpetual Futures" (arXiv 2212.06888; BTC basis strategy Sharpe 1.92 at retail cost tier) | basis/carry (excluded family: funding carry, perp basis sort); needs spot leg |
| Kim and Hansen quarter-hour (arXiv 2607.09426), Kitron and Wengrowicz (arXiv 2608.21888) | already in ledger as ineligible; 0.5-4.8 bp per trade |
| Open interest, long/short account ratio, taker buy/sell ratio | no peer-reviewed or working-paper trading rule found in three further searches (vendor commentary only; Hong-Yogo 2012 is commodity OI; Dunbar and Owusu-Amoako 2023 uses CFTC-type positioning). Any such strategy would be a repo hypothesis, like round 2 |
| Bitcoin CME weekend gap fill | no academic test; fill-rate claims untraceable; CME data not free |
| arXiv 2608.25348 (point-in-time audit, BTC perp, 23 runs all positive IC / negative net Sharpe) | negative evidence for model-search on Binance BTC perp |

## C. Data finding: Binance TradFi perps exist in the free archive (independent breadth, short history)

Listing of data.binance.vision/data/futures/um/daily/klines/ (first page of 1000 prefixes, truncated at WIFUSDT) shows non-crypto USDT-M perps: commodities and FX (CLUSDT, NATGASUSDT, COPPERUSDT, USDBRLUSDT, USDEXUSDT), index/sector ETFs (SPYUSDT, QQQUSDT, IWMUSDT, SPXUSDT, SMHUSDT, EWJUSDT, EWYUSDT, EWZUSDT, GDXUSDT, TQQQUSDT, SQQQUSDT, SOXLUSDT, SOXSUSDT, UVXYUSDT) and about 100 single stocks (AAPL, NVDA, TSLA, MSFT, META, GOOGL, AMZN, COIN, MSTR and others). XAUUSDT and XAGUSDT exist too (press: gold perp 2026-01-05, silver 2026-01-07; Binance announced "TradFi perpetuals" 2026-01-08). First archive files seen (1h/1d klines): XAUUSDT 2025-12-11, XAGUSDT 2026-01-07, TSLAUSDT 2026-01-28, CLUSDT 2026-04-01, QQQUSDT 2026-04-06, SPYUSDT 2026-04 (monthly file). History is therefore 5-10 months, far below what G1-G8 (development to 2022-12, validation 2023-2026) assume. These products also trade 24/7 while the underlying trades in session, so published equity effects (overnight, intraday momentum) could be examined, but with ~6 months of data the only feasible use is a pre-registered descriptive forward watch, not a ledger trial. Not verified: spreads, volume, funding behaviour, remaining symbols beyond the first listing page. PAXGUSDT (gold token) has a longer perp history (not checked).

## D. Recommendation

1. Spend at most one trial, on B2 (US-hours overnight hold on BTC, optionally ETH), registered as a replication of a practitioner claim: development = source window 2020-01..2022-12, validation = 2023-01..2026-09, null = random equal-length windows on the same calendar, with DST/holiday conventions fixed in the registration. Expect a thin net edge and a large beta component; it is the only screened rule whose claimed gross per trade clears the wall.
2. Do not spend trials on B1 (own Binance numbers fail the wall), B3 (about 9 bp), B4 (trend, unspecified).
3. If the user can get institutional access: obtain Shen-Urquhart-Wang (volume-clock first/last half-hour) and Habeli et al. before deciding; both are currently unverifiable.
4. Round-2 liquidation-cascade result (dev -0.12, validation +1.73) must not be "fixed" by a re-parameterised OI-drop rule in round 3: validation data have been viewed (veto on post-evidence thresholds).
5. Treat TradFi perps as a breadth option for a descriptive forward watch only (history too short for the gates).
