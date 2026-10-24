# External arbiters for the payoff-geometry-v1-1 branch conclusions (as of 2026-10-16)

Scope note: Bash was unavailable, so git history/tags were NOT inspected directly. Repo status marks below come from Read/Glob/Grep of files only. Several doc hosts (jfqa.org, docs.tardis.dev, docs.coinmetrics.io) were unreachable by fetch; those facts rest on search snippets or are flagged. Items marked "(background knowledge, unverified here)" have no fetched source.

## 1. Market reality as arbiter: independent price/funding sources and book reconciliation

### Takeaway
The forward books are currently checked only against the repo's own replay (G1, same code, same data adapters), which proves self-consistency, not truth. The cheapest independent arbiters are free public exchange archives and APIs that the repo already partly uses (Binance archive, OKX archive, Hyperliquid); the missing piece is a vendor-independent, tolerance-banded reconciliation of fills/prices/funding per position per day.

### Cited Findings
- Binance public data repo: daily files (published the next day) and monthly files (first Monday of the month), each zip with a .CHECKSUM file verified with sha256sum; MIT-licensed repo; futures UM klines come from the /fapi/v1/klines endpoint. The fetched page did not confirm fundingRate/markPriceKlines/premiumIndexKlines/metrics folders; terms are in a separate TERMS_AND_CONDITIONS file not shown — [binance-public-data](https://github.com/binance/binance-public-data)
- Hyperliquid info endpoint: POST /info with type "fundingHistory", coin, startTime (ms), optional endTime; fields coin, fundingRate, premium, time; funding reported hourly. Sourced from an SDK file and third-party guides, not the official gitbook (not fetched) — [SDK method](https://app.unpkg.com/@nktkas/hyperliquid@0.33.1/files/esm/api/info/_methods/fundingHistory.js), [OneKey guide](https://onekey.so/blog/ecosystem/hyperliquid-funding-rate-history-api/), [Dwellir](https://www.dwellir.com/blog/hyperliquid-funding-rates-for-rpc-consumers)
- Coin Metrics Community API: root https://community-api.coinmetrics.io/v4, no API key needed, 10 requests per 6 s per IP, non-commercial use; blog says market data (trades, books, OI, funding, liquidations) only for the past 24h, reference rates daily with full history; docs and blog disagree on sub-daily windows — [Coin Metrics community docs](https://docs.coinmetrics.io/packages/coin-metrics-community-data), [blog](https://coinmetrics.io/?p=6495). Coin Metrics was acquired by Talos July 2025 (secondary source), so terms may have changed.
- Tardis.dev: a 2022 Deribit post says the first day of each month is available without an API key (Deribit promotion; current scope and whether MEXC is covered NOT confirmed) — [Deribit insights](https://insights.deribit.com/?p=7828). Treat Tardis free samples as a spot-check only, uncertain.
- Repo: G3/funding-source/Hyperliquid checks already use independent venue data as arbiters of the signal (not of the paper book) — [fast_gates RESULT.md](/home/user/orderflow_edge_lab/research/fast_gates/RESULT.md)
- Repo G1: paper vs "V_ALL" replay correlation 0.9992, tracking error 0.34%/yr over 180 days, 70 coins — [calibration.json](/home/user/orderflow_edge_lab/research/fast_gates/calibration.json). V_ALL is the repo's own replay, so this is an implementation-consistency check, not independent.

### Inferences
- Professional trade/position reconciliation (background knowledge, unverified here; no source fetched) is three-way: internal book vs execution venue statement vs independent market-data vendor, per symbol per day, with tolerance bands (price vs vendor close/VWAP within a few bps plus spread; funding within rounding of exchange-published rate x notional; position quantity exact). For a paper book there are no venue fills, so the arbiter is: recompute each day's mark-to-market from an independent source of 1d closes and funding history, and require per-coin daily return difference < tolerance and portfolio-level TE small. Exceptions list is the output, not a pass/fail only.
- Concrete wiring at zero cost: (i) for the Binance-perp watches (fade-24h, near-miss, TradFi perps) pull the same days from data.binance.vision monthly klines + funding after month-end, diff against the logged forward prices (the repo already has binance_futures_archive.py and tests that reference data.binance.vision); (ii) for MEXC-priced books there is no free archive equivalent I verified, so cross-check MEXC daily closes against Coin Metrics reference rates / CoinGecko for the large coins only (basis differences expected: record tolerance ex ante, e.g. median abs daily return gap); (iii) store the vendor snapshot hash. Pre-fix tolerance numbers in a committed config before the first comparison.
- Key limit: an independent price feed confirms that prices were recorded correctly; it cannot confirm that the funding-source claim (a) is "right". Claim (a) is already tested against three consistent venues, which is the right shape of arbiter, but each venue differs in coin set (Bybit 58 coins with a download defect; Hyperliquid 64 of 70) and sample window.
- Subtle point about claim (a): the repo's own table shows the funding-swap effect is NOT_MATERIAL on development coins (blend 0.26 to 0.19) and MATERIAL on untouched coins (carry 1.69 to -0.18; blend 1.60 to 0.67; t -2.20), over only ~15 months because MEXC funding only starts 2025-04-15 — [RESULT.md](/home/user/orderflow_edge_lab/research/fast_gates/RESULT.md). The mechanism is explicitly labelled "unverified" there. An external arbiter for the mechanism would be a direct basis decomposition: MEXC perp vs Binance perp price spread time series on the same coins, and whether the long-low/short-high-funding book earns the spread (can be computed from archives; not yet done per files seen).

### Gaps
- Could not confirm MEXC free historical archive availability, nor Bybit/OKX archive field details (not fetched).
- No fetched source describing industry tolerance-band conventions; the three-way reconciliation description is background knowledge only.

## 2. Published-literature arbiter: known-answer reproduction

### Takeaway
The repo has a CTREND implementation (ctrend.py, tests) and a "paper cost scenarios" function, but I found no test asserting reproduction of a published headline number; the near_miss reference_daily_v1.json reproduces the repo's own earlier series (hash-pinned), not a published number. Published factor results can only be an approximate, period-matched sanity check because the repo universe (~70 MEXC majors/mid-caps, 2020-2026) differs from the papers' universes (1,500 to 3,000+ coins).

### Cited Findings
- CTREND: Fieberg, Liedtke, Poddig, Walker, Zaremba, JFQA vol 60 no 7 (Nov 2025) pp 3116-3153, DOI 10.1017/S0022109024000747, open access (CC BY); >3,000 coins; machine learning over technical indicators; reported to survive transaction costs and persist among large liquid coins — [Cambridge](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178). I could not retrieve the headline long-short return/Sharpe figures (PDF host unreachable). A search snippet mentions "3.87% per week" for a lowest-return portion; this is unconfirmed and ambiguous, do NOT use it as a target.
- Repo ctrend.py docstring: "CTREND (Fieberg... JFQA 2025): 28 technical indicators, CS-C-ENet, quintile long-short" — [ctrend.py](/home/user/orderflow_edge_lab/src/orderflow_edge_lab/ctrend.py)
- Liu, Tsyvinski, Wu, "Common Risk Factors in Cryptocurrency", Journal of Finance 2022, 77(2), 1133-1177, DOI 10.1111/jofi.13119: three-factor model (market, size, momentum); sample starts with coins above $1M market cap, 1,583 coins by end-2018; 10 characteristic long-short strategies explained by the 3 factors (NBER version says nine) — [SSRN](https://papers.ssrn.com/abstract=3379131), [NBER w25882](https://www.nber.org/papers/w25882.pdf)
- Carry: secondary survey reports a spot-long/perp-short carry Sharpe of 6.45 over 2020-2025, 4.06 from 2024, negative in 2025; He, Manela, Ross, von Wachter report Sharpe 1.92 for BTC under retail costs, up to 3.94 for market makers. Different definitions (delta-neutral spot/perp, BTC), not the repo's cross-sectional long-low/short-high-funding perp book, so not comparable — [arXiv 2510.14435](https://arxiv.org/pdf/2510.14435), [arXiv 2212.06888](https://arxiv.org/html/2212.06888v5) (as summarised by search tool; original Schmeling-Schrimpf-Todorov paper not retrieved).

### Inferences
- What a known-answer test should be: (1) Re-run the repo's momentum and CTREND code on a universe/period matching a paper as far as free data allow (Coin Metrics/CoinGecko daily top-N by market cap, long history), and require the sign, rough magnitude (within the paper's reported confidence interval, not a point), and the decay pattern (pre-2020 stronger than post, large-cap weaker) to match. Pre-commit the acceptance band. (2) The quantity to match is the paper's long-short return per week and its t-stat, with the paper's own cost assumption; paper numbers are mostly on small illiquid coins, so a repo Sharpe on 70 liquid MEXC coins being lower than paper is expected and is not a failure, whereas opposite sign is.
- Cross-sectional momentum Sharpe of 0.90 and trend 1.2 in the repo are in a plausible range for post-2020 liquid-coin results in the literature generally (background knowledge, not verified), but the literature has publication-bias and the Venue replication shows S2 collapsing to 0.03 on Binance prices, so S2 is not a robust arbiter-confirmed result.
- A trend-leg external check: TSMOM on BTC/ETH daily is reproducible from free CoinMetrics daily reference rates; compare repo S1 on BTC+ETH only vs a minimal independent implementation (see section 5).

### Gaps
- Exact published headline figures (CTREND quintile spread, LTW weekly momentum/size returns, time-series-momentum Sharpe papers) not retrieved; the report writer should not quote any.
- No crypto time-series-momentum paper retrieved.

## 3. Synthetic known-answer tests and look-ahead detection

### Takeaway
Look-ahead detection is present (truncation invariance, modelled on freqtrade lookahead-analysis). Null/matched-random machinery exists. A planted-signal recovery test (inject a known-Sharpe signal, require the full pipeline including costs, rebalancing, and stats to recover it, and recover about zero under shuffled/null) appears partial or absent at the pipeline level.

### Cited Findings
- Repo truncation_check.py: "A signal/feature function is causal if its output at row t is identical whether it is computed on the full data or on data truncated at t"; compare modes row/history, tolerance atol — [truncation_check.py](/home/user/orderflow_edge_lab/src/orderflow_edge_lab/truncation_check.py); tests/test_truncation_invariance.py exists (listed; contents not read).
- Repo review_methods.py provides action_matched_null_p, matched_random_selection_returns, random_event_null, bh_family (Benjamini-Hochberg), assert_single_look, scale_invariance_flag, concentration_flag, boundary_flag, cost_wall_bps, expected_max_normal_z and deflated_sharpe_null_consistent — [review_methods.py](/home/user/orderflow_edge_lab/src/orderflow_edge_lab/review_methods.py)
- Grep for "placebo|permut|planted|synthetic|shuffle" in src/tests matched ~20 files (e.g. test_ctrend, test_near_miss_forward, test_fade24_forward, strategy_search*.py); I did not read each, so whether any plants a known Sharpe through the whole pipeline is unconfirmed.
- Bailey, Borwein, López de Prado, Zhu, "The Probability of Backtest Overfitting" (J. Computational Finance 20(4), 2017): hold-out is unreliable for investment backtests; proposes CSCV to estimate PBO; R package "pbo" on CRAN — [SSRN](https://papers.ssrn.com/abstract=2326253), [CRAN pbo](https://cran.hafro.is/web/packages/pbo/readme/README.html)
- Repo G2 uses stationary block bootstrap (mean block 20 days, 20,000 paths, seed 20261004) calibrated to target Sharpe 1.39 (not the 2.09 headline) to set drawdown envelopes: MDD p2.5 -13.7%, median -6.3%; false-alarm 3.6% — [calibration.json](/home/user/orderflow_edge_lab/research/fast_gates/calibration.json)

### Inferences
- Design of a planted-signal harness (generic best practice; not a cited source): generate synthetic panel with 70 coins, empirical vol/correlation/fat tails (block-resampled from real returns), plant a signal with known per-period IC (or an exact time-series trend with a known Sharpe), run the unmodified strategy functions, and assert (a) recovered Sharpe within the sampling interval of planted value after costs, (b) null (signal-destroyed by cross-sectional or block permutation) gives Sharpe about 0 with Type-I rate near nominal over many seeds, (c) planting a one-bar look-ahead is flagged by truncation_check (positive control for the detector, which is as important as the detector itself). Wire as CI tests with fixed seeds so thresholds are committed.
- Note on the funding-carry claim: a positive control would be a synthetic perp where price follows a known basis process and funding is paid by that same process; checking that the pipeline gives zero carry when funding is consistent, and positive carry when a mismatched funding series is injected, would directly reproduce the proposed artifact mechanism and validate claim (a)'s mechanism independent of any real venue.
- Limits: these prove the code does what it says; they cannot prove the strategy has edge in reality.

### Gaps
- Contents of test_truncation_invariance.py and the placebo-bearing tests not read, so exact coverage is unknown.

## 4. Time as arbiter: sealed forecasts and statistical power

### Takeaway
Pre-registration exists in git commit ids and config hashes; a calibrated forward envelope (G2) is present. Cryptographic third-party timestamping is absent as far as I could find. Power math shows 180 days cannot confirm a Sharpe of about 1 to 1.2, only detect breakage or gross cost errors.

### Cited Findings
- Repo: fast-gates config "declared 868fdcc, thresholds frozen 7a07d46, both before 2026-10-05"; funding-source-check "declared ffd8628"; hyperliquid check "declared 4169095"; multi-premia "declared in c7b80d6" — [fast_gates RESULT.md](/home/user/orderflow_edge_lab/research/fast_gates/RESULT.md), [multi_premia RESULT.md](/home/user/orderflow_edge_lab/research/multi_premia/RESULT.md)
- near_miss reference_daily_v1.json embeds sha256 of code, configs and data frames, git_head_at_generation, data_end, and claims "live_trading_authorized: false" — [reference_daily_v1.json](/home/user/orderflow_edge_lab/research/near_miss_forward/reference_daily_v1.json)
- Grep of .github/workflows for tag/sign/sha256sum patterns found no matches; grep for "opentimestamps" across src/docs/research/tests/.github found no hit (the hit list was driven by other terms in the same regex). So no external timestamping appears present.
- OpenTimestamps: calendar servers aggregate commitments in Merkle trees anchored in Bitcoin transactions; `ots stamp <file>` then `ots upgrade`; confirmation takes a few hours; verification needs a Bitcoin node (pruned suffices); it proves existence before a time, commit dates themselves are self-declared; git-ots can stamp a commit ID and ancestors but history rewrite invalidates the proof — [PyPI git-ots](https://pypi.org/project/git-ots/), [opentimestamps-client](https://pypi.python.org/pypi/opentimestamps-client/0.5.1)
- Git itself is not an external arbiter: commit dates and force-pushes are controllable by the author. GitHub's server-side record (push events, Actions run logs with run ids, release/tag immutability settings) is partially third-party evidence (background knowledge, unverified here).

### Inferences
- Power (own calculation using the standard approximation SE(annualised SR) ~ sqrt((1 + SR^2/2)/T years), iid assumption; autocorrelation and fat tails make it worse): at SR 1.2 and T=180 days (0.49 y), SE ~1.9, so expected t ~0.6; testing SR>0 at t=2 needs about 4.8 years for SR 1.2, ~6 years for SR 1.0, ~1.5 years for SR 2.1 (the retracted headline). Even 18 months leaves SR 1.0 vs 0.5 indistinguishable. Therefore 180 days is adequate only for (i) mechanical correctness (P&L vs replay), (ii) breakage alarms like G2, (iii) falsifying the headline 2.09 blend if realized Sharpe is strongly negative, not for confirming the trend leg.
- Better sealed-prediction design: before data arrives, commit (hash + OpenTimestamps) a per-watch file listing expected daily vol, the 2.5/50/97.5 percentile paths of cumulative return and max drawdown (G2 already computes), the expected correlation with BTC, and the exact decision rule ("fail if cumulative return below p2.5 path on day N"). The seal should include the code/config sha256 manifest, as reference_daily_v1.json already does. Add an external anchor: OTS proof files committed in a separate repo or published (e.g. to a second account/gist/email to a third party) so the author cannot silently rewrite.
- Counting watches: ~15 simultaneous watches means about 15 comparisons; apply BH or Bonferroni to forward verdicts, or the forward test inherits a multiple-testing problem. review_methods.bh_family exists.
- Because the funding-carry claim was reversed by a later test, at least the original "all passed" decision was based on an unreplicated construction; so prediction-sealing should apply to the claims "trend ~1.2 on consistent venues" with explicit forward falsifier bands.

### Gaps
- Could not run git (no Bash) to count tags, signed commits, or the order of declaration vs data-end commits; the claim "declared before data" for each registration should be verified from `git log --format='%H %ad %G?'`.

## 5. Third-party humans/tools as arbiter

### Takeaway
No independent replication, external review, or verified third-party track record is present in the repo as far as seen. These are the strongest arbiters against shared-assumption errors, but they are slow and each has limits.

### Cited Findings
- Repo contains discovery_v2 adapters comparing against external engines (Freqtrade, Nautilus calibration scripts: run_freqtrade_signal_calibration.py, run_nautilus_signal_calibration.py, run_nautilus_execution_calibration.py, compare_external_engine_calibration.py) — [research/discovery_v2/adapters](/home/user/orderflow_edge_lab/research/discovery_v2/adapters). This is an external-tool arbiter, but for the intraday ema-atr frozen candidate, not for the daily multi-premia books (I saw no equivalent in file names).
- truncation_check is explicitly modelled "after freqtrade's lookahead-analysis" (an external tool's method re-implemented, not the external tool itself).
- A Kronos external-model forecast evaluation and several third-party-ish sentiment tests exist in research/ but are not arbiters of the portfolio books.

### Inferences
- Clean-room reimplementation: give a spec (one page, no code: universe rule, signal definitions, rebalance, cost model) plus raw data hashes to someone (or an independent run of a different engine such as vectorbt/bt/Freqtrade backtesting, or a different LLM session with no repo access) and compare daily return series: require correlation > 0.98 and annual return gap < the stated tolerance. Value: catches spec-vs-code bugs. Limit: a person who only gets the spec shares the spec's flaws (e.g. the funding-source mismatch would NOT have been caught by clean-room replication using the same data); and an AI re-implementer is not independent of "the AI assistant's judgment", the thing the user wants to exclude.
- External code review: share a minimal repo of the evaluator (data loading, cost, funding sign convention, rebalance timing) with a quant developer; use a pre-written checklist (funding sign, timestamp alignment of funding vs bar, delisted coins, point-in-time universe, survivorship, fee side). Limit: reviewers rarely audit 200 test files; scope them narrowly.
- Verified live track records (background knowledge, unverified here, no source fetched): exchange copy-trading leaderboards and Darwinex-style broker-verified records provide real fills but have survivorship/incubation bias and require live money, which violates the repo's live-execution boundary; Numerai-type tournaments need data/model fit to their targets. They do not apply to a cost-free paper research programme. They are for a future promotion step only.
- Practical ranking by information per cost for this branch: (1) vendor-independent price/funding reconciliation, (2) planted-signal and positive-control tests, (3) OTS-sealed forward bands, (4) narrow human review of cost/funding/timing code, (5) clean-room replica, (6) live verified track record (only after explicit user approval).

### Gaps
- No fetched sources on Numerai/Darwinex/copy-trading verification mechanics; omitted rather than guessed.

## 6. Status of arbiters in the repo (present / partial / absent)

Based on files seen; not run.

| Arbiter | Status | Evidence |
| --- | --- | --- |
| Look-ahead truncation invariance | Present | src truncation_check.py; tests/test_truncation_invariance.py |
| Null/matched-random p-values, BH, deflated Sharpe, single-look guard | Present | review_methods.py |
| Pre-registration declared in git before run | Present (author-controlled) | commit ids in fast_gates RESULT.md; config/*.json; tests/test_preregistration.py, test_freeze_manifest.py exist |
| Trial ledger | Present | research/strategy_search_v3/trials.jsonl, research/lsk_conditional_v1/holdout_trial_ledger.json, DISCOVERY_LEDGER_MANIFEST |
| Paper vs own replay (G1) | Present but not independent | calibration.json G1 corr 0.9992, TE 0.34%/yr |
| Forward breakage alarm (G2 bootstrap envelope) | Present | calibration.json, false alarm 3.6% |
| Consistent-venue replication (Binance, Bybit, Hyperliquid, MEXC funding) | Present (author-run but independent data) | fast_gates RESULT.md; venue_replication.json; hyperliquid_venue_check.json |
| Reference series with code/config/data hashes | Present for near-miss | reference_daily_v1.json |
| Independent vendor reconciliation of forward book prices/funding | Absent (partial for Binance archives via binance_futures_archive.py, binance_spot_archive.py, okx_funding_archive.py used as data inputs, not as audit) | Grep hits only in source adapters |
| Published-number known-answer test | Absent/partial (ctrend.py implements the paper; no test asserted against paper numbers that I saw) | tests/test_ctrend.py grep |
| Planted-signal end-to-end recovery | Absent or partial (unconfirmed; ~20 files mention placebo/synthetic-type terms) | grep |
| External cryptographic timestamp (OTS/signed tags) | Absent | no match in workflows/docs/src |
| External engine cross-check (Freqtrade/Nautilus) | Partial (intraday ema-atr candidate only) | discovery_v2/adapters |
| Independent human replication / external review | Absent | no artifact found |
| Verified live track record | Absent by design (live disabled) | AGENTS.md |
| Basis-decomposition test of the funding-artifact mechanism | Absent; mechanism labelled "unverified" | fast_gates RESULT.md |

## Claim-by-claim: what arbiter would settle each
- (a) Carry = funding-source artifact: already supported by three consistent-venue results (Binance S3 0.52 vs 1.62; Hyperliquid -0.19; MEXC-funding on untouched coins -0.18, t -2.20). Weaknesses to be aware of: untouched-coin MEXC test is only ~15 months; development-coin swap is NOT_MATERIAL; Bybit run is defective (58 coins); the mechanism is unverified. Settling arbiters: synthetic positive control, direct MEXC-vs-Binance basis decomposition, and OOS forward carry-leg P&L computed with MEXC funding (forward watches already do this).
- (b) Trend robust across venues Sharpe ~1.2: venue table shows S1 1.22 on Binance vs 1.17 MEXC, but Hyperliquid 0.65 vs 1.19 reference and Bybit 0.68 (defective), and 0.42/0.40 and 0.65/0.56 in the 15-month funding check. So "robust across venues" is not uniformly supported by the repo's own tables; Hyperliquid and Bybit show ~0.65. Sharpe 1.2 cannot be confirmed forward in under ~5 years (power section). Literature arbiter: CTREND and time-series momentum papers (numbers not retrieved).
- (c) Daily P&L computed correctly: arbiters are vendor reconciliation and planted/known-answer tests; G1 is self-consistency only.
- (d) "No strategy profitable yet": cannot be confirmed by more tests; it is the null that survives absent out-of-sample evidence. Its truth is safe by default per AGENTS.md rules; the risk is the opposite error (failing to detect a real but small edge), which low power implies.
