# Intraday crypto strategies (15 min to 2 h holds), round 1

Scope note: ~20 tool calls. Full texts read: Kitron & Wengrowicz (arXiv 2608.21888, PDF read, all 24 pages). Full text via fetch summary only (HTML/PMC, not page-numbered): Shanaev et al (Heliyon 2023), Kitron-style quarter-hour paper (arXiv 2607.09426, first 100k of 176k chars). NOT obtainable (403 / DNS / paywall / Anubis): Shen-Urquhart-Wang 2022 full text, Wen-Bouri-Xu-Zhao 2022 full text, Kurihara-Matsumoto 2026 full text. Those three are abstract-only, so their parameters are UNVERIFIED and are not presented as codable specs. Several other published results found were not codable or cost-hopeless. Dates in sources: arXiv IDs 26xx are 2026 papers.

## Which published intraday crypto strategies are fully specified, and what do they net after costs?

### Takeaway
Only two sources gave full, codable specs (Kitron-Wengrowicz 15m reversal; Shanaev 15-minute-boundary effect), and both document gross edges (about 1.3 bp and about 0.6 bp per trade) that are an order of magnitude below a 14 bp round trip. The two sources with the most plausible cost profile (one trade a day: Shen et al first-half-hour momentum, and Wen et al) could not be read in full, so their parameters and net economics are unverified.

### Cited Findings

#### Candidate 1: 15-minute directional reversal (bet against the prior bar), with taker-flow conditioning. Source read in full.

```json
{
  "id": "C1",
  "name": "15m sign reversal (fade previous 15m bar), optional flow-driven filter and confidence threshold",
  "source": "Kitron & Wengrowicz, 'Short-horizon mean reversion in cryptocurrency markets: a matched cross-market measurement', arXiv 2608.21888v1, Aug 2026 (preprint, independent researchers; authors disclose they run an automated crypto system using a variant of this model)",
  "pages": "p2 (data, model Eq.1), p3 (primary test box), p5-6 (N=1 baseline, sign flip by decile), p10-11 (taker imbalance, Sec 5.1), p11-12 (cost of capture, Sec 5.2, Fig 8), p16-17 (Appendix A.3 Table 6), p23 (Appendix F channels, G costs)",
  "asset_universe": "Primary: 183 highest-24h-volume Binance USDT SPOT pairs (ex stablecoins, leveraged tokens), post-sample ranked (survivor-tilted); ex-ante subset 133 pairs. Focal: BTC, ETH, SOL, XRP. Reversal also replicates on USDT-M perpetual tape (AUC 0.531-0.538, p23 App F) -- perp results are signal-level only, no perp P&L reported.",
  "bar_interval": "15m (signal decays: 1h AUC lower, 4h gone; 5m gross edge 0.15 bp per trade, worse) [p5 Fig 2, p12]",
  "signal": "Eq.1 (p2): P(up_t)=sigmoid(C + A*sum_{k=1..N} k^-alpha * s_{t-k}), s=tanh(150*r), r=(close-open)/open of each bar, N=12, 3 free params (C,A,alpha), fit by MLE walk-forward (train 5,760 bars / test 960 bars, refit each block). Simplest equivalent (p6, p16): N=1, i.e. go short if previous bar's r>0, long if r<0 (AUC 0.5267 vs 0.5305 for N=12; Table 6 p17). Flow filter (p10): taker imbalance i_t = 2*takerBuyBaseVol_t/Volume_t - 1; bar is 'flow-driven' if sign(r_t)==sign(i_t) (~70% of bars); reversal AUC 0.540 after flow-driven vs 0.519 after flow-opposed bars. Optional confidence threshold |p-0.5|>=tau on ex-ante grid (tau=0.02 cited p12).",
  "entry_exit": "Not a published trading rule with fills. Implied: at close of bar t (bar-start UTC timestamps), take the position opposite to signal for bar t+1 only; label is intra-bar open-to-close (p2). Execution timing/fills UNVERIFIED (paper gives gross edge per trade only).",
  "holding_period": "One 15m bar (implied by open-to-close label)",
  "sizing": "Not specified (directional sign bet; gross edge reported in bp of notional per trade)",
  "parameters": {
    "N_lags": "12 VERIFIED p2 (N=1 and N=3 baselines VERIFIED p16-17)",
    "lambda_tanh": "150 VERIFIED p2/p16",
    "kernel": "k^-alpha, alpha fitted (median 1.16-1.27) VERIFIED Table 6 p17",
    "walk_forward": "train 5,760 / test 960 candles VERIFIED p3",
    "tau_confidence": "0.02 cited as an example only; grid itself UNVERIFIED",
    "flow_filter": "definition VERIFIED p10; any usable cutoff on |i_t| UNVERIFIED (shown by quintile only, Fig 7a)"
  },
  "source_sample": "Primary 2025-01-01 to 2026-02-11 (15m); focal coins multi-year back to 2021-01; frozen holdout 2026-02-12 to 2026-08-08 (p4)",
  "reported_performance": "Statistical, not P&L. 15m OOS AUC: crypto class mean 0.531 (BTC 0.533, ETH 0.538); artifact-robust 0.520; with both artifact adjustments 0.509 (class gap vs stocks +0.011). Holdout: gap +0.020, 60% of pairs still FDR-significant, crypto AUC 0.522 (Table 1 p4). Gross edge per trade peaks ~1.3 bp (BTC, most selective thresholds), unthresholded ~1/20 of the 5 bp maker round-trip, i.e. roughly 0.25 bp; median pair 0.46 bp at tau=0.02; 'not one of the 183 pairs clears even the 5 bp maker band at any threshold' (p12). Cost bands in paper: round trip ~5 bp maker, 10-20 bp taker (p24).",
  "post_publication_evidence": "No independent replication found. Internal: frozen 6-month holdout attenuated by roughly a third to a half (AUC gap 0.031 -> 0.020); BTC per-year AUC drifts slightly downward 2021-2026 (p5-6). Preprint, not peer reviewed.",
  "known_weaknesses": "Edge is far below any realistic cost (authors' own conclusion). Survivor-tilted universe. Effective independent crypto observations ~2.5 (p4). Time-reversal control shows most detectable structure is time-symmetric (p19). Gross figures ignore latency, depth, adverse selection. Spot data; perp P&L not computed. Flat-bar (r=0) convention inflates raw accuracy."
}
```

- 90% of 183 Binance pairs (164/183) show significant 15m directional reversal after FDR vs 2.7% of 187 US stocks; class-mean AUC 0.531 vs 0.499 — [arXiv 2608.21888](https://arxiv.org/pdf/2608.21888) (p3)
- Lag-1 return autocorrelation is near zero on majors (BTC rho1 -0.003) yet betting against the previous candle captures most of the effect; N=1 AUC 0.5267 vs N=12 0.5305 — [arXiv 2608.21888](https://arxiv.org/pdf/2608.21888) (p5-6, p16-17)
- Signal decays monotonically with sampling interval: focal crypto AUC 0.536/0.521/0.496 at 15m/1h/4h — [arXiv 2608.21888](https://arxiv.org/pdf/2608.21888) (p5, p19)
- Funding-related conditioning is flat: reversal is flat in lagged funding rate and lagged |basis|; predictions in the hour containing a funding settlement are slightly LESS accurate (0.531 vs 0.537). Edge peaks 10:00-14:00 and 21:00 UTC and sags in the Asian morning. AUC flat across UTC sessions 0.531-0.542 — [arXiv 2608.21888](https://arxiv.org/pdf/2608.21888) (p23 App F, p20 App D). This is direct evidence against a standalone funding-settlement edge at this horizon (for this signal).
- Gross edge per trade never exceeds ~1.3 bp; taker band 10-20 bp is above the axis range — [arXiv 2608.21888](https://arxiv.org/pdf/2608.21888) (p12 Fig 8)

#### Candidate 2: Turn-of-the-candle (long BTC during minutes :00, :15, :30, :45). Source read via full-text fetch of PMC page (section/table refs from that page).

```json
{
  "id": "C2",
  "name": "Turn-of-the-candle: long during the first minute of each 15-minute candle",
  "source": "Shanaev, Vasenin & Stepanov, 'Turn-of-the-candle effect in bitcoin returns', Heliyon 2023 (peer reviewed), PMC10015199",
  "pages": "Sec 3 (data, Eq.2), Sec 4 (strategy), Tables 1-7, Fig 1 (no page numbers available from HTML fetch)",
  "asset_universe": "BTC only, 7 exchanges incl. Binance (spot, from Aug 2017), Bitfinex, Gemini, Bitstamp, Bittrex, Kucoin, FTX",
  "bar_interval": "1m",
  "signal": "Dummy D_t=1 if the 1-minute bar is minute 0, 15, 30 or 45 of the hour (UTC clock assumed; timestamp convention UNVERIFIED), else 0. Model: 1m log return on D_t, HAC SEs, OLS and quantile (median) regression (Sec 3, Eq.2).",
  "entry_exit": "Hold long BTC only during the turn minutes (Sec 4). Exact entry/exit within the minute (open of minute :00 to close of that minute?) UNVERIFIED -- paper does not specify.",
  "holding_period": "1 minute x 4 per hour (96 round trips per day)",
  "sizing": "Fully long, flat otherwise",
  "parameters": {
    "turn_minutes": "0,15,30,45 VERIFIED (Sec 3)",
    "entry_exit_timestamps": "UNVERIFIED",
    "fee_tier_in_paper": "Bitfinex new-account 10 bps and zero-fee tier above 30-day volume of USD 7.5M, spreads from bitcoinity.org (Table 1/5) -- fee basis per trade UNVERIFIED"
  },
  "source_sample": "Each exchange's history to 2021-12-31 (Binance from 2017-08); out-of-sample Bitfinex Jan-Aug 2022 (Table 7)",
  "reported_performance": "Mean turn-minute return 0.58 bps/min in 2021 (0.55 Bittrex to 0.66 Gemini; Fig 1); 2021 OLS coefficients 0.82-0.97 bps (Table 2), t>9 on all exchanges. Strategy (Bitfinex 2021, $5,000 start): net 74.18% p.a. vs 60.27% buy-and-hold, MDD 51.78%, Sharpe 4.96 vs 0.77 (Table 5-6); break-even capital $3,763 (fee-tier dependent). OOS Jan-Aug 2022 Bitfinex coefficients 0.11-0.29 bps, all significant at 1% ('less pronounced').",
  "post_publication_evidence": "Only the authors' own Jan-Aug 2022 out-of-sample (effect shrinks to roughly one third). No independent replication found. Source of effect is attributed to algorithmic/periodic trading (see also quarter-hour paper below).",
  "known_weaknesses": "Gross 0.6-1 bp per 1-minute trade versus 14 bp round trip: even with a zero-fee tier the strategy only beats buy-and-hold by ~14 points in a 2021 bull market and only by being invested ~6.7% of the time with zero fees; Sharpe 4.96 relies on near-zero fees/spread at high VIP volume. Does not survive taker fees. Entry/exit definition ambiguous. Mean effect measured per minute, strategy needs 96 trades/day."
}
```

- Dummy for minutes 0/15/30/45 on 1-minute BTC log returns is positive and significant on all seven exchanges (t>9 in 2021); average turn-minute return 0.58 bps — [Heliyon via PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC10015199/)
- Out-of-sample Bitfinex Jan-Aug 2022 coefficients 0.1126-0.2916 bps, all significant at 1% — [Heliyon via PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC10015199/)
- Related (aggTrades-based, not kline-codable): arXiv 2607.09426 finds order-imbalance in the first 10 seconds of minutes 0/15/30/45 predicts the next 10 seconds on six Binance USDT-M perps (BTC, ETH, XRP, SOL, DOGE, ADA, 2021-01 to 2024-10; walk-forward OOS R2 3.4% mean, AUC 0.60), but sign-weighted realized edge is ~0.5 bp per boundary vs 5 bp taker and the paper says it "is not a net-of-cost trading strategy"; it also reports a negative effect over first half hour, positive at 4-12 hours on 4 of 6 contracts — [arXiv 2607.09426](https://arxiv.org/html/2607.09426v2) (Sec 5.3, 6.1; partial fetch)

#### Candidate 3: Intraday time-series momentum, first half-hour predicts last half-hour (volume-clock for 24/7 BTC). ABSTRACT-ONLY; full text not obtainable.

```json
{
  "id": "C3",
  "name": "Bitcoin intraday time-series momentum: first-30-min return -> last-30-min return (volume-based session clock); related Wen et al momentum/reversal switch",
  "source": "Shen, Urquhart & Wang, 'Bitcoin intraday time series momentum', Financial Review 57(2):319-344, 2022 (DOI 10.1111/fire.12290). Related: Wen, Bouri, Xu & Zhao, 'Intraday return predictability in the cryptocurrency markets: Momentum, reversal, or both', N. Am. J. Econ. Finance 62, 2022 (DOI 10.1016/j.najef.2022.101733). Equity origin: Gao, Han, Li & Zhou (JFE 2018).",
  "pages": "UNVERIFIED (full texts blocked: Reading eprints DNS failure, centaur Anubis denial, Wiley 403, ScienceDirect paywalled)",
  "asset_universe": "Shen et al: Bitcoin only (abstract). Wen et al: BTC, plus ETH, LTC, XRP show similar predictability (abstract). Sample for Wen: high-frequency BTC 2013-03-03 to 2020-05-31 (IDEAS abstract).",
  "bar_interval": "UNVERIFIED (30-minute returns are the natural bar; 1m/5m/30m all codable from Binance klines)",
  "signal": "UNVERIFIED in detail. Abstract only: r_first30 positively predicts r_last30, where 'first' and 'last' are defined on a trading-VOLUME clock (not UTC wall clock) because BTC has no open/close; predictability is strongest in sessions with highest volume or volatility. Equity template (Gao et al, from memory, not verified in this run): r_first = return from prior close to first 30 min, r_12 = second-to-last half hour, predict r_13 = last half hour via sign(r_first [+ r_12]).",
  "entry_exit": "UNVERIFIED. Template: enter at start of last 30 min in direction of r_first, exit at end of day/session.",
  "holding_period": "~30 min once per day (template)",
  "sizing": "UNVERIFIED (abstract mentions market-timing and asset-allocation exercises)",
  "parameters": "ALL UNVERIFIED: volume-clock definition, session length, volume/volatility regime cutoffs, exchange, sample dates, cost assumption.",
  "source_sample": "UNVERIFIED for Shen et al; Wen et al 2013-03-03 to 2020-05-31 (abstract)",
  "reported_performance": "Abstract claims 'substantial economic gains' in market timing and allocation, especially in BTC downturns (Shen); timing strategy beats always-long and buy-and-hold in utility terms (Wen). No Sharpe, no trade count, no cost assumption obtainable.",
  "post_publication_evidence": "None found. Contradiction risk: Wen et al find BOTH momentum and reversal, with reversal described as crypto-specific and regime-dependent (around jumps, FOMC, liquidity, COVID); Ledger (Pitt) paper reports significant NEGATIVE autocorrelation at 1h/2h/4h intervals for BTC (reversal), with larger moves reversing more, attributed to overreaction/leveraged liquidations. Kitron-Wengrowicz finds sign reversal at 15m. Signs depend on horizon and regime.",
  "known_weaknesses": "Cannot be coded exactly from available text. Volume-clock is a data-snooping surface (defining 'first' and 'last' windows). Equity analogue R2 is small (CXO summary: ~0.018 OOS for SPY, third-party). Cost-feasibility depends on per-trade edge, not available."
}
```

- Shen-Urquhart-Wang abstract: volume used as market-time proxy; first half-hour return positively predicts last half-hour return; strongest in high-volume/volatility sessions; gains in market timing/asset allocation especially in downturns; driven by liquidity provision, not late-informed trading — [Birmingham portal](https://research.birmingham.ac.uk/en/publications/bitcoin-intraday-time-series-momentum/)
- Wen et al abstract: BTC data 2013-03-03 to 2020-05-31; both intraday momentum and reversal; changes around large jumps, FOMC, liquidity, COVID; similar predictability in ETH, LTC, XRP; timing strategy earns higher economic value than benchmarks — [IDEAS/RePEc](https://ideas.repec.org:443/a/eee/ecofin/v62y2022ics1062940822000833.html)
- Pitt Ledger paper: significant negative first-order autocorrelation of BTC returns at 1, 2 and 4 hour intervals, stronger after larger moves, author applied a basic algorithmic strategy retroactively (rule not shown on abstract page) — [Ledger](https://ledger.pitt.edu/ojs/ledger/article/view/213)

#### Candidate 4: BTC-leads-altcoins lag trade (shock in BTC, trade lagging altcoins), minute horizon. Peer-reviewed paper abstract-only; the only exact rules found are from an unreviewed GitHub README.

```json
{
  "id": "C4",
  "name": "BTC 5-minute drop -> trade altcoins basket for 15-30 min (lead-lag-trader rule set)",
  "source": "(a) Kurihara & Matsumoto 2026, Asia-Pacific Financial Markets, DOI 10.1007/s10690-026-09589-z (abstract only: BTC Granger-causes small-cap alts, simulated lag strategy with ML triggered by BTC returns beats buy-and-hold). (b) github.com/mamipour/lead-lag-trader README (practitioner repo, NOT research; the exact rules below are from here).",
  "pages": "(a) UNVERIFIED, full text blocked by login redirect; (b) README only",
  "asset_universe": "(b) 19 altcoins in large/mid/small-cap tiers (list not extracted), historical data Binance, paper trading on Kraken Futures. (a) small-cap altcoins (list UNVERIFIED).",
  "bar_interval": "1m candles (b)",
  "signal": "(b) Regime by BTC 7-day return: bear < -5%, neutral -5%..0% (no trades), bull >= 0%. Bear short: BTC falls >1% within 5 minutes, skip if falls >2%, short alts, leverage 1-2x scaled to drop size (cap 2x). Bull long: BTC dips >0.5% within 5 minutes, skip if BTC 3-day return <0, long alts, 1x. No entries in UTC hours 07-11.",
  "entry_exit": "Enter on trigger across all 19 alts simultaneously; exit after fixed hold. Fill price convention UNVERIFIED.",
  "holding_period": "Bear short 15 min; bull long 30 min",
  "sizing": "Full compounding portfolio per trade; leverage 1-2x (bear), 1x (bull)",
  "parameters": "Thresholds (0.5%, 1%, 2%, 5% regime, 7d/3d windows, 07-11 UTC filter) are quoted from the README but appear tuned; no sensitivity shown. UNVERIFIED as to selection method.",
  "source_sample": "(b) Apr 2022 - Mar 2026 (1,440 days), apparently the same period used to choose rules (no OOS reported)",
  "reported_performance": "(b) claims +378% total, ~49% annualized, MDD 47.1%, win rate 55%, 25,230 trades, 13 of 14 rolling 6-month windows profitable; costs 0.02% maker per side + 1 bp slippage per side (i.e. ~6 bp round trip, assumes maker fills). Claim only, self-reported, no verifiable records. Author says 2025-26 shows fewer bear events and smaller per-trade returns, so edge may be shrinking.",
  "post_publication_evidence": "None. Related: tick-level BTC cross-exchange lead of up to ~15 seconds (CBS thesis) and BTC->Cardano tick lead exist but are sub-minute and not tradable on 1m klines with 14 bp costs.",
  "known_weaknesses": "Unreviewed repo; maker-fill assumption on a signal that triggers after an adverse move (adverse selection); no OOS; thresholds look tuned; 25,230 trades over 4 years is only ~17 per day across 19 coins = frequent crowded entries; 1 bp slippage is optimistic in a drop; funding and short-borrow ignored; Binance vs Kraken mismatch. Treat only as a codable hypothesis, not as evidence."
}
```

- Kurihara & Matsumoto (2026): small-cap cryptocurrencies react with delay to BTC moves, one-directional Granger causality BTC -> alts, lower liquidity linked to slower reactions; ML-driven lag strategy beat buy-and-hold in simulation (abstract only; fees/bars not seen) — [Springer DOI](https://doi.org/10.1007/s10690-026-09589-z)
- lead-lag-trader README: rules and claims listed above; backtest only, no OOS — [GitHub README](https://raw.githubusercontent.com/mamipour/lead-lag-trader/main/README.md)

#### Other findings checked and set aside

- Hour-of-day long 21:00 to 23:00 UTC BTC: Quantpedia own research on Gemini hourly data 2015-10-09 to 2022-02-03; annualized 33%, vol 20.93%, max drawdown -22.45%; no costs, no external paper, in-sample — [Quantpedia](https://vvv.quantpedia.com/?p=17341). Inference: 33% p.a. over one 2h trade/day is about 9 bp/day gross, below a 14 bp round trip, so net negative.
- Periodicity in volatility/volume, Binance funding at 00/08/16 UTC conjectured as cause, volatility peaks near 16 UTC — arXiv 2109.12142 (PDF binary fetch, only search snippet used; no return strategy) — [arXiv](https://arxiv.org/pdf/2109.12142). Not a tradable rule; Kitron-Wengrowicz finds funding-hour effects flat/slightly adverse.
- arXiv 2608.25348 (BTC perpetuals point-in-time audit): per search snippet only, all 23 runs had positive IC but negative net Sharpe under primary costs and none of 460 fee-slippage cells positive. Body not readable (compressed PDF), so treat as unverified snippet — [arXiv](https://arxiv.org/pdf/2608.25348)
- Conditional volume-reversal strategy on 26 coins/150 exchanges reporting 342% net annualized, Sharpe 2.4: press coverage only, daily-scale, not verified — set aside.
- Liquidation-cascade papers (arXiv 2608.03616; Hyperliquid Oct-2025 study; Lim 2026): describe cascade mechanics and spread/depth recovery; no backtest of a reversal rule found.

### Inferences
- The only quantified net-of-cost statements in the literature found are negative: Kitron-Wengrowicz (gross <=1.3 bp), quarter-hour paper (0.5 bp), audit snippet (negative net Sharpe in all cost cells).
- The 15m reversal and the 1m turn-of-candle effect probably share a mechanism (periodic algorithmic/flow-driven overshoot) and are both microstructure-sized; neither scales to 14 bp.
- C3 and the Pitt/Wen reversal evidence imply sign instability across horizon and regime (momentum at 30-min-in-day, reversal at 1-4h and 15m), so a pre-registered single-sign rule is risky.
- Taker-flow conditioning (flow-driven bars reverse, flow-opposed bars do not; AUC 0.540 vs 0.519) is the only conditioning with documented incremental information and is codable from klines (taker_buy_base_volume field), but the paper shows it does not lift the edge above cost.
- Funding-settlement returns: no published rule found; the one paper that tested the funding clock found it flat.

### Gaps
- Full text of Shen-Urquhart-Wang, Wen et al and Kurihara-Matsumoto could not be fetched (host errors, bot protection, paywall); their exact windows, cost assumptions and Sharpe are unknown. A reader with institutional access should verify C3 and C4(a) before any pre-registration.
- No published volume-spike continuation/reversal, jump-based, or funding-settlement-return strategy with a full spec and net-of-cost result was found on the kline-testable horizon.
- Replication code for Kitron-Wengrowicz exists (github.com/nadav2/short-horizon-reversion per paper p13) but was not opened.
- Independent post-publication tests of any of the above: none found.

## Do 14 bps round-trip costs (Binance taker 5 bps + 2 bps slippage per side) leave any published edge at this horizon?

### Takeaway
No published edge found at 15 min to 2 h survives 14 bp as a net trading result. Documented gross edges are 0.5-1.3 bp per trade for high-frequency signals, and the single-trade-per-day signals have no verifiable per-trade edge above 14 bp.

### Cited Findings
- 15m reversal: gross edge peaks near 1.3 bp, "not one of the 183 crypto pairs clears even the 5 bp maker band at any threshold," moving to 5m worsens it (0.15 bp); taker band 10-20 bp is above the plotted range — [arXiv 2608.21888](https://arxiv.org/pdf/2608.21888) (p12)
- Quarter-hour boundary prediction: ~0.5 bp realized per boundary vs 5 bp taker fee; authors state it is not a net-of-cost strategy — [arXiv 2607.09426](https://arxiv.org/html/2607.09426v2)
- Turn-of-the-candle: 0.58 bp average per turn minute, positive net only at the zero-fee tier on Bitfinex in 2021, shrinking in 2022 OOS — [Heliyon via PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC10015199/)
- BTC perp audit snippet: no positive net Sharpe in any of 460 fee/slippage cells — [arXiv 2608.25348](https://arxiv.org/pdf/2608.25348) (snippet only)
- Practitioner lead-lag rule claims 49% p.a. at ~6 bp round trip (maker assumption); unverified, no OOS — [GitHub README](https://raw.githubusercontent.com/mamipour/lead-lag-trader/main/README.md)

### Inferences
- Arithmetic: at 14 bp per round trip, a rule needs a gross expectancy per trade above 14 bp. High-frequency candidates (C1, C2) fall short by 10x to 25x; one-trade-per-day candidates (C3) would need a per-trade edge above 14 bp, which the abstracts do not show. A 14 bp threshold equals ~51% p.a. of cost for one round trip per day.
- Only a maker-execution route (2 bp fee, lower slippage, with adverse-selection risk) or a conditional/rarer trigger (C4-style, large moves only, where per-trade moves are tens of bp) plausibly clears costs, and those are the least verified. Any further test here should therefore select on expected move size per trade (thresholded rare events, 1-2 h holds) rather than hit-rate AUC.

### Gaps
- No source reports net P&L on Binance USDT-M perps at taker fees for any 15m-2h rule. Per-trade expectancy for rare large-move reversal/continuation rules (the only plausible route over 14 bp) has no published figure found.
- Candidate gross figures are spot-based (C1) or exchange-specific (C2, Bitfinex/Gemini), not verified on USDT-M perps.
