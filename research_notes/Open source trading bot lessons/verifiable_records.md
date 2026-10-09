# Publicly verifiable records of systematic crypto trading (research date 2026-10-09)

Method note: about 14 tool calls; search-engine summaries plus 3 direct page fetches. I did not run the Hyperliquid endpoints myself, so the schemas are as documented. Several key facts (G-Research private-vs-public shake-up, copy-trading persistence) were NOT found.

## Hyperliquid vaults: free endpoints, history length, dispersion, persistence

### Takeaway
Hyperliquid exposes free, unauthenticated vault data: per-vault PnL and account-value history via `vaultDetails`, and a bulk snapshot of all vaults at stats-data.hyperliquid.xyz. This is the fastest independent dataset available. I found no published cross-sectional study of vault dispersion or persistence, so we would have to compute it ourselves.

### Cited Findings
- `POST https://api.hyperliquid.xyz/info` with `{"type":"vaultDetails","vaultAddress":"0x..."}` (optional `user`). Response includes name, leader, description, `apr`, `followers` (user, vaultEquity, pnl, allTimePnl, daysFollowing, vaultEntryTime, lockupUntil), leaderFraction, leaderCommission, isClosed, allowDeposits. `portfolio` is a list of `[period, {accountValueHistory, pnlHistory, vlm}]` for periods day, week, month, allTime and perp variants. History entries are `[timestamp, value]` pairs. The docs do not define `apr`, and they give no verbatim JSON example. — [Hyperliquid info endpoint docs](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)
- `userVaultEquities` (`{"type":"userVaultEquities","user":"0x..."}`) returns `[{vaultAddress, equity}]`. The official docs page I fetched has no endpoint that lists all vaults. — same source
- `vaultSummaries` via POST info is described by third-party providers as returning only vaults less than 2 hours old. For hourly snapshots of ALL vaults they point to `https://stats-data.hyperliquid.xyz/Mainnet/vaults` (no parameters; vault performance, APR, PnL history, summary). This is not in the official docs I fetched. — [Chainstack](https://docs.chainstack.com/reference/hyperliquid-info-vaultsummaries), [Hyperliquid Elixir client](https://hyperliquid.hexdocs.pm/Hyperliquid.Api.Stats.Vaults.html)
- Third-party Python library eth_defi scans this vault list and stores timestamped per-vault snapshots, computing TVL and PnL. — [eth_defi scan_vaults](https://web3-ethereum-defi.tradingstrategy.ai/api/hyperliquid/_autosummary_hyperliquid/eth_defi.hyperliquid.vault_scanner.scan_vaults)
- One practitioner guide estimates more than 2,000 vaults exist and says risk-adjusted metrics matter more than gross PnL (example: a vault with 60% drawdown). This is a blog claim, not an audited count. — [buildix.trade](https://www.buildix.trade/blog/hyperliquid-vaults-analytics-hlp-top-traders-guide-2026)
- HLP is the protocol's market-making vault (spread plus fee share) and takes directional risk in volatile periods. The documented stress episode was JELLY in 2024. — [buildix.trade](https://www.buildix.trade/blog/hyperliquid-vaults-analytics-hlp-top-traders-guide-2026), [OneKey HLP liquidation history](https://onekey.so/blog/ecosystem/hlp-liquidation-history/)
- tradingstrategy.ai snapshots of HLP, taken at different times, conflict: max drawdown -12.9% and lifetime Sharpe 4.17 with 1-year CAGR 17.8% in one; 1-year CAGR 15.4% and lifetime CAGR 34.3% in another. HLP ranks #75 over one month but #47 over one year. The site says its PnL is cleaned for deposit/redeem flows and so differs from Hyperliquid's own PnL. — [tradingstrategy.ai HLP](https://tradingstrategy.ai/vaults/hyperliquidity-provider-hlp)
- Dispersion examples (single snapshots): "100x" vault 1-year CAGR -29.6%, max drawdown -43.9%, TVL about $1.69K; "Gold Vault" max drawdown -49.2%; "Liquidator" vault down more than 95% from peak and deprecated. — [100x](https://tradingstrategy.ai/vaults/100x), [Gold Vault](https://tradingstrategy.ai/vaults/gold-vault), [Liquidator](https://tradingstrategy.ai/vaults/liquidator)

### Inferences
- Because `apr` is undefined and PnL includes flows, we should rebuild returns from `accountValueHistory` and `pnlHistory` ourselves. Deposit and withdrawal flows must be netted out, and PnL-per-unit-of-equity must be handled carefully.
- The "allTime" history of each vault gives time-series, so the number of vaults with more than 1 year of history can be counted directly from the bulk snapshot. Survivorship bias is a concern because closed or abandoned vaults may drop off listings. Take our own timestamped snapshots going forward.
- A persistence test (rank vaults on year 1, test on year 2 or on the forward period) is feasible in an afternoon. It is independent of our 10 coins and DON8/EMA8/VOL8 strategies. It also fits the evidence-rate rule as a breadth or time-to-answer addition, though it measures other people's skill rather than our trend core. Pre-register the vault selection rule before looking at returns.
- HLP is a market-maker, not a trend strategy, so it is weak evidence for or against trend.

### Gaps
- Count of vaults with more than 1 year of history: not found. Must be computed from the bulk endpoint.
- The exact JSON schema of stats-data.hyperliquid.xyz/Mainnet/vaults: not verified (WebFetch of it was not attempted). Fetch it directly to confirm.
- Top-vault strategy descriptions and a published persistence study: not found.
- Official statement of rate limits and retention of vault history: not found.

## Other on-chain vaults (dHEDGE, Enzyme, Drift, GMX)

### Takeaway
I did not research these in this pass beyond Hyperliquid tooling. No findings.

### Cited Findings
- None.

### Inferences
- tradingstrategy.ai / eth_defi appears to index many on-chain vaults and could be a one-stop data source. I did not verify coverage of dHEDGE, Enzyme, Drift or GMX.

### Gaps
- All of dHEDGE, Enzyme, Drift, GMX: no searches done.

## Exchange copy-trading lead-trader survival and persistence

### Takeaway
I found no rigorous, primary study of lead-trader survival or persistence on Binance, Bybit, OKX or Bitget. The only numbers are secondhand and come from an exchange marketing blog, so they are claims.

### Cited Findings
- A KuCoin blog (competitor exchange, commercial interest) reports a 90-day study of more than 100,000 copy outcomes on Binance, Bybit and MEXC: 97% of leaders had positive personal PnL but only 43.61% delivered positive returns to followers. Follower profitability: Binance about 66.5%, Bybit about 43.65%, MEXC about 57.8% (net follower PnL negative on MEXC), blended 48.48%. The original study could not be located and the methodology is not explained. — [KuCoin blog](https://www.kucoin.com/blog/is-crypto-copytrading-profitable-in-2026); same figures repeated in [AInvest](https://www.ainvest.com/news/leader-copying-losing-point-2608/) (derived, not independent)
- Academic: Apesteguia, Oechssler and Weidenholzer, "Copy Trading", Management Science 66(12), 2020. A lab experiment finding that seeing others' performance, and especially being able to copy, raises risk-taking. It is not evidence on real leaders' persistence. — [BSE](https://bse.eu/research/publications/copy-trading)
- A University of Vienna thesis found eToro and Wikifolio social-trading returns could not be shown to beat the S&P 500; T-tests were consistent with chance. This is a thesis, so low weight. — [Univie thesis](https://utheses-gateway.univie.ac.at/api/document/get/file/73534)
- eToro data studies (Deng et al., Information Systems Research, forthcoming at the time) focus on how followers pick leaders and on network dynamics, not on persistence. One 2025 arXiv preprint uses eToro data from only April to October 2013. — [arXiv 2507.01817](https://www.arxiv.org/pdf/2507.01817), [TAF working paper](https://wiwi.uni-paderborn.de/fileadmin-wiwi/cetar/TAF_Working_Paper_Series/TAF_WP_074_DengYangPelsterTan2023_rev.pdf)
- Leader selection research (250 top traders) finds credentials matter more than performance to followers. — [Birmingham portal](https://research.birmingham.ac.uk/en/publications/determinants-of-leadership-in-online-social-trading-a-signaling-t)

### Inferences
- The gap between leader PnL and follower outcomes (if real) points to execution, fees, slippage and leverage differences, plus selection. It does not show leader skill.
- Exchange leaderboards are subject to survivorship and self-selection; free historical leaderboard data with delisted traders appears not to exist.

### Gaps
- Primary survival and persistence data for Binance, Bybit, OKX, Bitget: not found. OKX and Bitget not searched specifically.
- No peer-reviewed persistence result for eToro or ZuluTrade leaders surfaced.

## Kaggle G-Research Crypto Forecasting (2021-22) and later competitions

### Takeaway
Design is a genuine out-of-sample test: the final score came from roughly three months of live data after the submission deadline. Winners used LightGBM with heavy feature engineering. I could not find the numeric public-vs-private shake-up or the winning correlation, so the overfitting evidence is qualitative only.

### Cited Findings
- Competition ran November 2021 to May 2022. Teams forecast short-term returns for 14 coins, scored by weighted Pearson correlation. Teams chose two models, which were scored on about three months of live data collected after the deadline. $125,000 prize pool; $50,000 to first. — [G-Research wrap-up](https://www.gresearch.com/news/wrapping-up-the-g-research-crypto-forecasting-competition/)
- Winners: 1st Meme Lord Capital (Jose and Eduardo), 2nd Nathaniel Maddux, 3rd GABA. All top three used LightGBM; some tried neural networks. Winners said feature engineering mattered far more than model choice. The page gives no scores. — same source
- G-Research states the leaderboard saw "many big jumps and precipitous drops", particularly early on, because the data is very noisy. — same source
- Unverified: a Kaggle profile aggregator lists scores of 0.03 (rank 2) and 0.01 for this competition on 2022-05-04 for individual accounts. It is not known whether these are private scores or winners' scores. — [clist.by](https://clist.by/account/nathanrm/resource/kaggle.com/)
- Later: ICAIF 2025 Cryptocurrency Forecasting competition (ceremony 2025-11-16, Singapore; 130+ participants, 740+ submissions). 1st Team 8k3 (Edinburgh; Stuart-Landau recurrent network), 2nd Hanyang University lab (LSTM-MLP). Source is participants' LinkedIn posts; the official leaderboard was not found. — [LinkedIn post (Jun Young Byun)](https://kr.linkedin.com/in/jun-young-byun)

### Inferences
- Winning private correlations in such noisy settings were, per the unverified aggregator entries, of order 0.01-0.03. This is a low-confidence indication and consistent with a very small achievable edge in short-horizon crypto prediction. It should be checked on Kaggle's leaderboard page.
- A forward-live private leaderboard is the strongest design for detecting overfitting; the stated big jumps suggest public leaderboard ranks were weak predictors.

### Gaps
- Public-vs-private rank changes, the winners' write-ups and exact private scores: not retrieved (Kaggle pages were not fetched; try the Kaggle competition Leaderboard and Discussion tabs).
- Official results of the ICAIF 2025 competition: not found.

## Numerai Signals / Numerai Crypto

### Takeaway
Docs describe scoring mechanics only; I found no published meta-model performance or payout evidence for Crypto, and signal types that earn positive correlation are not documented in what I retrieved.

### Cited Findings
- Numerai Crypto: target is 20-day horizon with 2-day lag (20D2L). Scores are CORR and MMC (contribution to the Crypto meta model, CNWMMmin1, a naive-weighted average of cleaned submissions from users with at least 1 NMR staked). Payout metric: SEASON = (CORR * 0.1) + (MMC * 1.0) over 20 score days. The page has no performance figures. — [Numerai Crypto scoring definitions](https://docs.numer.ai/numerai-crypto/scoring/definitions)
- Numerai Signals docs are inconsistent: one page lists FNCv4 and MMC as payout scores; the current index lists Alpha (60D2L target) and Meta Portfolio Contribution (MPC). — [Signals scoring](https://docs.numer.ai/numerai-signals/scoring), [docs index](https://docs.numer.ai/llms.txt)
- Weighting MMC 10x above CORR means payouts reward uniqueness versus the staked crowd, not raw predictive correlation. (This is arithmetic from the formula above.)

### Inferences
- Staked-user participation is verifiable, but without per-model public histories we cannot get independent evidence quickly. Numerai Crypto per-model leaderboards may be public on numer.ai; not checked.

### Gaps
- Meta-model performance, the signal types that score, and payout totals: not found.
- Which Signals scoring page is current: unresolved.

## Overall for our team
- Fastest independent evidence: Hyperliquid vault bulk snapshot plus `vaultDetails` history (free, no auth). Start snapshotting now, because survivorship bias grows with delay.
- Verifiable out-of-sample successes found: none that are strategy-type-specific. The only verified facts are design properties (G-Research live scoring; HLP's public ledger). Performance numbers I found are from third-party aggregators or exchange marketing and are claims.
