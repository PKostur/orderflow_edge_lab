# Transcript analysis: Moon Dev prediction-market and teaching videos

Scope: three locally saved transcripts, read in full. Citations are "video id @ h:mm:ss". Transcript text is auto-captioned, so numbers and names are sometimes garbled; flagged where it matters. Everything below is what the speaker says or shows on screen, not independently verified. No web lookups were made.

Overall verdict: none of the three videos contains a tested edge, an out-of-sample result or a live P&L record. All three are live "over the shoulder" coding sessions with sales funnels. Usable material is limited to (a) a handful of free-data and market-structure facts, and (b) one cautionary exhibit on multiple testing.

---

## 1. "I Built an AI Kalshi Bot That Spots What Others Can't"

- URL: https://www.youtube.com/watch?v=YhJvEeeVCRw (file YhJvEeeVCRw.txt)
- Length: about 1:29:30 (last timestamp 1:29:32). It is a livestream replay.
- Rough share: technical about 10% (0:02:30 to 0:25:50, 0:41:50 to 0:44:10, plus scattered asides); marketing and sales about 55% (0:04:00 to 0:05:45, 0:25:50 to 0:28:00, 0:44:40 to 1:20:00, i.e. several repeated pitches); chatter, NFT giveaway and banter about 35%.

### What the title's claim actually rests on
- The "bot" is a Kalshi trade scanner, not a trading bot. It lists large trades (over $1,000) so the host can discover markets (0:02:46, 0:07:39 to 0:08:18, 0:20:54 to 0:21:04). No Kalshi order is placed in the video; he is "restricted" when he tries to bid (0:25:09 to 0:25:11).
- The scanner is a copy of an existing Polymarket whale scanner he says he built earlier (0:20:40 to 0:21:04). It polls on a roughly 15-second refresh (0:08:18).
- "Spots what others can't" therefore means: seeing which markets large traders are active in. There is no model, no price forecast, no fee model and no backtest. The mechanism is implicit: copying or following "whales" and "discovering ideas" (0:21:01, "unlimited ideas").
- The one edge mechanism stated is an AI-generated cross-venue "arbitrage" (see below). It was never tested and it has no fee or fill modelling.
- The host says directly that he knows little about Kalshi and is "starting at square one" (0:16:01). He also says the arbitrage idea has not been tried: "who knows until somebody actually tries it" (0:02:07).

### Concrete ideas with timestamps
- Kalshi public API (no key needed for market data): get markets, filter by status (unopened, closed, settled), candlesticks at 1-minute and 1-hour periods (0:03:04 to 0:03:56). Demo account exists (0:03:25). Scanner built from public endpoints (0:07:39).
- Whale-trade scanner for Kalshi, threshold over $1,000 per trade, output market name, side, size and link; last 25 whales (0:08:55 to 0:09:15). The Polymarket version ignores crypto and sports markets (0:20:48 to 0:20:55).
- Inventory of Polymarket bot types he proposes to port (0:14:00 to 0:14:39): lag-arb, liquidation momentum, stink bids, whale copy, "no"-market bots, weather no-bots, Elon-tweet no-bots, mean reversion, spread, Poly/Hyperliquid hedging, MACD plus CVD, LLM agent bots, market-maker framework, esports scanners, Kelly position sizing, auto-redeem. Only names are shown; no performance.
- Gas-price idea: price national average gas (AAA-resolved Kalshi/Polymarket markets, thresholds near $4.14 to $4.30) from oil or gas futures; relationship unknown to him (0:16:18 to 0:19:00). He notes Kalshi and Polymarket list slightly different thresholds and that thin markets carry maker rewards (0:18:40 to 0:18:58). He also says he suspects the two venues cooperate (0:18:44).
- Expiration-day idea: on the last day of a "will X touch/close above Y" market, look for low-risk "no" positions (0:23:57 to 0:24:40, 0:28:14 to 0:28:21). Worked example: WTI crude market on a $105 threshold, intraday high 104.94, resolves on official CME settlement price, "no" priced about 96.7 cents (a gain of "3 something%" if filled) (0:22:03 to 0:25:00). He then adds this is risky because it could still close above (0:25:22). He did not trade it.
- Earnings-market idea: Polymarket had about a 78% implied probability that Nike beats earnings (transcript also shows a garbled "738%") (0:29:54 to 0:30:32). He suggests backtesting the stock reaction to past beats over 30 years (0:30:39 to 0:30:48). No backtest is run.
- Stink-bid idea on sports markets (0:19:00 to 0:21:00, 0:34:15 to 0:38:05): resting limit bids far below the market, to be filled when a large holder dumps. An LLM answer is read out claiming this is impossible at a traditional sportsbook (0:34:20 to 0:35:00). Example from the LLM answer: Lakers "yes" at 65 cents, bid at 52 cents, filled when a whale dumps, claimed 92% return versus 54% (0:35:09 to 0:35:48).
- Cross-venue "risk-free" arb (LLM-generated, read out on screen, 0:40:34 to 0:41:11): stink bids at -20% on both Polymarket and Kalshi; if a whale dumps on one and the bid fills at 52 cents, market-sell on the other venue at 65 for a locked 13 cents per share "risk-free". The host's own caveat: simpler to sit on one venue and sell on reversion to fair value, and "in the long run" he thinks the answer is holding to expiration, which "is going to take some testing" (0:41:22 to 0:41:40).
- Concrete NBA stink-bid test specification given to Claude Code (0:41:42 to 0:44:12): Polymarket only, all NBA games that night; bid size $2; bid 30% below the price of the favourite (the more expensive side, e.g. 62 cents); 30% is a variable at the top of the script; cancel unfilled bids when the second half starts (he also says "end of second quarter"); if filled, hold to expiration, no sell; needs live score and clock from an ESPN-style feed. He says "we're going to have the data back tomorrow" (0:44:03). No result appears in this video.
- Data-vendor claims (0:49:00 to 0:57:00): a paid "API key" gives Hyperliquid positions with liquidation distances, Binance and Hyperliquid liquidations, Polymarket trade filters, and one-hour OHLCV for "the last 400 weeks" for BTC, ETH and SOL (0:52:04 to 0:52:12). Screen shows example whales with liquidation prices 1.2% to 8% away (0:51:08 to 0:51:30). Claim "not even Wall Street has this" (0:57:11). The key is a 24-hour bonus for a $5 Zoom or a lifetime perk of the up-sell.
- Prediction "arena" (0:59:05 to 1:01:00, 1:22:15 to 1:24:30): community members predict next-hour or 5-minute BTC price; prizes are a $1,795 credit (weekly) or a $50 NFT (daily).
- Question from chat (1:16:20 to 1:16:37): Polymarket 5-minute up/down market differs from the TradingView chart used to backtest. His answer is only "stay off TradingView." Possibly relevant as a data-source warning (resolution source of the market matters), but he gives no detail.
- RBI process stated (0:54:15 to 0:54:50): research, backtest, incubate in small size. Not demonstrated in this video.

### Reported numbers with timestamps
| Item | Value | Timestamp | Evidence quality |
|---|---|---|---|
| Arb profit (LLM example) | 13 cents per share, "risk-free" | 0:41:03, also 0:00:33 | hypothetical example, no fees |
| Stink-bid discount example | 52 vs 65 cents, "92% vs 54% return" | 0:35:44 to 0:35:48 | hypothetical LLM arithmetic |
| Expiration "no" price | about 96.7 cents, upside "3 something%" | 0:24:02 to 0:24:08 | spot observation, not traded |
| Crude intraday high vs threshold | 104.94 vs 105 | 0:22:20 to 0:22:29 | spot observation |
| Nike beat probability | about 78% | 0:30:24 to 0:30:32 | market price, no outcome tracked |
| Arena records | "8 correct, 2 wrong"; "13 correct, 4 wrong" | 0:59:20 to 0:59:28 | tiny samples, self-selected leaderboard |
| Polymarket bot counts | 83 scripts; "300 bots and backtests" | 0:09:18, 1:10:01 | marketing |
| Scanner refresh | 15 seconds | 0:08:18 | tool detail |
| Fees | none quoted for Kalshi or Polymarket | n/a | omission |
| Sample period / live P&L | none given | n/a | omission |

### Validation/overfitting observations
- No backtest, sample period, out-of-sample split, fee schedule, slippage or fill model is shown for any Kalshi idea. The word backtest appears only as a promise (e.g. 0:30:39, 0:29:14 to 0:29:21).
- Selection process is "throw up so many shots, see what sticks" (0:17:22). That is explicit multiple testing with no correction, and the host says "I'll be wrong every day" (0:17:17), so the format is idea sampling rather than validation.
- The risk-free arb is not risk-free as described. Visible gaps in the argument: (1) it assumes the second venue price stays at 65 after a whale dump on the first (the dump itself is information that probably moves both); (2) it ignores fees on both venues; (3) it ignores fill adverse selection (a stink bid fills mainly when informed sellers hit it); (4) it ignores differing resolution rules between venues, which he partly notes at 0:18:40 (the markets are "slightly changed"). This is my assessment from what is on screen; the transcript contains no evidence either way.
- The 30%-below-favourite parameter is a round number picked in conversation (0:41:55 to 0:42:10), not derived from data. A live test with $2 bids over one night of NBA games would give a handful of fills at most; no sample-size or stopping rule is stated.
- "Polymarket is built to pull inside information out of insiders" (0:30:58 to 0:31:08) and "wisdom of the crowd" are asserted without evidence.
- Chat testimonials and arena leaderboard (1:21:49 to 1:22:45) are anecdotes; the host says arena is "in beta" (1:24:26).
- Look-ahead is not applicable because no model exists. Cost omission is total.

### Usable for our repo?
- Not usable as a strategy source. It is exactly the "ideas zoo" pattern we have already failed on, and it has no data or result to pre-register against.
- Possible independent-breadth angle (my inference, not stated in the video): resolved Kalshi markets are public and resolve on short horizons (15-minute crypto-threshold markets, daily economic and gas markets), so a descriptive calibration study (implied probability versus realised frequency, net of the published fee schedule) could produce an answer in days rather than months, and sits outside the crypto-factor trend book. Caveats the transcript cannot answer: how much history the free Kalshi API serves, the actual fee schedule (not quoted in the video; must be checked from Kalshi's own documentation), and whether any longshot or favourite bias survives fees. This would be calibration of the prediction-market price, not a trade signal, and must be pre-registered before any data is pulled. Kalshi's crypto-threshold markets overlap the crypto factor and would not count as independent.
- The stink-bid and cross-venue arb ideas require order placement and are excluded by the no-live-trading rule. Watch-only observation of bid depth would require data that the video does not show how to obtain for free.
- The whale scanner on Polymarket is already a public-data concept, but "follow big trades" has no validation here and would be a new per-trade diagnostic; skip.
- Liquidation and position data (0:49:00 to 0:57:00): paid or perk-gated and unverifiable; our OKX liquidation-flow collection is already in progress and should not be redirected by this claim. Hyperliquid positions being public is a platform feature, not a Moon Dev edge, and venue-mismatch problems from the failed funding-carry work apply to any Hyperliquid-derived signal.
- Nike-style "prediction-market probability -> stock reaction" backtest (0:30:39) is an interesting independent-information idea in principle but needs historical Polymarket price archives that the video does not source.

---

## 2. "Harvard Algorithmic Trading with AI (for CS50 Grads)"

- URL: https://www.youtube.com/watch?v=Vu62g43_1aE (file Vu62g43_1aE.txt)
- Length: about 1:33:45 (last timestamp 1:33:41). Livestream-style tutorial with Cursor.
- Rough share: technical about 35% (0:33:00 to 0:47:00 data and templates, 0:48:00 to 1:10:00 one backtest, 1:10:00 to 1:30:00 bot scaffold); motivational and filler about 55% (personal systems, Jim Simons, typing speed, quotes, sleep/meditation, README writing); marketing about 10% (course and boot camp, scattered, e.g. 1:15:07 to 1:15:35, 1:29:59 to 1:30:15).
- Note: despite the title there is no Harvard affiliation shown. CS50 is named only as a prerequisite course (0:03:56, 0:14:10, 1:31:09). The title is an audience hook.

### What the title's claim actually rests on
- The claim is a teaching workflow (RBI: research, backtest, implement) plus a template repo, not a performance result. The one backtest shown is self-described as a "random strategy picked out of thin air" (0:58:36 to 0:58:41) and the host says "it doesn't matter if it works or not" (0:48:50 to 0:48:56).
- He explicitly says AI is not used here to predict price (0:03:03 to 0:03:10); AI is used for writing code, READMEs and explanations (Claude 3.7 Sonnet inside Cursor, 0:07:00 to 0:07:12).

### Concrete ideas with timestamps
- RBI loop: research, then backtest on OHLCV, then implement only at "tiny size" after past success (0:05:35 to 0:06:35, 1:14:18 to 1:14:30, 1:07:35 to 1:08:20).
- Idea sources: Google Scholar, university repos, finance journals, AI/ML papers with code, "Chat with Traders" podcast, Market Wizards, YouTube, a ChatGPT-generated list of 20 approaches (trend following, mean reversion, momentum, breakout, ML time series, reinforcement learning, sentiment) (0:21:41 to 0:24:08, 0:30:26 to 0:31:20). Book list read out at 0:24:26 to 0:27:05 (includes Advances in Financial Machine Learning, Permutation and Randomization Tests, Testing and Tuning Market Trading Systems, Systematic Trading).
- Backtest libraries named: backtrader, backtesting.py (his preference), zipline (0:33:15 to 0:33:55).
- Free data sources: Yahoo Finance via yfinance for daily stocks (0:34:38 to 0:37:00; the download attempt "didn't work" for one asset, 0:41:16); Hyperliquid candle API with no key, only "a couple months" of 15-minute data (0:41:32 to 0:44:20); Coinbase "also gives free data" (0:44:31); his road-map downloads of BTC 1-hour "1,000 weeks", BTC/ETH 6-hour "1,000 weeks" (0:40:56, 0:44:50 to 0:45:10, transcript is ambiguous on which files).
- Worked strategy: Bollinger Band squeeze breakout confirmed by ADX, with Keltner channel squeeze detection; parameters named at 0:56:28 to 0:56:50: BB window 20, BB std 2, Keltner window 20, Keltner ATR multiple 1.5, plus ADX period and threshold, take-profit and stop-loss. Optimisation grid of 342 combinations (0:58:14), later narrowed "to make it faster" (0:59:50 to 1:00:50).
- Cost assumption stated: fees "typically 0.001%" but he set 0.002 "so I can see something with higher fees" and "it will account a little bit for the slippage" (1:03:30 to 1:03:55). Units are ambiguous in the caption (0.001 as a fraction is 0.1%, not 0.001%); no separate slippage model. He says fees matter because "500 opens and closes" (1:03:34).
- Metric preferences: expectancy above 0.2, Sharpe above 1.2 to 1.5, profit factor, Sortino, Calmar, exposure time, drawdown (0:58:07 to 0:59:55). He argues lower exposure time reduces black-swan risk (1:04:40 to 1:07:25, mostly LLM text).
- LLM-generated overfitting checklist read aloud (1:01:02 to 1:03:25): walk-forward testing, limit parameters, wider parameter steps, cross-asset validation, parameter-stability checks, regime tests, include transaction costs.
- Bot scaffold: .env for keys, .gitignore, `bot.py` with TA-Lib indicators, limit orders, cancel-all before new order, position check, decimal handling, one-minute schedule, Hyperliquid via a helper file; CCXT mentioned for other exchanges (1:10:20 to 1:23:00, 1:21:47 to 1:22:20). Checklist screenshot of risk controls and P&L close (1:13:44 to 1:13:54).
- Claim of data edge: liquidation and position visibility "is my secret alpha source" (0:02:11 to 0:02:40, 1:31:41 to 1:32:20, 1:32:03 "not so secret"). Not demonstrated or used in any code in this video.
- Mentioned but not shown: AI agent class and a liquidation-data class offered if viewers comment (1:31:29 to 1:31:41).

### Reported numbers with timestamps
| Item | Value | Timestamp | Note |
|---|---|---|---|
| Unoptimised BB-squeeze+ADX backtest | profit factor 1.08, expectancy 0.15 | 0:58:02 to 0:58:09 | host says he wants over 0.2 |
| Same, return | 22% | 0:59:12 | asset appears to be BTC (0:58:54, 0:59:20); period not stated |
| Same, trades / win rate | 217 trades, 42% | 1:00:01 to 1:00:05 | |
| Optimised run | expectancy 0.23, exposure 21%, return 122% (also spoken as "112"), max drawdown about 30%, win rate 57.3% | 1:04:03 to 1:05:10 | optimised on the same data, no holdout |
| Grid size | 342 combinations | 0:58:14 | |
| Fee setting | 0.002 (units unclear) | 1:03:43 | slippage only "accounted a little" |
| Buy-and-hold BTC drawdown | "like 90%" | 0:59:20 | asserted |
| Idea hit rate | "1 out of 10" described as a good outcome | 0:48:59 to 0:50:52 | anecdote from a student |
| Typing speed | 62 then 162 wpm | 0:11:50 to 0:11:59 | irrelevant |
| Timeframe mismatch | backtest on 6-hour bars, bot on 4-hour bars | 1:18:41 to 1:19:05 | host admits "not following my backtest" |

### Validation/overfitting observations
- In-sample selection is visible and admitted: the result shown is the best of a 342-point parameter search on the whole dataset, with no walk-forward or holdout run (1:04:03 to 1:05:50). Return moved from 22% to 122% and win rate from 42% to 57% purely from optimisation, which is the signature of overfitting. The host states the caveat himself ("may have been over optimized", 1:08:22) and says he did not test other timeframes or assets (1:08:29 to 1:08:37), then also says he "got lucky" it worked immediately (1:09:03).
- The grid was narrowed and re-run after seeing the first output (0:59:50 to 1:00:50). That is post-hoc parameter choice.
- Multiple testing is endorsed rather than controlled: a 10% idea hit rate is called "nice" and a losing backtest is a "secret power" (0:49:09 to 0:50:52). With no correction, a 1-in-10 survivor rate is about what pure noise would give at conventional thresholds.
- Costs: a single fee number of unclear units, no spread or funding model, and no short-side or leverage costs described. The LLM text warns "many seemingly profitable strategies disappear" with fees (1:03:16), but the shown run does not demonstrate robustness to higher costs.
- Sample period: not stated for the BB-squeeze run; data files are described as "1,000 weeks" or "a couple months" depending on source (0:41:00 to 0:44:50). Look-ahead handling in the backtesting.py code is not inspected; AI-written code is accepted without review (0:55:19 to 0:55:36). A column-count bug was patched live (0:55:40 to 0:56:20), so data parsing was not verified.
- The host's own "avoid survivorship bias" line (0:09:52) refers to the README text; nothing is done about it, and the yfinance tickers are current large caps (Apple, Google, Amazon, 0:34:44 to 0:38:00).
- Bot deployment was judged by a screenshot checklist, not by out-of-sample tracking (1:13:44).

### Usable for our repo?
- Strategy content: no. BB squeeze + ADX is another trend/breakout variant; it conflicts with the evidence-rate veto (no new trend variants) and the failed strategy-zoo and FX/index trend results.
- Methodology content: as a negative exhibit only. It illustrates the pattern our pre-registration is designed to block (grid search on the full sample, narrowing after viewing, selection by hit rate, backtest/live timeframe mismatch). The LLM-generated checklist (walk-forward, parameter stability, cross-asset validation, realistic costs) is generic and already covered by our protocol.
- Data content: Hyperliquid free candle endpoint (no key; depth only "a couple months" for 15-minute bars) and Yahoo daily data are free but already known; Hyperliquid data has a venue-mismatch history in our repo (carry artifact). No new independent information.
- Liquidation and positions claims are teasers with no code in the video.
- Nothing here shortens time-to-answer or adds breadth.

---

## 3. "I Built a Python Bot for Prize Picks!"

- URL: https://www.youtube.com/watch?v=cp9bzlkU31c (file cp9bzlkU31c.txt)
- Length: about 28:45 (last timestamp 0:28:45; transcript ends mid-sentence about putting a link in the description).
- Rough share: technical about 25% (0:00:45 to 0:07:30, 0:15:40 to 0:16:30, 0:20:40 to 0:23:40); marketing and calls to action about 15% (0:00:15 to 0:00:40, 0:15:40 to 0:16:05, 0:23:06 to 0:23:20, 0:24:40 to 0:25:40); chatter, a side project (Twitch/TikTok stream recorder) and a private-key leak aside about 60%.

### What the title's claim actually rests on
- "Built a bot" means a script that downloads PrizePicks league and projection listings through an unofficial endpoint and saves them to CSV (0:00:45 to 0:02:30). There is no prediction, odds comparison, edge estimate or bet placement. The host says the code gives him a look at the markets, and "I'm sure this will give you some alpha" (0:22:49), which is a claim without any supporting analysis.
- The Selenium scraper he asks Claude to build failed: browser closed with "no data to save" (0:16:06 to 0:16:12), then the site blocked him with a press-and-hold bot check (0:22:05 to 0:22:30). He concedes the only working file is the markets fetcher (0:23:36 to 0:23:38).

### Concrete ideas with timestamps
- Endpoint: a partner API path for leagues and projections (transcript spells it "partner-api.prizepix.com/leagues", a caption error for PrizePicks) (0:01:56 to 0:02:12). Fetch all projections, 1,000 per page, group by league, show stat types, save two CSVs (0:02:12 to 0:02:40). Leagues seen include basketball, soccer, football, tennis and CS:GO (0:02:39 to 0:02:48).
- Paid odds alternative: Optic Odds offers PrizePicks-style props, live odds, historical odds, injury reports and results via a paid sign-up; the host dismisses it (0:03:08 to 0:04:13).
- Scraping guide with Selenium, Pandas and Chrome (0:04:15 to 0:05:30). A commenter asks whether scraping is allowed (0:04:36).
- Possible geo restriction noted on the site (0:21:02 to 0:21:34).
- Google Trends API as a possible data source, from a viewer; host says "I heard they have a Google Trends API now" and asks chat if anyone has used it (0:24:09 to 0:24:35, 0:26:55). Unverified.
- Side project: livestream recorder for Twitch/TikTok/Kick, unrelated to trading (0:11:20 to 0:19:00).

### Reported numbers with timestamps
- "Thousand per page" for projections (0:02:17).
- "Over 250 daily props" (from a scraping guide read aloud, 0:04:55).
- Five spaces left in a paid camp, $101 off (0:24:42 to 0:25:30), and a 90-day refund guarantee (0:15:50): marketing only.
- No odds, hit rates, P&L, sample period, or fee assumptions are given. PrizePicks is a pick'em format with its own payout structure, which is never discussed.

### Validation/overfitting observations
- There is nothing to validate: no model, no backtest, no live bets. The edge claim is purely rhetorical.
- Multiple testing and look-ahead do not apply; cost omission is total (no payout structure, vig or entry-fee model).
- Data reliability: the working endpoint is undocumented, the scraper failed, and there is no historical data (the host notes that historical data "is important to us", 0:03:38, then only finds it behind a paid vendor).
- Operational note: the host says he leaked a private key on stream the previous day and deleted the video (0:19:38 to 0:20:06). This is relevant only as a warning about the author's reliability and security habits, not to our work.

### Usable for our repo?
- No. It is fantasy-sports pick'em (not crypto), has no free historical data, depends on an unofficial endpoint and scraping that is blocked, carries terms-of-service and jurisdiction risk, and nothing in the video produces a testable hypothesis. It adds neither independent information nor a faster answer.

---

## Cross-video summary for the report writer

| Video | Edge claim evidence | Out-of-sample | Costs | Live result | Value to repo |
|---|---|---|---|---|---|
| Kalshi bot | none (scanner plus LLM-written arb idea) | none | not modelled | none | idea only; possible pre-registered calibration study on public resolved-market data (inference) |
| Harvard/CS50 | one in-sample optimised backtest (BTC, 6h, 342-point grid) | none | single fee number, unclear units | none | negative exhibit of overfitting workflow |
| Prize Picks | none | none | none | none | none |

Gaps and cautions
- Sample period and exact asset for the BB-squeeze backtest are not stated in the transcript (BTC is inferred from 0:58:54 and 0:59:20).
- Fee numbers are caption-garbled (1:03:34 to 1:03:55 in video 2); do not cite as exact.
- The Kalshi fee schedule, API history depth and historical availability of Polymarket/Kalshi prices are not covered by any of the three transcripts and would need a separate, pre-registered data check from primary documentation.
- Claims about the Moon Dev API (positions, liquidations, 400 weeks of OHLCV) are vendor claims behind a paywall perk; none is verifiable from these transcripts.
