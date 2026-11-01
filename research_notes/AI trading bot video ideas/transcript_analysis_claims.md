# Moon Dev short videos: procedure and evidence behind each performance claim

Scope: 14 local transcripts (channel "Moon Dev", all auto-captions). Source is the transcript only, cited as [video id h:mm:ss]. No outside verification except where a line is marked "(outside knowledge)". Caveats that apply to every video:

- Captions are speech-to-text. Numbers are sometimes garbled ("1230", "$927", "426/361"). I flag each place where the figure cannot be read with certainty.
- Every number is the creator's own screen read aloud. No video links a ledger, a trade file or a wallet that I could check. Treat all results as claims.
- Product and model names (Jev, Astra, Fable, GPT 5.6, Opus 5, Kimi K3) are taken as spoken. I cannot verify they exist as described.
- The repo's own "Jev layer" (CLAUDE.md) may or may not be the same thing as the "Jev AI" model discussed here. Do not assume they are related.

Repo filter used for every "Usable?" line: strict pre-registration, free data only, no live trading. Already failed: strategy zoos, Fear & Greed, Kronos, FX/index trend, regime diagnostics. Funding carry was a venue artifact. In progress: trend+momentum forward test, OKX liquidation flow, Hyperliquid check (failed). The evidence-rate rule bars new variants or diagnostics on the same 10 coins and on DON8/EMA8/VOL8. New work must add independent breadth or shorten time-to-answer.

---

## 1. "Andrej Karpathy's AI Trading Loop Found 44,975% (and it never stops)"
URL: https://www.youtube.com/watch?v=nroZBpr30vA | Length: ~10:15 (transcript ends mid-sentence) | Share: ~45% technical walkthrough of loop design, ~55% marketing (GitHub/lifetime access, "code is a great equalizer", code scrolled past too fast to read).

### Concrete ideas with timestamps
- Loop design. One agent edits only strategy.py. A frozen harness scores each try, a human-owned program.md steers, and results are logged to results.tsv. A kept change becomes the new champion; otherwise it is reverted [nroZ 0:01:39-0:03:00].
- Score. K = ln(1 + return) x Sharpe, as best the caption can be read [0:02:49]. Keep-or-revert with no middle ground.
- Each iteration copies the current best and builds a prompt from program.md, the baseline and the last 30 tries [0:03:02-0:03:17]. The agent makes one change and writes a one-line proposal.
- Harness guards [0:03:41-0:04:20]:
  - at least 50 trades;
  - a "leverage dial" guard: a try only counts if volatility barely moved, because bigger bets raise return and Sharpe on identical trades;
  - a locked window: the loop sees only 2017-2022, and 2023 onward is held out;
  - a separate morning.py runs the out-of-sample check once a day.
- Harness settings: ETH, 6h bars, 2017-2022, double fees "because of slippage", $10 million size [0:03:29, 0:08:57-0:09:04].
- His own admission: "1,000 tries on one window is 1,000 chances to curve fit" [0:04:23].

### Reported numbers with timestamps
- Best so far 44,975%, then 30,937%. Max drawdown 12.54, Sharpe 1.8, about 100 trades [0:00:16-0:00:56].
- Running 24/7 on Claude Code, with no API cost [0:00:21].

### Validation / overfitting observations
- Headline 44,975% is an in-sample number from the loop's leaderboard on the 2017-2022 window. No out-of-sample (morning.py) result is shown in this video.
- Not stated: leverage, iteration count (how many variants were tried before the winner), number of kept versus rejected tries, buy-and-hold comparison, and whether the 12.54 drawdown is on the same window.
- A 450x return with Sharpe 1.8 and 12.5% drawdown on 6 years of ETH implies heavy sizing or compounding. The vol guard only limits relative change versus the baseline, so a ratchet is possible (see video 4, 2 and 3).
- (outside knowledge, approximate) ETH rose roughly 100-150x from early 2017 to end 2022, so 44,975% is the same order of magnitude as a leveraged long-biased ETH hold, not evidence of timing skill.
- $10M size on a 6h ETH strategy with no stated market-impact model. The fee model (2x) is the only cost control mentioned.

### Usable for our repo?
- No for results.
- The design pattern is partly useful. A frozen harness, a trade-count floor, a leverage-neutrality guard and a held-out window sealed from the loop all match our pre-registration discipline.
- Running such a loop on single-asset OHLCV (ETH/BTC) breaches the evidence-rate rule.

---

## 2. "I Broke the Karpathy Loop with AI Trading (ROI vs Cost Result Is Insane)"
URL: https://www.youtube.com/watch?v=rm9arc2t5Xc | Length: ~22:00 | Share: ~65% technical (post-mortem of the loop is the most informative of the Karpathy videos), ~35% marketing, mostly the RBI pitch and book list.

### Concrete ideas with timestamps
- "Leverage is banned" in program.md so returns cannot be bought with size [rm9a 0:03:06].
- Loop stats: 23 hours, 140 iterations, 59 kept, 81 rejected [0:03:48]. Over 3 nights the iteration counter reached about 256, with a stall at 230 [0:08:55-0:09:12, 0:11:50-0:12:10].
- Diagnosis by the agent [0:04:18-0:04:40, 0:09:03-0:10:00]:
  - the score rose 5.5x (10.24 to 63.46), but almost none of it was money;
  - the gain came from "grinding" one number, the single worst in-sample dip, from -7% to -1.7% ("memorize where that dip was");
  - proposed fix: score on Ulcer index instead of max drawdown, and put a return floor.
- Out-of-sample read-out: the in-sample leaderboard ranking is inverted relative to out-of-sample [0:08:30-0:08:40].
- Cost wall and stall: iterations are about 10 min each; productive windows were iterations 19-94 (night 1) and 160-230 (night 2). After that the loop only re-scored noise [0:11:40-0:12:20].
- Proposed fixes [0:12:20-0:13:50]:
  - auto-stop when the best score moves less than 1% in 25 iterations;
  - run the agent on Sonnet, not Opus;
  - run 12-hour sprints from different seeds;
  - stop ranking by in-sample alone;
  - kill criterion: three restructured sprints (~$50) must beat the iteration-160 out-of-sample result at 60 bp, or the loop is dropped.
- Comparison with his old grammatical-evolution (GE) system [0:14:00-0:17:30]:
  - GE ran 100,000 evaluations and 153 scripts with 8 overfitting fixes; the top results were identical or "always long";
  - the Claude loop ran 336x less search and found something that survived once;
  - the agent's diagnosis: both optimise an in-sample number and lack out-of-sample inside the fitness function. Fix: put walk-forward inside the fitness.

### Reported numbers with timestamps
- Top in-sample strategy: 75.69% ROI, drawdown 1.27% in sample. Out of sample: ~12% ROI, drawdown 6.77% [0:08:11-0:08:30]. Other top-10 rows: 80% ROI with drawdown 1.27 in sample, and out-of-sample ROI of "13 and then nine" [0:06:58-0:07:10].
- Out-of-sample dip is still 9.59% versus 1.7% in sample [0:04:00].
- Out-of-sample: night 1 produced a strategy that makes money out of sample on 4 of 4 coins at 10 bp and 3 of 4 at 60 bp. Night 2 improved drawdown by 12% but "broke BTC" and added zero return [0:11:21-0:11:45].
- BTC flipped from winner to loser; XRP improved materially; drawdown improved on 3 of 4 coins [0:08:55-0:09:00].
- Cost: 75% of a $200 Claude Code plan in 3 days, on a temporary 50% limit boost, about $200 of plan value [0:10:15-0:10:30]. GE cost "a few thousand" dollars on Lambda GPUs (8x A100, about $14/hr) [0:17:45, 0:21:19-0:21:25].
- Decision: the creator kills the Karpathy loop and returns to RBI (idea research, backtest, small-size incubation) [0:21:51].

### Validation / overfitting observations
- This is the only video where out-of-sample is actually shown, and it shows a large collapse: ROI 75% to 12%, drawdown 1.27% to 6.77%. In-sample rank inverted out of sample.
- Objective hacking is documented: sanding one drawdown point; the score is a ratio, so a single point drives it; the earlier K-based loop bought leverage.
- Selection bias is explicit: 140 to 256 tries, with "kept" decided on the same in-sample window.
- The OOS "success" (4/4 coins at 10 bp) is still one OOS window, on 4 coins that share the crypto factor, and comes with no variant count.
- Costs: the out-of-sample check was run at 10 bp and 60 bp round trip; the profit disappears at some cost level (see video 4: zero at 108 bp).

### Usable for our repo?
- Lessons yes, loop no.
- The anti-gaming checklist is directly reusable for any automated-search tooling we build: a ratio objective can be gamed at one point; never rank on the in-sample score; stop on stall; cost-sweep out of sample.
- Walk-forward inside the fitness function is aligned with our approach, but any loop over the same crypto OHLCV is excluded by the evidence-rate rule.

---

## 3. "Andrej Karpathy's AI Trading Loop On Secret Data (Nobody Is Talking About It)"
URL: https://www.youtube.com/watch?v=l0fthd71hOE | Length: ~13:20 | Share: ~35% technical, ~65% marketing and repetition of the RBI pitch.

### Concrete ideas with timestamps
- Pitch: feed liquidation data (collected "for 2 years") into the same loop; claimed edge is that most traders only use OHLCV [l0ft 0:00:38-0:01:00, 0:10:44-0:11:00].
- Bug found by the agent when first building it [0:11:51-0:12:20]:
  - the score for a losing strategy can be positive, because two negatives multiply;
  - a full-sample threshold is look-ahead.
- Honest seed signal [0:11:57-0:12:25]: go long on the next ETH open when the whole tape's long-liquidation notional crosses the top 3% of its own trailing 30 days. In sample +19%, out of sample about -4% (caption: "plus minus4").
- Baseline frozen at K = 0.193 [0:12:26].
- Always-use-double-fees rule restated [0:08:48].

### Reported numbers with timestamps
- 87,000%, 81,000%, 93,000% (Sharpe 1.76, one "rejected") and 82,353 shown on the old (OHLCV) loop's leaderboard [0:00:31-0:00:44, 0:02:20]. These are old-loop, in-sample results, and he says "maybe a little overfit".
- Pre-fix screen: "median tracks 60-70% hit rate, spread over 11-12 months" [0:05:50]. This was said before the look-ahead threshold was identified, so it should be discounted.
- No result from the liquidation loop itself is shown. He starts the run at the end [0:13:08-0:13:15].

### Validation / overfitting observations
- The only liquidation-based evidence is the agent's own look-ahead warning and an honest seed that fails out of sample (+19% in sample, -4% out of sample).
- Claims of an "edge" because the data is rare are a statement about availability, not about predictive value.
- The data source, exchange, coverage and timestamp alignment are never described.

### Usable for our repo?
- Partly, as a checklist. We already collect OKX liquidation flow, which is in progress. The look-ahead pitfall (a full-sample percentile threshold) and the sign-bug are worth confirming are impossible in our harness.
- His seed (long-liquidation notional in the top 3% of its own trailing 30 days, next-open entry) is an example of a rolling-threshold, causal design, and it already failed out of sample in his hands. Do not tune it after viewing our data.

---

## 4. "Karpathy Loop Made Trading Bots Do WHAT in 24 Hours (ROI & Cost Revealed)"
URL: https://www.youtube.com/watch?v=b70or37mSfg | Length: ~25:25 (a ~5-minute muted gap around 0:18-0:23) | Share: ~40% technical, ~60% filler, code scrolling and RBI pitch.

### Concrete ideas with timestamps
- One 24h run: 158 iterations scored, 112 kept; K moved 0.15 to 4.16. The agent's verdict: every keeper is the same strategy with the size dial turned up, and the last 64 iterations bought return with leverage, not edge [b70o 0:10:43-0:11:00].
- The ratchet: the annualised-volatility guard allows +10% of the current baseline each step, so size can creep up indefinitely [0:11:47-0:12:00].
- Cost wall: out-of-sample ROI hits zero at 108 bp round trip [0:12:26]. Out-of-sample Sharpe turned positive only at iteration 73 [0:12:07-0:12:16].
- Fee setting confusion: fee comment says 0.0003 ("triple"); he asks to fix to 0.001 [0:12:40-0:13:55]. The agent recommends shipping iteration 149, not 158 [0:12:48-0:13:05].
- The whole night ran on the wrong Python environment (a path issue) [0:06:11-0:06:20]. It is unclear whether this invalidates the results; he treats it as fine.
- Re-spec: optimise ROI over drawdown, forbid leverage, run on BTC/ETH/SOL/XRP, resume from iteration 160 [0:13:55, 0:16:00, 0:23:30-0:24:50].
- Philosophy: stack uncorrelated strategies (trend plus mean reversion) to smooth P&L [0:16:23-0:16:50].

### Reported numbers with timestamps
- Winner: 187% ROI, Sharpe 3.94, drawdown 12.30% (caption "1230"), versus buy-and-hold ETH (figure garbled) [0:11:05-0:11:20].
- Usage: 49% of the $200 plan in 24h [0:01:55-0:02:00].
- "the 150%ish, not as crazy as before and they probably are overfit" [0:14:58-0:15:05].

### Validation / overfitting observations
- Selection: 158 edits scored, best of the kept chosen on in-sample. The agent itself states the improvement is leverage, not edge.
- Out-of-sample positive only after 73 iterations and dead at 108 bp. That leaves a thin margin over costs, and no OOS ROI is given.
- When asked about p-hacking, he concedes "all this is overfitting" [0:14:08-0:14:15] and relies on small-size live incubation as the remedy.
- A "5-minute" audience question about multiple testing is dismissed without a correction.

### Usable for our repo?
- No for results. The cost-wall concept (the cost level at which out-of-sample P&L reaches zero) is a good single-number summary that fits time-to-answer; we likely already report cost sensitivity.

---

## 5. "i let ai actually trade for me for 60 days (here are the results)"
URL: https://www.youtube.com/watch?v=RZhiYZFyDx0 | Length: ~10:20 | Share: ~40% technical (results and fees), ~60% chatter, plugs and community news.

### Concrete ideas with timestamps
- Setup: models GPT 5.6, Grok 4.5, Opus 5, Kimi K3, Gemini 3.1 and DeepSeek, started July 24, same data and prompt, built on Hyperliquid, open source [RZhi 0:00:05-0:00:25, 0:01:34-0:01:50].
- Every hour each model gets the option to trade; the creator says this caused over-trading [0:05:15-0:05:30, 0:07:20].
- Orders were limit orders [0:04:42].
- Conclusion: AI cannot just say long or short, but is useful for coding backtests and agent loops [0:08:49-0:10:20].

### Reported numbers with timestamps
- OpenAI "won" at +0.15% (caption "one, 0.15%") after about 60 days. Elsewhere in the same video, about 1% up [0:00:41, 0:03:45]. Reported as a caveat-laden win.
- All except DeepSeek had been in profit by August 29. The first month was straight down [0:00:55-0:01:06].
- Buy and hold from July 24 would have been about +33% (BTC, as stated "at 33%") [0:03:49-0:03:55].
- Fees: the profitable ones paid about $13 on a $100 account (13%) [0:04:27-0:04:36]. The best at not trading (xAI/"X") paid about $7 [0:07:28].
- Fee-calculator claim: $25,000 account, 40x leverage, five trades a day loses everything to fees in 31 days; a patient bot "gains 717 days" [0:04:45-0:05:12]. The inputs (fee rate, trade size, round trip) are not shown, so I cannot reproduce it.
- Models appear to be better at long than at short ("better at longing than shorting") [0:01:20-0:01:30].

### Validation / overfitting observations
- N = 1 path, one asset (BTC), one regime (a rising market), 6 models. "Better at longing" is an attribution of beta, not skill: in an up-trend any long bias wins.
- The final standings are within noise of zero (+0.15%), while they underperformed buy-and-hold by about 33 points.
- Capital: $100 per model, a hugely small account. The $13 of fees on $100 implies turnover that no small account would sustain in real trading; the lesson that fees dominate is plausible.
- "I know there's edge in this data. I know it for a fact" [0:06:55-0:07:00] is an unsupported assertion about his dataset of model trades.
- Internal inconsistency: the "60 days" is a rolling label. By dates (Jul 24 to the sources' Sept 9/16) it is 47-54 days. Series: +1.7% (Sep 9, video 7), -4.1% (Sep 16, video 6), +0.15% (this video, later). Swings of 4-6 points in a week.

### Usable for our repo?
- Partly: it is evidence that hourly LLM discretion loses to fees, which is not a hypothesis we pursue. No usable dataset has been released (only claimed). Skip.

---

## 6. "I Let the World's Top 6 AIs Trade My Money For 48 Days..."
URL: https://www.youtube.com/watch?v=2S2C5MYPXCs | Length: ~11:35 | Share: ~75% technical (rules and results), ~25% marketing.

### Concrete ideas with timestamps
- Rules [2S2C 0:00:36-0:02:00]:
  - six models, $100 each, one asset (BTC);
  - one decision per hour: long, short or nothing; they see current position and can close or hold;
  - zero human intervention;
  - 55 identical data fields: price, candles, some tick data, order flow, Hyperliquid and other-exchange liquidations, and position/liquidation maps.
- Six real wallets on Hyperliquid, public addresses [0:02:04-0:02:20].
- Hypothesis from results: models lose on shorts; test a long-only variant [0:07:56-0:08:30].

### Reported numbers with timestamps
- Day 1: every model down (fees) [0:03:55-0:04:10]. Google first above $100 on Aug 6 [0:04:13-0:04:25].
- OpenAI peak $108 on Aug 29 [0:05:26-0:05:50]. Widest OpenAI-to-DeepSeek gap $19 on Aug 31 [0:06:06-0:06:18].
- By Sep 13 DeepSeek -19% [0:07:03].
- Final standings, Sep 16: OpenAI -4.1%, xAI -4.3%, Anthropic -6.5%, Google about -11%, Moonshot -13%, DeepSeek -16.1% [0:08:49-0:09:12].
- Fees: xAI $5.38 on a $96 account; OpenAI nearly $11. He says both "would be profitable" without fees [0:10:12-0:10:36].
- The headline "48 days" does not match the dates: July 24 to Sept 16 is 54 days.

### Validation / overfitting observations
- Real money but tiny ($100 per model), one path, and rank order among 6 models over a few weeks is noise: the leader changed within the window (Google, then OpenAI), and the leader was down at the end.
- The "profitable without fees" counterfactual is arithmetic only. It assumes the same trades with zero cost, which is impossible for a policy that trades for small gross edges.
- No benchmark is given in this video (buy-and-hold was +33% from video 5).
- Prompt, temperature and the exact 55 fields are not given, and there is no leverage or position-size cap in the description. Tick and liquidation fields were supplied, yet the outcome is a loss, which weakly suggests that data availability alone is not an edge.

### Usable for our repo?
- Not as a source of edge. One take-away: gross edge versus fee on small notional. Nothing here is free data we can pre-register against (the 6 wallets are public on-chain, so the trades could in principle be read, but that is a study of LLM behaviour, not of markets).

---

## 7. "AI Trading Works (You are just doing it wrong)"
URL: https://www.youtube.com/watch?v=6AiGNWM8Obo | Length: ~25:30 | Share: ~10% technical, ~90% motivational marketing and personal story.

### Concrete ideas with timestamps
- RBI process: research (books, papers, podcasts), backtest to kill ideas, incubate at $10 size on Hyperliquid [6AiG 0:03:55-0:05:05, 0:07:30-0:08:20].
- Free data: Coinbase offers unlimited free history; test many timeframes and symbols [0:06:59-0:07:05].
- Robustness heuristic: look for "bubbles"/plateaus where nearby parameters (3%, 4%) still work [0:07:05-0:07:30].
- Hit-rate framing: roughly 10% of ideas work in the past and a couple of those in the future; a user whose 1 in 10 tests worked was told that is a great rate [0:09:50-0:10:15, 0:11:31-0:11:40].
- Layer uncorrelated strategies (trend plus mean reversion) [0:23:25-0:23:55].
- Fee mechanics: Hyperliquid taker 0.045% versus maker 0.015%; fees are charged on the notional, not the margin [0:17:05-0:18:25].

### Reported numbers with timestamps
- AI arena at Sep 9: OpenAI +1.7%, the rest down [0:02:48-0:02:55].
- Later slide: OpenAI +1.3%, with fees paid of $9.27 (caption "$927") and gross P&L of about $1.32 (caption "$132") [0:15:55-0:16:25]. Elsewhere "up 6% but paid 6% in fees" [0:16:34]. The transcript units are garbled, so I treat the $9 fee figure as the more likely.
- "5 out of 6 got profitable" at one point and then "not profitable" days later [0:14:55-0:15:15].
- Anecdote: a trader doing $1B/day with a max position of $1,000 [0:22:54-0:23:15]. Unverifiable.
- "AI can't just trade for you", yet "AI sped up the coding" [0:18:59-0:19:20].

### Validation / overfitting observations
- Nothing new is tested. The idea of parameter plateaus is a standard robustness check; the 1-in-10 hit-rate is acknowledged but there is no multiple-testing correction.
- The "incubation at $10" step cannot detect a small edge in a feasible time (no sample size or power calculation is mentioned).

### Usable for our repo?
- No new content. Our pre-registration is stricter than RBI.

---

## 8. "Most Traders Looks At The Wrong Data (thats why they lose)"
URL: https://www.youtube.com/watch?v=0OdEqSaPFfA | Length: ~7:20 | Share: ~60% technical, ~40% marketing.

### The "wrong data" and the recommendation
- Wrong data = candles (OHLCV). A candle discards order, timing, size and venue. Recommended = tick data (one trade with time, size, venue) [0OdE 0:00:18-0:00:55].
- Main argument: in a bar backtest with a stop and a target inside the same bar, you cannot know which was hit first, and the bar test "usually guesses in your favor" [0:02:36-0:02:57].

### Concrete ideas with timestamps
- Free crypto ticks from Binance and Bybit, no API key needed, back to 2017; he downloaded 136 GB (he also says "100 GB") [0:03:30-0:03:58]. (Outside knowledge: Binance's public data dump and Bybit's public trade archive host these.)
- Stock ticks cost money: $150 for Tesla ticks from Databento, with a free price-quote before download [0:04:10-0:04:20, 0:06:30-0:07:00].
- Illustrative numbers: 80% of Tesla volume in the Nasdaq feed printed off-exchange; 41% of trades add zero shares to a volume bar [0:01:35-0:01:55].
- Fill realism: 9.2 bp on bars versus 3.3 bp on ticks for the "honest fill"; a "retail flow" setup gave +13.6 on 1-minute bars versus -13 out of sample on ticks [0:02:12-0:02:30].
- Another Tesla setup showed +13% on bars and has not yet been tested on the paid ticks [0:05:00-0:05:15].

### Validation / overfitting observations
- The tick-versus-bar illustrations are single examples, with units unclear (bp, %), no description of the strategy, no sample size, and no statement that the tick result is a different out-of-sample window (it may be a different period).
- The "retail flow" +13.6 to -13 swing reads like in-sample versus out-of-sample plus fill model at once, so the cause cannot be separated.
- The core claim (bar backtests with intrabar order ambiguity flatter results) is well known and plausible.

### Usable for our repo?
- Fill modelling matters for any orderflow work. Free crypto tick data is accessible, which fits "free data only", and it could shorten the time to detect an artefact (a signal that dies when intrabar order is resolved).
- It adds no independent information by itself and does not add breadth: it re-examines the same assets. Use only as a cost/fill realism audit for something already pre-registered, not as a source of a new strategy.

---

## 9. "Tori Trades made $526,454 off this Trading Strategy (AI actually tested it)"
URL: https://www.youtube.com/watch?v=qcGwneLU0nM | Length: ~13:00 | Share: ~50% technical (rules from the source video plus agent results), ~50% commentary.

### Strategy rules (as described by the third party, spoken in the clip)
- Draw trend lines top-down, subjective [qcGw 0:01:08-0:02:00, 0:03:12].
- Action line = the trend line broken. Entry in the direction of the break: break of an up-trend line means short; break of a down-trend line means long [0:02:20-0:03:00].
- Safety line = the opposing trend line. Stay in the trade while price respects it; close when it is violated. The stop sits beyond the safety line and trails along it [0:03:23-0:04:10, 0:07:25-0:08:00].
- Risk 1-2% of capital per trade; position size is discretionary [0:06:10-0:07:20].
- She says there are optional filters and "playbooks" not specified. Line placement is not defined algorithmically.

### The test (Moon Dev, three AI agents, run live)
- The agents interpreted the rules their own way, because the lines are subjective [0:02:49-0:03:20]. Gemini was used to extract the full strategy text [0:09:23].
- Results read aloud [0:05:56-0:12:55]:
  - "safety-line trend" backtest: exposure 27%, return 10% versus buy-and-hold -39% to -40% ("solid");
  - tick bars: return 0% versus buy-and-hold -44%;
  - liquidation variant: 101% versus buy-and-hold 311%;
  - XRP out of sample: 50% exposure, return 10%;
  - fleet of 16 sources: BTC -61%, Apple 15m -25%; 12 years versus 3 years, BTC 15%;
  - agent rating 3/10: "no edge" for shorts, which "only lose less than a random short";
  - "full system, boring strategy" 4/10: XRP Sharpe 0.93, Sortino 3.27, out-of-sample return 68% versus buy-and-hold -4% [0:12:20-0:12:55].

### Reported numbers with timestamps
- $526,454 profit is the third party's claim in the title and 0:00:01-0:00:07. No evidence is shown, and the video never ties that profit to the rules.

### Validation / overfitting observations
- The claim is unverified. The "AI test" is not a test of her strategy: the agents invented line-drawing rules.
- Many variants (about 16 sources, multiple data types, tick bars, liquidation data, various assets and horizons) were run, then the best were highlighted (XRP out of sample +68%). That is selection after the fact, with no variant count, no correction and no pre-registered pass/fail.
- "Beats buy-and-hold" in a falling market is treated as success. Low exposure (27%) will beat a market that falls 40%, so that proves little.
- Mixed results (BTC -61%, Apple -25%) are mentioned and then ignored.

### Usable for our repo?
- No. Trend-line breaks are discretionary and map to our failed breakout/trend zoo. The workflow (agents turning a YouTube strategy into code) is a pipeline for generating the very strategy zoos that have failed.

---

## 10. "I Let 114,000 Strangers Control My Polymarket 5 Min Bot (58% Win Rate)"
URL: https://www.youtube.com/watch?v=W-7EuAhY1q8 | Length: ~12:00 | Share: ~55% technical (rules, stats, code scroll), ~45% chatter.

### Bot rules
- Polymarket opens a BTC up/down market every 5 minutes (288 per day) [W-7E 0:02:02, 0:10:55].
- Chat votes "up" or "down" for the first ~3 minutes. One vote per person, can flip, no spamming [0:02:20-0:04:15].
- Majority wins (three ups to one down gives up); ties do nothing; minimum votes = 1 (code) [0:02:29-0:02:36, 0:09:14-0:09:20].
- Bot buys $5 of the chosen side with a limit order, holds to expiry, no stop and no exit [0:02:50-0:03:15, 0:05:00-0:05:10].
- Planned: an AI veto/weighting layer, not turned on [0:07:55-0:08:40, 0:10:15-0:10:25].

### Sample and numbers with timestamps
- 230 rounds: 146 with no votes, 11 order errors, 7 ties, 5 with no ask, 3 with no fills, 58 trades (sums to 230) [0:03:55-0:04:55].
- Win rate 58.3% [0:06:24]. Average win 3.61 and average loss 4.26 (caption "426/361", read as dollars on $5 bets) [0:06:05-0:06:12].
- Best trade +$23 on $5 at 17 cents (trade 9), early in the run [0:04:50-0:05:40].
- One account, "52 edit", cast 60 of 116 votes (51.7%), with a record of 45 wins and 15 losses [0:02:40, 0:07:45-0:07:55].
- "$28 was never real": one line in the scoring counted a missing fill as free money [0:05:10-0:05:20].
- Chat learned to vote the favourite above 90 cents for a near-certain small win, with 10% wins and 100% losses; he describes slot-machine payoffs [0:06:30-0:07:10].
- He says the bot "lost money at the end of the day" [0:10:05-0:10:15] and that a real test needs about 1,000 trades [0:07:30-0:07:50].
- The title's "114,000 strangers" is his audience, not the number of voters.

### Validation / overfitting observations
- Internal inconsistency. A 58.3% win rate with average win 3.61 and average loss 4.26 gives about +$0.33 per trade (about +$19 over 58 trades), which contradicts the reported net loss. Either the 58.3% belongs to voters' votes (116) rather than executed trades, the averages are misread, or the P&L includes fees or unfilled orders. Cannot be resolved from the transcript. Also 58 trades at 58.3% is not an integer count (33.8 wins).
- Mostly one person's picks, so this is not "wisdom of the crowd".
- Favourite-heavy entries create a high win rate with negative expectancy. That is the standard structure of binary markets priced near the odds.
- "58% win rate" is not a performance statistic; net P&L is a loss.
- Effective leverage "3,000x" is a turnover calculation, not risk-relevant.

### Usable for our repo?
- No. 5-minute Polymarket BTC markets are the same BTC factor and are settled on Chainlink (see video 11). The break-even-versus-win-rate framing (price is the breakeven probability) is a useful reminder for any binary-contract work. No free data or labelled dataset is provided.

---

## 11. "JevAstraFable AI Traded Polymarket 5 Minute Markets for 24 hours"
URL: https://www.youtube.com/watch?v=KJDZGywdfZI | Length: ~11:55 | Share: ~65% technical (design and breakdown), ~35% live chatter.

### Concrete ideas with timestamps
- Three models ("Jev", "Astra" from OpenAI, "Fable 5.1") see the same inputs: 288 five-minute bars, strike, TWAP so far, volatility numbers, order book, "liquidation fuel", and others' positions via his API [KJDZ 0:02:00-0:02:50].
- Each outputs up, down or nothing. If two of three agree, one $5 trade goes on that side [0:02:55-0:03:15].
- Shadow trader: every model is scored on paper on its own call regardless of consensus. Shadow books never paid a spread [0:03:48-0:04:10, 0:10:40-0:10:50].
- Decision time moved from the first 15s to 150s of the window [0:05:35-0:05:55].
- Settlement note: markets resolve on Chainlink, not Binance, and he suspects a rolling-average close. Price-source mismatch risk [0:04:15-0:04:50, 0:05:20-0:05:35].

### Reported numbers with timestamps
- 60 windows, 25 trades, 10 wins (40% hit rate), profit $27 or 23% of money spent. Average entry 0.34, so breakeven is 34%; the 6-point gap is "the entire profit" [0:05:58-0:06:58].
- The equity curve reached +$45 and gave it all back, then one ticket saved the day [0:07:00-0:07:25].
- Shadow hit rates: Jev 71% (return 13%), Fable 39%, Astra 31% (return 35%) [0:07:50-0:08:45]. Astra's average entry 0.29. The least accurate model made the most money by buying long shots.
- One 13-cent ticket returned 669%. "One ticket is 121% of the profit", so excluding it the run loses [0:08:50-0:08:55, 0:10:44-0:10:50].
- Agreement split: 3 of 3 agreed: 17 trades, profit $16, average entry 41c. 2 of 3 agreed: 25% win rate, profit $11, average entry 20c [0:09:15-0:09:55].
- Costs: Jev 1.5 cents for the day, Fable $3.72, Astra $2.64. Latency 475 ms versus 5,460 ms versus 10,942 ms [0:10:03-0:10:35].
- The creator: "25 trades is not a study", and "I haven't cracked these markets" [0:10:44, 0:12:40-0:12:50 approx].

### Validation / overfitting observations
- n = 25 trades and 60 windows in about one day. A 40% versus 34% hit-rate gap on 25 trades is not significant (binomial standard error is about 10 points).
- The result is carried by a single 669% ticket. Cheap-side (long-shot) entries produce high variance and positive P&L from a few hits.
- The decision time was changed mid-experiment (15s to 150s). That is a parameter choice after seeing too few trades, and the sample mixes regimes.
- By 150 seconds the price already reflects the move so far, so a "prediction" near the end of the window is partly a continuation of known information. Entry price embeds that. The experiment cannot separate skill from pricing.
- Shadow books ignore spread and fill failures; the live $5 trades omit these as well (the "basis" is an estimate).

### Usable for our repo?
- No. Same BTC factor, tiny sample, price-source mismatch.
- The break-even logic (hit rate versus average entry price) is the right way to read a binary book; keep it for any prediction-market work.

---

## 12. "I Tried JEV AI on Polymarket 5 Minute Markets (Felt Like Cheating Incorrectly)"
URL: https://www.youtube.com/watch?v=EpVAJG3EF5s | Length: ~6:40 | Share: ~30% technical, ~70% live commentary and community plug.

### Concrete ideas with timestamps
- Adds Jev to an existing 5-minute bot via OpenRouter, with an "AI 5-minute core" module [EpVA 0:01:00, 0:03:50-0:04:50].
- Base bot variants he lists as already existing in his roadmap: weather scanner, "95 cent bid sniper", CVD bot [0:02:50-0:03:10]. No results are given for them.
- Pitch: Jev is the faster/cheaper "system one" model; a test earlier that day cost "$1,500 for Astra, $5 for Jev" [0:00:34-0:00:42].

### Reported numbers with timestamps
- Jev lost its first trade, then took a second loss; "down 97%" at 0:05:06 (unclear whether account, token or a trade). He plans about 10 trades [0:05:00-0:06:10]. Effective leverage "5,000x" [0:06:29].

### Validation / overfitting observations
- Two or three trades; no evidence. He says explicitly that faster and cheaper does not mean an edge [0:04:35-0:04:48].

### Usable for our repo?
- No.

---

## 13. "Jev AI just changed Trading Forever (way better than gpt-6 astra & Fable)"
URL: https://www.youtube.com/watch?v=cV6pxlXgCv8 | Length: ~13:10 | Share: ~25% technical (model properties), ~75% marketing (about 4 minutes of sales copy for his paid community).

### Concrete ideas with timestamps
- Jev is described as a one-forward-pass classifier ("system one") with fixed answer shapes (yes/no, score 0 to 1, choice), no output parsing, up to six questions answered in one request [cV6p 0:00:05-0:02:30].
- Claim: calibrated scores ("when it says 80% it is right about 80%") [0:02:41-0:03:10].
- Pricing and speed as stated: input $0.042 per million tokens versus $10 for Astra; output free versus $50; latency 70-500 ms versus seconds; context 32K versus 1M; 5.43x faster and 238x cheaper on input [0:03:05-0:03:55].
- Accuracy 67.8% versus GPT 5.6 74.1% and Opus 73.1% (benchmark not named) [0:04:00-0:04:12].
- Application: a rug-pull gate for his token sniper, because a token fell 90.8% in 16 seconds. Deploy in shadow mode (buy nothing, settle against its own data) for a week of paired decisions [0:08:40-0:11:30].
- Cautions he gives: it cannot count or do date math, so hand it computed numbers; "a classifier is not an edge" [0:09:25-0:10:10].
- Sales segment: paid Zoom community, API key, roadmap, 90-day money-back guarantee [0:05:55-0:08:10].

### Validation / overfitting observations
- Vendor-level numbers are not independently supported. The calibration claim is contradicted by the creator's own later test (video 14: confidence flat or slightly inverted on price bars).
- "Offit study" of 199 tokens, said to show that pre-buy signals are noise (caption garbled), is mentioned without detail [0:10:30-0:10:40].

### Usable for our repo?
- No. Shadow-mode as a promotion path (log paired decisions, no money) is consistent with our no-live rule, but it is a generic idea. Do not add LLM classifiers on prices.

---

## 14. "I Let JEV AI Predict Stock Prices and the Result Were Not Hard to Believe"
URL: https://www.youtube.com/watch?v=_N15W3X-8rM | Length: ~12:35 | Share: ~85% technical, ~15% code walkthrough. Best methodology content in the set.

### Procedure (as described)
- About 44,000-45,000 calls, 42 minutes, $4.95 on OpenRouter (hard cap $5); he states the equivalent would be $1,356 with Astra [_N15 0:00:55-0:02:05, 0:04:25-0:05:15]. He first says "BTC price on 5 years of data" [0:01:50] but the tests listed are HOOD (Robinhood), COIN (Coinbase) and QQQ, with data from Databento (~$2) [0:02:05-0:02:15, 0:12:15-0:12:30]. The asset description is therefore inconsistent.
- Prompt: 46 hours of bars, return one word (buy, sell or nothing), told to say nothing unless the chart gives a reason [0:02:05-0:02:30, 0:03:20-0:03:40].
- Three framings: named (ticker and date visible), blind (ticker and date stripped), scaled (prices rescaled) [0:02:45-0:03:10].

### Reported numbers with timestamps
- Acted 19% / 15% / 12% of the time by framing; about 4 of 5 answers were "nothing" [0:03:08-0:03:25].
- Early false positive at 2,396 calls: scaled HOOD +10.1% (p = 0.045) and QQQ +21% (p = 0.02) on 32 trades (22 right). With 535 trades it fell to 0.9% [0:05:16-0:06:15]. The "next bar up" base rate was 38.3% in that sample, so the apparent edge was luck [0:06:33-0:06:40].
- Action-matched null (same count of buys and sells scored against the real base rate). All 95% intervals straddle zero. Hit rates 50.0% (2,812 trades, named), 48.8% (2,184, blind), 50.5% (1,905, scaled) [0:06:40-0:07:10].
- Per symbol accuracy: COIN 50.7%, HOOD 46.6%, QQQ 49.9% [0:07:10-0:07:20].
- Six tests at 0.05 is expected to give about one false positive; the Benjamini-Hochberg threshold for HOOD was .0083 versus its raw p = .0387, and the sign was negative. "Nothing survives" [0:07:22-0:08:00].
- Contamination test: named beat blind on 97.7% of 14,828 paired windows for "recognition" (0.789 versus 0.288 on a 0-1 scale), but edge over the null stayed within -4% to +4% (-1% blind, +0.7% named). Conclusion: dating a backtest card inflates conviction, not the equity curve [0:08:00-0:08:45].
- Calibration: probability buckets are flat and slightly inverted, so higher confidence is slightly more wrong. The gate's arm threshold of 0.6 was set assuming the number meant something [0:08:45-0:09:25].
- Baselines: random forest on HOOD daily bars, 871 out-of-sample days, AUC 0.49; logistic regression 0.499. His own "bar" from CLAUDE.md is 0.65 (unverified) [0:09:30-0:10:15]. Verdict: the data is the problem, not the model.

### Validation / overfitting observations (positive ones, which we can learn from)
- Explicit control for peeking: his own demonstration that an early look at 2,396 calls produced two p < 0.05 results which vanished with more data.
- Multiple-testing correction (Benjamini-Hochberg) applied across six tests.
- Action-matched null rather than a 50% null.
- Identity-masking test for LLM memorisation or leakage (ticker and date).
- Free ML baseline run alongside.
- Remaining weaknesses: only three symbols; all 2020s equities; pricing, latency and payoffs not in scope.
- 45,000 calls over about 15,000 windows is not 45,000 independent samples.

### Usable for our repo?
- Yes for method, no for the model. Four reusable checks fit our pre-registration culture directly:
  - an action-matched null;
  - Benjamini-Hochberg across the pre-registered tests;
  - a "named versus blind" leakage test for any LLM that touches research;
  - a stop rule that prevents interim peeking.
- LLM price prediction is not worth pursuing: it adds no information, and it overlaps with the Kronos result.

---

## Cross-video summary table

| Claim | What it actually rests on | Credible? |
|---|---|---|
| 44,975% return from the Karpathy loop (v1) | In-sample best on ETH 6h 2017-2022 after an unstated number of tries; no OOS shown; leverage and sizing unstated; $10M notional | No |
| 87,000-93,000% (v3) | Old loop leaderboard, in sample only; he says "maybe a little overfit" | No |
| 187% ROI, Sharpe 3.94 (v4) | Best of 158 iterations; agent says it is the same strategy with the size dial turned up; OOS Sharpe positive only after iteration 73; OOS ROI zero at 108 bp | No |
| Loop improved the strategy (v2) | Score up 5.5x by sanding one in-sample dip; OOS ROI collapsed from ~75% to ~12%; rank inverted OOS; night 1 OOS positive on 4/4 coins at 10 bp (one window, correlated coins) | Unclear, mostly no |
| Liquidation data is an edge (v3) | Two years of collected data; an honest seed went +19% in sample and -4% out of sample; no loop result shown | Unclear (no evidence yet) |
| Seed: long ETH when long-liquidation notional exceeds its trailing 30-day top 3% (v3) | Own result: -4% out of sample | No |
| AI cannot trade for you (60-day, v5) | One path, BTC, hourly, $100 per model; OpenAI +0.15%; fees ~$13 per $100; buy and hold ~+33% | Yes for "hourly LLM trading loses to fees and beta"; no for any broader claim |
| AI cannot trade for you (48-day, v6) | All 6 down 4% to 16% at Sep 16; $100 per model; fees $5-$11 | Yes (same narrow sense) |
| "Better at long than short" (v5, v6) | A rising market over the period; models' long exposure is beta | No |
| Fees explain the losses (v5, v6, v7) | Fee totals ($5-$13 on $100) plausible at hourly decisions; no-fee counterfactual is arithmetic only | Partly (fees large, counterfactual unsupported) |
| Fee calculator: lose $25k in 31 days (v5) | Unstated inputs; cannot reproduce | Unclear |
| Candles are the wrong data; use ticks (v8) | Bar backtests resolve intrabar order optimistically (plausible); illustrative single numbers (9.2 vs 3.3 bp; +13.6 vs -13) with no sample | Yes in principle (as a fill-realism point); numbers unclear |
| Free crypto ticks are available (v8) | Binance/Bybit public archives (outside knowledge agrees) | Yes |
| Tori Trades made $526,454 (v9) | Third party's claim, never verified; rules are discretionary trend lines | Unclear (no evidence) |
| Trend-line strategy works (his AI test, v9) | ~16 sources and many variants; best picked after the fact (XRP OOS +68%); mixed or negative on BTC/Apple; agents' own interpretation; "beats buy-and-hold" in falling markets | No |
| Chat-voted Polymarket bot: 58% win rate (v10) | 58 trades, 1 voter = 52%; net P&L reported as a loss; stats internally inconsistent; entries near 90c | No (win rate is not P&L) |
| AI consensus on Polymarket makes 23% (v11) | 25 trades, 10 wins, one 669% ticket = 121% of profit; decision time changed mid-test; shadow books ignore spread | No |
| Lower accuracy made more money (v11) | Long-shot entries (avg 0.29) with 25 trades | Unclear (noise) |
| Jev on Polymarket (v12) | 2-3 trades | No |
| Jev is calibrated, 238x cheaper, 5.4x faster (v13) | Vendor-style claims read from slides; his own later test shows flat or inverted calibration on price bars | Cost/speed unclear; calibration no |
| Jev cannot predict price (v14) | 44k calls, ~15k windows, three symbols, action-matched null, BH correction, RF and logistic baselines at AUC ~0.5 | Yes (a null result, well controlled for what it tests) |
| Dated/named backtest cards inflate LLM confidence, not returns (v14) | 97.7% of 14,828 paired windows; edge within +/-4% | Yes (reasonably supported) |
| RBI (research, backtest, $10 incubation) is robust (v2, v3, v4, v7) | Narrative; incubation at $10 has no power to detect small edges; hit rate "1 in 10" | Unclear |

## Gaps
- None of the 14 videos provides a downloadable ledger, a trade file or an out-of-sample table for the headline numbers. The Moon Dev site and GitHub pages mentioned (AI arena, auto-research loop code) were not checked, as the brief limited this task to the local transcripts.
- Not stated in any transcript: loop leverage for the 44,975% run, the exact number of iterations before it, the AI arena prompt and the 55 data fields, Polymarket fee treatment, the Tori Trades account's real results.
- Garbled captions: v2 average figures, v4 buy-and-hold ETH, v7 fee amounts, v10 average win and loss. Any figure needed for a decision should be rechecked against the video frame.
