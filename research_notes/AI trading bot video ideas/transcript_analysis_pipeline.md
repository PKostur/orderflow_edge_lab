# Moon Dev automated strategy-generation pipeline: transcript analysis

Scope: four locally saved transcripts, read in full. Citation form is `[video id @ h:mm:ss]`. Everything below is what the speaker says or shows on screen as transcribed. It is a claim unless the transcript contains a verifiable record. The transcripts are auto-captions, so some numbers are garbled. Those are flagged.

Dates inferred from the transcripts, not stated as such: jApbmBW_HH8 was recorded around 2025-10-16 (the results file says "2025 1016" at 1:21:02). q2ugYN8eSeY was recorded Sunday 2025-10-26 (posts scheduled for the 27th, Halloween on Friday). mOI4-f6QkLc was recorded on a Saturday around late Aug or early Sept 2025 (strike and "September 11th" remarks). RlqzkSgDKDc has no date.

---

## 1. "I Let AI Test 12,000 Trading Bots in One Day (Here's What It Found)"

- URL: https://www.youtube.com/watch?v=jApbmBW_HH8 (transcript file jApbmBW_HH8.txt)
- Length: about 1h30 (last timestamp 1:29:35). He cuts it for length at the end.
- Rough split: about 60% technical (data pulls, prompts to the coding agent, reading result tables), about 12% sales pitch (Zoom/API key/bootcamp reads at 0:04:00-0:06:00, 0:26:13-0:28:35, 0:40:55-0:42:20, 0:58:23-1:00:25, 1:18:26-1:20:44), about 28% chat banter, waiting, and off-topic clips.

### Concrete ideas with timestamps

- Base rule: short at 12 UTC on Wednesdays, take-profit 3%, stop-loss 5%. The coding agent is a Claude Code sub-agent called "backtest architect" [jApb @ 0:02:35-0:02:50, 0:06:34].
- Four variants of the base: plain, MFI, ADX and Kalman filter, run on Wednesday 12 UTC. Filters were dropped later "to make it easier" [jApb @ 0:10:14-0:10:30, 0:16:49, 0:36:24].
- "Timeality" (his coinage, hour-of-day and day-of-week effects). The loop runs the same short rule at each of 24 hours, for each weekday separately, over every data file. A matching long file does the exact inverse [jApb @ 0:31:41-0:32:20, 0:38:40].
  - He also built an "all days combined at hour H" variant [jApb @ 0:40:09-0:40:30, 0:57:41].
  - Rationale for always running the inverse: "a lot of times you're just wrong" [jApb @ 0:52:14-0:52:22].
- Data sources:
  - 19 files of 1-hour OHLCV by the time of the full scan [jApb @ 0:18:28, 0:38:36]. An earlier summary says "25 different" sources [jApb @ 0:16:57].
  - Coinbase 1h: BTC, ETH, SOL, XRP, DOGE, LINK, SUI, ADA, LTC, ZEC, HBAR [jApb @ 0:12:50-0:16:10].
  - Birdeye 1h for Solana tokens: Popcat, Trump, Jup, Fartcoin, WIF, Bonk, Pingu, SPX, Helium, Moodeng, Launchcoin and others [jApb @ 0:06:58-0:21:50].
  - History lengths:
    - "SOL 1 hour 250 weeks, almost 5 years" [jApb @ 0:43:39].
    - SUI and XRP pulled at 52 weeks [jApb @ 0:13:27, 0:58:20].
    - Some Birdeye files have gaps and NaNs [jApb @ 0:23:50].
- Sizing: the first runs used backtesting.py's `size=1` unit, which gave tiny returns. He told it to use 95% of capital per trade [jApb @ 0:25:36-0:28:46]. He also asked for a buy-and-hold column next to the return [jApb @ 0:29:05].
- Result ranking and filters:
  - Per-CSV top-10 by return, by Sharpe, and by shallowest max drawdown [jApb @ 0:47:55-0:49:15, 0:57:30].
  - A second version without BTC, because BTC long "obviously" goes up [jApb @ 0:55:02-0:55:20].
  - A minimum of 5 trades, added after zero-drawdown and NaN rows appeared [jApb @ 1:04:58].
- Second stage: a TP/SL grid for the "winners". It uses backtesting.py's built-in optimizer on five configurations, TP and SL each 1%-15% in 1% steps. It was then extended to 15%-30% [jApb @ 1:10:40-1:13:10, 1:21:13-1:21:33, 1:25:51].
- Stated next step: repeat at 15-minute resolution [jApb @ 1:27:40].
- Context only, not a rule: a "one house = one house coin" memecoin buy bot is mentioned in passing [jApb @ 0:55:48-0:56:55, 1:24:30].

### Reported numbers with timestamps

All are creator-reported from his screen, and none is backed by a record we can check. Metrics are as read aloud.

| Item | Number | Where |
|---|---|---|
| Baseline Wed 12 UTC short, size=1 | "returns are not good on any" | 0:10:26-0:10:35 |
| Same, after the sizing fix, one asset | 18% return, Sharpe 1.47, buy-and-hold -44% | 0:30:24-0:30:36 |
| Same, another file | 1% return vs buy-and-hold 113%, profit factor 1.1 | 0:30:00-0:30:12 |
| Full scan, top short | 257% return, Solana | 0:40:03-0:40:08, 0:43:25 |
| Same row | max drawdown 23%, win rate 71%, "11 UTC" | 0:58:05-0:58:20 |
| Tue and Thu 11:00 short SOL | "218 trades" | 0:43:07 |
| Scan result | SUI 146%, SOL 124% on the short side | 0:43:33-0:43:38 |
| SUI "every day 6 UTC" | 86% win rate (Sharpe not read), then 80% win rate, 68.36 return, drawdown about 10% | 0:52:52, 1:07:10 |
| Another high-Sharpe row | Sharpe 1.59, a 64% win-rate row | 0:46:50, 0:51:49 |
| ETH 1h short | 122% return, -39% drawdown | 1:00:47 |
| Highest-Sharpe row | Sharpe 4.5, only 6 trades, 100% win rate, 18% return, 2% max drawdown | 1:00:53 |
| Long side | BTC 34,000% return, so he drops BTC | 0:50:41 |
| TP/SL optimizer, SOL | 289% at TP 14%, SL 5% (up from 257%, called "less overfit") | 1:15:56-1:16:10 |
| Optimizer total | 5 configurations, 1,125 backtests | 1:21:51 |
| Optimizer best | SUI Monday 7 UTC: 146% return, Sharpe 2.4, drawdown 10% | 1:21:56 |
| Optimizer top five | up to 378%, with a 2% stop (caption partly garbled) | 1:22:09-1:22:17 |
| Optimizer, all days SUI | 242% | 1:22:25 |
| Win rate on the "alpha" config | 22% (winners large, losers small) | 1:24:12 |
| TP/SL 1-15% | "100% profitable" | 1:28:00 |
| TP/SL 15-30% | "total disaster", so "never go wider than 15%" on shorts | 1:28:03-1:28:13 |

Live-trading results: none shown. The only live item is a memecoin buy bot with no P&L.

### What the title claim rests on

"12,000 bots" is a count of backtest runs, not of independent bots. His own tally is:
- Short optimizer: 3,192 runs, which is 19 files x 7 weekdays x 24 hours [jApb @ 0:38:40, 0:57:34].
- Short combined: 456 runs (19 x 24).
- Long optimizer: 3,192, and long combined: 456 [jApb @ 0:57:40-0:57:56].
- Total about 7,300 for the hour scan. Add the 1,125 TP/SL runs and the 4 variants x about 19-25 files earlier, and the sum is under 9,000.
- He says "10,000, no 12,000" at 0:46:14-0:46:18, before the tally is printed. The 12,000 is not supported by the counts shown.

Beyond the count, the runs are one idea (a time-of-week short with fixed TP/SL) crossed with many assets.

The assets are heavily correlated crypto, mostly small and memecoin names. Many were chosen from memory, which he admits "have some selection bias built in" [jApb @ 0:19:52]. The test window for SUI is about one year, for SOL about five.

The "finding" is the top rows of an unadjusted max-over-cells table, such as Tue/Thu 11 UTC SOL short and SUI 6-7 UTC short. He then tuned TP/SL on those same rows.

### Validation and overfitting observations

- In-sample selection:
  - There is no train/test split, no walk-forward, and no holdout. Cells are ranked by return, Sharpe and drawdown on the full sample, and the winners are re-optimized on that same sample.
  - "Held up for 5 years" [jApb @ 0:52:34] only means profitable across the same 5-year sample used to choose it.
- Multiple testing:
  - 19 files x 168 hour-of-week cells x 2 directions is about 6,400 hypotheses. No correction, no null or shuffle baseline, no deflated Sharpe, no count of how many cells are expected to look good by chance.
  - Running "the exact inverse" for every cell doubles the search. He treats it as a feature [jApb @ 0:52:17].
  - Inference: the highest-Sharpe rows (4.5, 100% win rate) have 6 trades. A minimum of 5 trades is no protection. Small-n cells are the ones that top a max-selected table.
- Sign of the effect is largely a market drift effect:
  - He notes "everything is Solana cooked" and shorts beat buy-and-hold "easily" [jApb @ 0:31:07].
  - The tokens are post-peak memecoins. Short returns on a list of assets chosen after the fact partly reflect that those assets fell. This is survivorship and look-back selection in the other direction.
  - His reasoning that "crypto is up only" explains why wide stops fail [jApb @ 1:28:16-1:28:25]. That is an after-the-fact story.
- Cost omissions visible:
  - No fees, spread, slippage, borrow or funding rate for shorts is mentioned anywhere in the video.
  - The venue is spot OHLCV (Coinbase/Birdeye), so a short is a modelled short. Whether commission was left at the backtesting.py default of zero is not stated.
  - With 218 trades or about 365 trades per cell, per-trade costs matter. The TP 3% / SL 5% default also means break-even win rate is 62.5% before costs. This is only valid if the 257% run used those same TP/SL, which the video does not confirm.
- Look-ahead: not demonstrated either way. Entry is "at hour H". Bar-open versus bar-close entry is not discussed and exits are TP/SL only. There is no stated check.
- Implementation errors seen on screen: position size left at 1 unit [jApb @ 0:28:44]; datasets accidentally duplicated, giving the same token twice in the top Sharpe list [jApb @ 1:01:14, 1:07:00]; wrong timeframe files (4h/1d) mixed in [jApb @ 0:18:54]; NaNs from gap data. Results from the first runs were thrown away and rerun, so the final numbers depend on a sequence of edits made while looking at the output.
- He does flag some caution himself: only 6 trades is "fishy" [jApb @ 1:07:34], and the TP/SL gain was small, which "might be less overfit" [jApb @ 1:16:08]. He then treats SOL Tue/Thu 11 UTC and SUI 6-7 UTC shorts as findings to "short for the rest of my life" [jApb @ 0:52:52].

### Usable for our repo?

- As evidence for an edge: no.
  - It is a session/time-of-week effect, which the repo has already tested and failed as part of the strategy zoos.
  - The method is max-over-cells on one sample, with no cost model and no holdout.
  - Under the evidence-rate rule, per-cell diagnostics on crypto coins are disallowed anyway.
- As an idea source: nothing new. Hour-of-day shorts on small Solana tokens do not add independent information. The venue (Birdeye on-chain) is also not our data.
- As a negative worked example: yes, cheaply. The transcript shows a "12,000 bots" headline where the printed counts add to under 9,000, correlated assets, no holdout, and top rows with 6 trades. It illustrates why our pre-registration rules (fixed grid, pre-stated metric, count the grid) exist. No experiment is needed.
- Process points worth noting but not new to us: a minimum-trade filter, a buy-and-hold column next to the return, an explicit count of the cells searched, and writing all results to CSV. The repo has these already, as far as we know.

---

## 2. "I Built an AI That Finds Trading Strategies While I Sleep"

- URL: https://www.youtube.com/watch?v=mOI4-f6QkLc (transcript file mOI4-f6QkLc.txt)
- Length: about 1h09 (last timestamp 1:09:02).
- Rough split: about 50% technical (building the sub-agent, running the multi-dataset tester, reading result tables), about 15% sales pitch (0:02:58-0:05:00, 0:15:04-0:16:50, 0:32:53-0:35:07, 0:45:07-0:47:15, 0:59:19-1:01:34), about 35% chat, M2 discussion and off-topic.

### Concrete ideas with timestamps

- Multi-dataset harness: each strategy file is run once against about 29-30 data sets (BTC, SOL, ES, NQ, AAPL, TSLA, NVDA, GOOG, in several timeframes), and results are collected in one stats table [mOI4 @ 0:00:39-0:01:14, 0:07:40, 0:22:57].
  - Columns shown: exposure time, final equity, return, Sharpe, Sortino, Calmar, max drawdown, average drawdown, expectancy [mOI4 @ 0:01:30-0:01:46].
  - He calls it "apples to apples" across markets [mOI4 @ 0:21:50-0:22:03].
- "Backtest architect" sub-agent (Claude Code, Opus) is told the house framework so every strategy is built to plug into the multi-data tester [mOI4 @ 0:05:06-0:07:15, 0:10:16].
- "Sellers exhaustion" idea family, prompted from a brainstorm by the LLM (7 strategies built in about 7 minutes [mOI4 @ 0:14:58]):
  - Consecutive down closes / sequential decline.
  - Volume spike / climax with a wick.
  - On-balance volume.
  - ATR-volume divergence (declining volume on lower lows).
  - Open interest as an exhaustion signal (he flags it as interesting).
  - Optionally ADX, MFI or Bollinger Bands.
  - Other names listed: gap and go, exhaustion gap, pairs trading, liquidation hunting, seasonality [mOI4 @ 0:08:50-0:11:02]. No rules or thresholds are given for any of them.
- "Trending" folder: 12 trend/momentum strategies from his book notes, built by the sub-agent [mOI4 @ 0:42:43-0:48:23, 0:51:54]. Named in passing:
  - Donchian breakout (long trend), golden cross, ADX plus moving-average trend, Bollinger trend.
  - Quad moving average (from chat) [mOI4 @ 1:08:53].
  - Others listed: gap, 200-day MA, seasonality, "4 days down", intraday Bollinger Mon/Tue/Wed, intraday price-action confirmation.
- AI-based ranking: he asked the LLM to compute a "top 10" using return, drawdown, Sortino and expectancy. He then asked for a "Jim Simons style" re-ranking [mOI4 @ 0:56:19-0:58:50, 1:02:10].
- Viewer macro idea, tested only in conversation: global M2 growth as a BTC signal [mOI4 @ 0:29:37-0:32:35]:
  - Resample BTC to monthly, normalize, and correlate with M2 growth.
  - Rule: go long if M2 growth > 0, else stay in cash.
  - The LLM warns the data is published with a lag and the signal must be lagged to avoid look-ahead bias [mOI4 @ 0:31:41-0:32:00].
  - He wants to "build our own M2 model" to get ahead of the publication lag and calls it "an arbitrage" [mOI4 @ 0:32:35-0:32:53, 0:35:22].
  - A viewer claims BTC follows global M2 by 10-12 weeks. He asks whether it was tested; no answer is given [mOI4 @ 0:35:55-0:36:30].
  - He cannot find global M2 in the IMF portal and notes US M2 "always goes up" [mOI4 @ 0:38:44-0:41:20].
- A viewer mentions a "strategy generator" that uses grammatical evolution [mOI4 @ 0:57:01-0:57:10]. It is not elaborated.

### Reported numbers with timestamps

Numbers are read off his screen. Assets, periods, fees and trade counts are mostly not stated.

| Item | Number | Where |
|---|---|---|
| Trending strategy 1, per data set | expectancy 3.67, then 10.75 ("expectancy of three") | 0:53:58-0:54:20 |
| Best Sharpe on a single file | 1.53 on Tesla; ES 1.27 | 0:54:55-0:55:05 |
| Best expectancy | 11.5, profit factor 6.67, Bollinger trend, with 87% max drawdown | 0:55:42-0:55:52 |
| A quick summary line | "profitable on 17 out of 25" (unclear which strategy) | 0:52:31 |
| LLM "top 10" | Donchian long trend: score 36 of 100 (caption unclear), 563% return, drawdown -41%, return/drawdown 12x, win rate 42% | 0:58:11-0:58:25 |
| Golden cross | 146% return, -34% drawdown, best expectancy 1.75 per trade | 0:59:02-0:59:10 |
| ADX-MA trend | 24% win rate | 0:59:17 |
| "Simons" list | 80% "edge persistence across markets", 98.7 "statistical confidence"; includes a negative-return mean-reversion strategy with 21,795 trades | 1:02:16-1:02:55 |
| Sellers-exhaustion strategies | no performance numbers; one row showed 0; some data errors (Apple, ES) | 0:23:49-0:28:25 |

The first batch of five strategies has no stated results [mOI4 @ 0:00:39-0:01:50].

Live-trading results: none. His "while I sleep" claim is not demonstrated. In the video he supervises the sub-agent for about 7 minutes at a time, and nothing runs unattended.

### What the title claim rests on

"Finds trading strategies while I sleep" rests on three things:
- A sub-agent writes seven strategy files from brainstormed ideas in about 7 minutes [mOI4 @ 0:14:58].
- A test-all script runs them against about 30 data sets [mOI4 @ 0:22:57].
- An LLM prompt ranks the output.

No overnight or autonomous run is shown. Nothing is "found": for the sellers-exhaustion batch he deliberately does not look at the numbers [mOI4 @ 0:23:28-0:23:35]. For the trending batch he mostly says he is "not diving deep into the data today" [mOI4 @ 0:55:10]. The "strategies found" are 12 textbook trend rules with returns summarised across data sets of unknown length.

### Validation and overfitting observations

- Selection without a protocol:
  - There is no stated sample period per data set, no walk-forward, and no holdout.
  - The ranking pools results over assets and timeframes (stocks, futures and crypto together). Each strategy is a bundle of 25-30 cells and the "best" is picked from the table.
  - Counting the cells: 12 strategies x about 25 data sets is about 300 backtests, plus 7 x 30 sellers-exhaustion cells, with no multiple-testing adjustment.
- Cost omissions: fees, slippage, futures roll and short-borrow costs are never mentioned.
- Metrics with obvious problems:
  - Expectancy of 3.67, 10.75 or 11.5 with no unit given. If it is R-multiples or percent-per-trade, those are implausibly large for trend rules on liquid markets. A bug or a unit mismatch is possible. This is an inference, not stated in the video.
  - 563% return with a -41% drawdown is a single-cell headline.
- The AI judge:
  - The LLM includes a statistically significant but losing strategy in the top 10. When challenged, it concedes the point (the edge must be positive) [mOI4 @ 1:03:31-1:06:00]. This shows an LLM-written "score" is not a validation step.
  - It also reports "98.7 statistical confidence" and "80% edge persistence" with no stated test [mOI4 @ 1:02:16-1:02:55].
- Look-ahead is acknowledged only for the M2 idea (publication lag) [mOI4 @ 0:31:41-0:32:00]. It is not examined anywhere for the price strategies.
- "Edges don't persist forever" and "new anomalies all the time" [mOI4 @ 0:14:24, 0:44:14] are comments only; there is no decay test.

### Usable for our repo?

- Trend, breakout, Bollinger, MA-cross and gap rules are already covered by the failed strategy zoos and the DON8/EMA8/VOL8 trend work. Under the evidence-rate rule, new trend variants are not allowed, so nothing here is a candidate.
- Equity and futures breadth is a real direction for us in principle (ES, NQ, AAPL, TSLA, NVDA, GOOG are in his data pool), but his list is one mega-cap-tech factor, so it is not independent breadth. FX/index trend is already tested and failed. Nothing new here beyond "the harness ran over those tickers".
- Sellers exhaustion with open interest and volume is the one potentially new information source (open interest). No rule, no result is given, so there is nothing to test beyond a name. Our OKX liquidation-flow work is the closer relative.
- Global M2 -> BTC:
  - It is independent of price (macro information), and the lag warning is correct.
  - It is monthly, so the number of independent observations over a crypto history is tiny. It does not shorten time-to-answer, and "10-12 weeks lead" is an unverified viewer claim.
  - We could note it as a low-priority candidate only if framed as a pre-registered, lagged, single-parameter test. I would not recommend it given the sample size.
- Process: the multi-dataset runner and the "ask an LLM to rank" step are not worth adopting. The latter demonstrates a failure mode (a significant loser reaching the top 10).

---

## 3. "I Let 8 AI Trading Bots Trade for Me All Day"

- URL: https://www.youtube.com/watch?v=q2ugYN8eSeY (transcript file q2ugYN8eSeY.txt)
- Length: about 2h24 (last timestamp 2:24:02).
- Rough split: about 8% technical (0:00:00-0:03:45 and 0:06:00-0:13:30, plus a 20-second Q&A), about 85% marketing (Halloween bootcamp pre-sale, reading about 30 testimonials, writing 58 promotional posts, scheduling emails, a $5 Zoom/API-key pitch), about 7% chat and off-topic.

### Concrete ideas with timestamps

- Pipeline shape: his "RBI" loop (research, backtest, implement). An agent turns an idea from a text file into a description, another writes backtest code, and a queue runs them in parallel [q2ug @ 0:01:55-0:03:20].
- Code is `RBI agent PP multi` in his open-source repo [q2ug @ 0:02:50-0:03:10].
- "Always-on" mode, built live with Claude [q2ug @ 0:03:25-0:13:10]:
  - Polls the ideas file for new ideas (every 15 seconds, then he asks for 1 second) [q2ug @ 0:06:03-0:06:10, 0:07:28-0:07:35].
  - Producer-consumer queue, with 18 worker threads [q2ug @ 0:10:54-0:11:10].
  - The first version did not pick up an idea added mid-run (an edge case). It was patched and re-tested with a third and fourth idea [q2ug @ 0:09:45-0:13:05].
  - Inconsistency in the caption: "eight" agents in the title and opening, "six in each swarm, but there's eight" [0:08:38-0:08:45], and 18 worker threads later.
- Ideas queued are named only: "Carmine orderflow strat" and "Fabio orderflow strat" came from chat [q2ug @ 0:08:13, 0:09:17-0:09:25]. No rules, data, or results are given for either.
- Output metrics mentioned: return %, max drawdown, Sharpe, Sortino, EV. "Sharpe of four" is said once without naming a strategy [q2ug @ 0:06:17-0:06:28].
- Other uses of agents (marketing, not trading): a "customer success" agent that answers questions from a review database [q2ug @ 0:16:26-0:20:30]. No trading content.
- Bonus-day topics named but not shown: Monte Carlo and alpha-decay tests (day 22) [q2ug @ 1:20:41-1:21:00], and genetic algorithms or grammatical evolution that "self-create" strategies (day 29) [q2ug @ 1:21:54-1:22:20].
- Paid data pitch (not shown working): his API exposes Hyperliquid positions, Binance and Hyperliquid liquidations, and Polymarket data [q2ug @ 0:45:35-0:47:30, repeated through the video].
- A viewer asks about detecting red flags like liquidations after a tariff headline. He answers "Liquidations. Yes." with no method [q2ug @ 0:21:19-0:21:42].

### Reported numbers with timestamps

- None that are checkable. The only figure in the technical part is a passing "sharp of four" [q2ug @ 0:06:21].
- A viewer tweet claims one model's assets "doubled" and another "made 75%" in under 8 days [q2ug @ 2:16:03-2:16:12]. This is a third-party claim, with no source or record.
- He declines to show P&L: "my profits don't matter", "not going to flaunt profits" [q2ug @ 0:36:49-0:38:10, 0:40:22].
- Live trading: none shown. The title's "trade for me all day" refers to agents that build and backtest strategies. The transcript shows no order placed.

### What the title claim rests on

"8 AI trading bots trade for me" rests on 8 (or 18) worker threads running an LLM-driven research/backtest queue. Nothing trades. No fills, equity curve or account is shown, and he explicitly refuses to show profits. The agents are researching and backtesting ideas from a text file, not executing.

### Validation and overfitting observations

- No validation method is described. The backtest outputs are not displayed in readable form at any point in the technical segment.
- Throughput is the only claim. A pipeline that auto-runs every chat idea without a pre-registered grid or holdout amplifies multiple testing. The more ideas through the queue, the more "winners" by chance.
- His stated validation philosophy: "if it works in the past, it's much more likely to work in the future" [q2ug @ 0:57:43, 1:57:45]. That is the inverse of our standard.
- Monte Carlo and alpha-decay are named as the checks, but only as product features for the paid course.

### Usable for our repo?

- Strategy content: none.
- Technical segment: a queue/worker pattern for running many LLM-generated backtests. It would raise our throughput of strategy-zoo-style work, which is exactly what the evidence-rate rule says to stop. It does not shorten time-to-answer for a question that needs more independent data.
- The paid-API pitch (Hyperliquid positions, liquidations across venues) is the only data-related idea. Our OKX liquidation-flow collector is already running. The Hyperliquid venue check already failed. I found nothing in the transcript that is usable without paying.
- The one useful signal is negative: how not to run an ideas queue (no pre-registration, no cap on the number of ideas, no holdout).

---

## 4. "Moon Dev Ai Agents Github Walkthrough"

- URL: https://www.youtube.com/watch?v=RlqzkSgDKDc (transcript file RlqzkSgDKDc.txt)
- Length: about 4m57 (last timestamp 4:57).
- Rough split: about 85% technical (repo tour), about 10% self-promotion ("fastest growing GitHub in the world") and disclaimers, 5% other.

### Concrete ideas with timestamps

- Repo layout of "moon dev ai agents for trading": a `src` folder with `agents`, `models` and `data` plus helper scripts, a `.env` example, and docs [RlqzkSgDKDc @ 0:01:42-0:03:45].
- Live agents listed [RlqzkSgDKDc @ 0:00:16-0:01:00, 0:01:46-0:02:08]:
  - trading agent (LLM analyzes token data and decides), strategy agent (runs strategies from a strategies folder), risk agent;
  - copy and copybot agents, whale agent, sentiment agent, listing-arbitrage agent, focus agent;
  - funding agent and funding-arb agent, liquidation agent, chart-analysis agent;
  - backtest runner, coin-gecko agent, compliance agent, clips agent, chat agent.
  - These are named only; there are no rules or parameters in the transcript.
- Model layer: Claude, DeepSeek, Gemini, Grok, Ollama and OpenAI [RlqzkSgDKDc @ 0:03:15-0:03:30]. He says he will add the new Grok because of "chatter about Grock being a good trader", and that "DeepSeek looks like the best trader" [RlqzkSgDKDc @ 0:03:30-0:03:40].

### Reported numbers with timestamps

- None. No P&L, trade, return or backtest figure appears. The claim "fastest growing GitHub in the world until I made it private" [RlqzkSgDKDc @ 0:01:01] is a popularity claim, not a performance one.
- "DeepSeek looks like the best trader" has no data behind it in the transcript.
- Live trading: none.

### What the title claim rests on

The title is descriptive (a walkthrough), so there is no performance claim to test.

### Validation and overfitting observations

- Not applicable: no strategies are tested.
- The "LLM picks trades" framing (a trading agent that reads token data and decides) has no evidence in this transcript. Statements about which model is the "best trader" are anecdote.

### Usable for our repo?

- No. It is a tour of code that we are not going to run. The only research-relevant element is the list of agent concepts (funding, liquidation, whale, sentiment), and each is either already tested and failed (sentiment, funding carry) or already in progress (liquidation flow) in our repo.
- Any code from that repo would be unreviewed third-party trading code; the transcript gives no reason to import it.

---

## Overall judgment across the four videos

- Across 5h+ of transcript, the only quantitative strategy results are in video 1, with a small and uninterpretable set in video 2. Everything else is tooling or marketing.
- All performance figures are in-sample, max-selected from large grids, with no holdout and no costs stated. They cannot serve as priors for our pre-registered work.
- No video contains a live or paper result, and one (video 3) says explicitly that profits will not be shown.
- Three ideas have some surface fit to "independent information" (open interest as exhaustion, liquidations/positions on Hyperliquid, global M2). None comes with a rule, data, or result in the transcripts, so each would need full pre-registration from scratch, and the first two overlap work already in progress. The macro one is too slow to answer.
- Nothing here changes the repo's plan.

## Gaps

- Entry/exit timing conventions, commission, slippage and sample dates of the hour-scan are not stated in the transcript (only visible on-screen in the video).
- Per-strategy rules for the sellers-exhaustion and trending batches are not spoken; only names.
- Several captions are garbled around the key numbers (e.g. "3,92 back tests", "Turn 68.36", "36 out of 100", "Only two trades though. 141 trades"). Verify against the video if any figure is to be cited externally.
- Whether the "12,000" refers to some larger count not shown on screen cannot be determined from the transcript.
