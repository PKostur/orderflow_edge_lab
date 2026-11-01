# Community and commercial automated crypto strategies: forward/live evidence (research date 2026-10-09)

Overall caveat: searches returned thin evidence. No verifiable, after-fee, third-party forward record was found for any bot below. Most material is vendor docs, competitor reviews and anecdotes. Search tool summaries are secondary; items fetched directly are marked (fetched).

## 1. Which strategies rank well on forward-test aggregators (strat.ninja) and how does forward compare with backtest?

### Takeaway
I could not reach strat.ninja (DNS failure on fetch; search found no page linking it to Freqtrade), so no ranking data, forward-vs-backtest comparison or survivorship evidence from it could be collected. The freqtrade-strategies repo itself says its strategies are educational, and its README gives no performance record.

### Cited Findings
- strat.ninja fetch failed with "getaddrinfo ENOTFOUND" on 2026-10-09; searches for "strat.ninja freqtrade" returned nothing relevant (only an unrelated TradingView "Stratninja" page). The site may be defunct or renamed (not confirmed) — [strat.ninja (fetch failed)](https://strat.ninja)
- Official freqtrade-strategies README (fetched): strategies are "for educational purposes only", used "AT YOUR OWN RISK"; results depend heavily on pairs/timeframe/timerange; some strategies may only work in specific market conditions; they are "starting points", users should backtest then dry-run before real money; works with Freqtrade 2022.4+; no dates of creation or last test; no overfitting discussion; does not mention strat.ninja — [freqtrade-strategies](https://github.com/freqtrade/freqtrade-strategies)
- Practitioner anecdote: a developer reports a 150-epoch hyperopt produced a strategy ~4x worse out-of-sample than hand-tuned defaults (single anecdote via search summary, original blog not fetched) — [search result source: stardance.hackclub.com project](https://stardance.hackclub.com/projects/17999)
- A Freqtrade guide lists "very high backtest returns with live losses" as an overfitting warning sign and recommends forward (dry-run) testing (secondary, Chinese-language tutorial) — [adg.csdn.net](https://adg.csdn.net/696f2617437a6b4033697c37.html)
- Freqtrade applies stoploss/ROI to the leveraged profit ratio, not price move (at 5x, -7% stop is ~-1.4% price), a source of mis-sized risk in futures setups (single developer report) — [stardance.hackclub.com](https://stardance.hackclub.com/projects/17999)

### Inferences
- Any aggregator ranking of dry-run results would be subject to selection (strategies are public and re-tuned after viewing results) and dry-run fills ignore queue position and slippage; this is a general inference, not shown by a source here.
- For our repo, public freqtrade leaderboards are low-value evidence unless the raw dry-run trade logs are obtainable; none were found.

### Gaps
- strat.ninja rankings, methodology, time series of forward vs backtest: unreachable. Try Wayback Machine or the freqtrade Discord/forum if still needed.
- No survivorship or curve-fitting study of freqtrade community strategies found.

## 2. NostalgiaForInfinity: live/dry-run results and core logic

### Takeaway
NFI (iterativv/NostalgiaForInfinity) is a large, actively maintained 5m-timeframe spot/futures Freqtrade strategy (versions X to X8) with many entry conditions plus grind/rebuy position-adjustment logic. The repo publishes no performance figures; it points to commit comments for backtests. No independent live or dry-run record was found.

### Cited Findings
- Repo (fetched; page snapshot 2026): "Trading strategy for the Freqtrade crypto bot"; ~27.9k commits, 3.5k stars, 760 forks; strategy files NostalgiaForInfinityX through X8; README points to individual commit comments for backtest results; no performance, backtest or dry-run claims on the page itself; no risk disclaimer on the page; promotes referral links, donations and Patreon — [NFI repo](https://github.com/iterativv/NostalgiaForInfinity)
- Recommended settings (fetched): 6 to 12 open trades, unlimited stake, 40-80 pair volume pairlist, prefers USDT/USDC stable pairs, blacklist leveraged tokens (BULL/BEAR/UP/DOWN), timeframe must be 5m, `use_exit_signal` true, `exit_profit_only` false, `ignore_roi_if_entry_signal` true — [NFI repo](https://github.com/iterativv/NostalgiaForInfinity)
- Auto-updater (fetched): Docker `nfi-updater` can pull strategy updates on a cron schedule and restart the bot, meaning the live strategy can change without review — [NFI repo](https://github.com/iterativv/NostalgiaForInfinity)
- Release changelog entries (X7 v17.4.x) mention "grind entries" and "Rebuy mode (Long)", confirming averaging-down logic exists — [newreleases.io NFI v17.4.379](https://newreleases.io/project/github/iterativv/NostalgiaForInfinity/release/v17.4.379)
- A Patreon review post says the maintained file is NostalgiaForInfinityX and developers recommend max 6 open trades — [Patreon](https://www.patreon.com/posts/89663923)

### Inferences
- Core logic (from memory and the above, not directly confirmed here): many stacked indicator conditions on 5m to buy dips, exit on profit targets, with grind/rebuy to average down on losing positions. Such designs have a high win rate with fat left tails (unrealized bag-holding), which backtests can hide. Not verified by a source in this session.
- The auto-update feature and referral/donation funding mean the strategy is a moving target, which makes any single forward record hard to attribute.

### Gaps
- No dry-run/live equity curve, drawdown, or fee-adjusted record found. No GitHub issue or Discord content on stuck trades in bear markets was retrieved (one search found nothing).
- The exact entry-condition list was not extracted (source file is very large).

## 3. Passivbot, Hummingbot market making and funding-arbitrage scripts

### Takeaway
Passivbot (contrarian grid/martingale market maker on perps) publishes no live results; the only figures are unverified user anecdotes relayed by a competitor. Hummingbot's docs describe Avellaneda-Stoikov and funding-arb scripts but make no performance claims, and no verifiable P&L was found.

### Cited Findings
- Passivbot README (fetched): bot for perpetual futures that places/cancels limit orders; "does not predict prices or follow trends", is "a contrarian market maker"; default `trailing_martingale` starts small and adds as price moves against it within exposure limits; `ema_anchor` also available; `trailing_grid_v7` deprecated; Forager picks markets by volume, EMA readiness and 1m log-range volatility; "Unstucking" realizes small losses on stuck positions, bounded so balance doesn't fall below a set percentage under its peak; v8 is a breaking release; "Used at one's own risk"; Unlicense; no live results, returns or track record published; mentions a Hyperliquid reference vault but no performance data; contains referral links — [Passivbot](https://github.com/enarjord/passivbot)
- Gainium review of Passivbot v7.8.4, dated 2026-03-31 (author is founder of a competitor): weaknesses include no stop-loss orders, no loss protection, performs better in sideways than trending markets, needs monitoring. Anecdotal unverified user reports: ~6.3% annualized over 100 days while BTC hold returned ~16% over that period; another trader's 1.5-year grid test ~30% on BTC, ~break-even on ETH. Notes TWEL Enforcer (auto-reduce when total wallet exposure exceeds buffer, v7.5.0) and `live.max_realized_loss_pct` default 0.05 — [Gainium review](https://gainium.io/review/passivbot)
- Hummingbot Avellaneda-Stoikov guide (fetched): reservation price shifts with inventory deviation q, risk aversion gamma, volatility and remaining time; bid/ask = reservation +/- half optimal spread; finite-horizon version only; paper does not specify gamma and kappa estimation, Hummingbot derives from spread limits; no backtest, profitability or live claims — [Hummingbot guide](https://hummingbot.org/blog/guide-to-the-avellaneda--stoikov-strategy/)
- Academic critique (via search summary, original not fetched): inventory build-up tends to coincide with adverse price moves, so ignoring adverse selection can make A-S results misleading; exponential price-impact assumption may not match markets — [Hummingbot A-S search result](https://hummingbot.org/blog/technical-deep-dive-into-the-avellaneda--stoikov-strategy/) (note: the critique itself came from a different linked source in the search, [quante substack](https://quante.substack.com/p/the-avellaneda-stoikov-algorithm))
- Hummingbot V2 funding-rate arbitrage script (`v2_funding_rate_arb.py`, added in release 1.27.0) compares funding rate differences across exchanges against a profitability threshold and applies take-profit/stop-loss; 2024 GitHub issues report runtime errors; no P&L published — [Hummingbot script examples](https://hummingbot.org/scripts/examples), [1.27.0 notes](https://hummingbot.org/release-notes/1.27.0)
- Hummingbot 2019 launch material claimed simulations showing 10-50% annual returns for makers (simulation, project's own claim) — [Hummingbot blog archive 2019](https://docs.hummingbot.org/blog/archive/2019/)
- 2022 FIRO Hummingbot liquidity-mining campaign, forum poster (anecdotal): 90% of bots earned $0.03 or less in a week while ~1% earned $555+; poster noted capital losses were unknown — [Firo forum](https://forum.firo.org/t/2022-firo-hummingbot-campaign/2290?page=2)

### Inferences
- Passivbot's edge, if any, is harvesting mean reversion with martingale-like averaging; payoff is concave (small steady gains, large drawdown in sustained trends), consistent with the no-stop-loss caveat. Not independently measured.
- Hummingbot MM profits in campaigns often came from exchange/protocol rewards, not spread capture; rewards concentrated in few bots (anecdote).
- Our funding-carry result (venue-mismatch artifact) parallels cross-exchange funding-arb scripts: spread differences across venues can be basis/venue artifacts. This is an inference, not a source finding.

### Gaps
- No verifiable Passivbot live account or vault performance (the Hyperliquid reference vault had no data in the README; its on-chain history could be checked directly).
- No Hummingbot P&L reports for A-S, pure MM, cross-exchange MM or funding arb; strategy-level rules for pure MM and cross-exchange MM not fetched.
- OctoBot and Gunbot: not researched in the available call budget; no findings.

## 4. Independent evaluations of grid/DCA bots: when they make or lose money; commercial bots and platform risk

### Takeaway
Theory and the little independent evidence say grids have near-zero expectation before fees, profit in ranges, and accumulate losing inventory in sustained downtrends; leverage on DCA/martingale adds liquidation risk. No rigorous independent test of 3Commas, Pionex, Bitsgap or Cryptohopper performance was found; the best-documented commercial failure is the 3Commas API-key breach (Dec 2022).

### Cited Findings
- arXiv 2506.11921 (June 2025; Chen, Chen, Jang): under simple assumptions (50/50 moves, no fees) a traditional grid's expected return is "essentially zero"; proposed Dynamic Grid Trading (resets grid) reportedly beats traditional grid and buy-and-hold on BTC/ETH minute data Jan 2021 to Jul 2024 in the authors' own backtest; abstract gives no fee assumptions or numbers; unclear if peer-reviewed — [arXiv abstract](https://arxiv.org/abs/2506.11921), [full HTML](https://arxiv.org/html/2506.11921v1)
- Stevens Institute student project on Bybit BTC grid bots: ML tuning did not beat traditional methods; a hedging variant beat holding BTC (student project, backtests) — [Stevens FSC](https://fsc.stevens.edu/cryptocurrency-market-making-improving-grid-trading-strategies-in-bitcoin/)
- Single-trader 6-month Gate.io BTC perpetual grid account (fetched): net "roughly flat-to-modest after fees", small range-month gains mostly given back in trends; four mistakes: range too tight (price outside range ~2 weeks), no drawdown stop, 5x leverage (20% adverse move = liquidation), ignored funding paid on a long grid in a downtrend; figures labeled illustrative — [DEV Community](https://dev.to/joe_hans_6c082d6c1caf189f/i-ran-a-gateio-btc-grid-bot-for-6-months-real-returns-and-3-fatal-mistakes-2i1p)
- cTrader grid product risk disclosure: unrealized losses accumulate if price leaves the range, growing fast in long mode in a strong downtrend — [ctrader.com](https://ctrader.com/products/3892)
- Gainium forum feature request: on perps a DCA trader can't know whether all safety orders will fill before liquidation (structural martingale risk) — [Gainium community](https://community.gainium.io/t/bot-ideas-and-extra-functions-to-the-platform-accumulatively/2428)
- 3Commas breach: Dec 2022 API-key leak; company initially called reports "false rumors", later confirmed data was real; loss estimates differ by source (about $20M Halborn, about $22M SiliconANGLE, over $27M HAPI, $14.8M across 44 victims per ZachXBT); 3Commas says phishing contributed; class actions (Freeman Jan 2023; Tritt Sep 2023, N.D. Cal.); Ninth Circuit in March 2026 reversed dismissal on jurisdiction only (allegations unproven) — [The Block](https://www.theblock.co/news/ecosystems/2022-12-28-binance-warns-about-3commas-api-leak-says-users-should-disable-keys-198295), [Halborn](https://halborn.com/explained-the-3commas-breach-december-2022/), [SiliconANGLE](https://siliconangle.com/2022/12/29/crypto-trading-service-3commas-confirms-massive-api-key-leak-hack/), [Forklog/HAPI](https://forklog.com/en/api-key-leaks-and-exchange-inaction-a-hapi-analysis-of-the-3commas-incident/), [Bloomberg Law](https://news.bloomberglaw.com/litigation/consumers-revive-data-breach-suit-over-millions-in-crypto-losses)
- Commercial bot reviews found were aggregator/marketing or competitor pages (Capterra, altFINS 7.8/10, Gainium); Trustpilot is user-written and mixed; none measured returns — [Gainium on 3Commas](https://gainium.io/review/3commas), [altFINS](https://altfins.com/review/3commas/)
- Oct 10, 2025 crash context: reports of roughly $19B leveraged liquidations, ~1.6M accounts, 70% of damage in 40 minutes, altcoins down up to 50% intraday, USDe briefly ~$0.66 on Binance. No source tied it specifically to grid/DCA bot losses (inference only) — [CoinShares](https://etp.coinshares.com/insights/knowledge/billions-in-liquidations-what-happened/), [The Defiant](https://thedefiant.io/newsletter/defi-daily/the-ultimate-10-10-crash-autopsy)

### Inferences
- Grid/DCA/Passivbot-style strategies are short-volatility, concave payoff; their reported "win rates" and calm-period equity curves understate tail risk. Fits our finding that the trend core (long-convex) survives while mean-reversion zoos failed.
- Broker/vendor claims (e.g. 15-30% annual in sideways phases) lack methodology and should be ignored.
- Platform risk (API-key custody) is a distinct failure mode from strategy risk; irrelevant to our no-order-placement setup except as a reason not to trust vendor track records.

### Gaps
- No Pionex, Bitsgap, Cryptohopper, Gunbot or OctoBot independent performance evaluations found; no academic out-of-sample study of grid/DCA bots with fees.
- No documented post-mortems of grid/DCA bot blowups on 2025-10-10 found.
- Reddit r/algotrading, r/freqtrade and Discord threads were not retrievable through the search tool.

## Relevance to repo (brief)
Per the evidence-rate rule, none of these families offer a cheap source of independent evidence: they have no verifiable public records, and re-implementing dip-buy or grid variants on the same 10 coins would violate the rule. The one potentially verifiable lead is Passivbot's Hyperliquid reference vault (on-chain history), which is not a strategy test but could give a live-record sanity check on a short-vol strategy; not pursued.
