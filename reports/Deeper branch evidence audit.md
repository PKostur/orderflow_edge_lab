# Deeper branch evidence audit

Branch `research/payoff-geometry-v1-1`, audit date 2026-10-16. Descriptive only. This file was committed with Section 0 alone before any result below was computed; the results sections were added in a later commit. Every test listed here is run once.

## 0. Pre-registration (written before any result)

### 0.1 Scope and access, as found before any computation

- Reachable: the full git history (unshallowed, 1172 commits on the branch), every committed file, GitHub run and artifact metadata through the GitHub API, PyPI.
- Not reachable from this session (proxy returns 403 on CONNECT): `data.binance.vision`, `fapi.binance.com`, `api.mexc.com`, `contract.mexc.com`, `api.hyperliquid.xyz`, and the GitHub artifact blob host (`productionresultssa1.blob.core.windows.net`). So the per-run forward report artifacts and all exchange data are unavailable here.
- Consequence fixed now, before any result: every test that needs those inputs is registered below with its full rule and marked DEFERRED. It is not run in this audit, and it may be run later exactly once, unchanged, when the hosts are allowed. Nothing is substituted with mocked data.
- Labels used in the results: VERIFIED (read from a file, or reproduced by a run in this audit), ARITHMETIC (derived; formula shown), UNVERIFIED (a reading not confirmed by a test, a recalled formula, or an unchecked tool), DEFERRED (registered, not run).
- Rules: no new strategies, no edits to frozen configs, modules or workflows, no production-code change, no live or paper order path. Test code lives only in the session scratchpad and is described in the report. Every test run below counts as an audit check, not as a strategy trial (none evaluates a trading rule for selection).

### 0.2 Part A. Decidability per watch

- Inputs: the review horizon of each forward watch as registered in its config (`review_after_days`, `review_after_calendar_days`, or `config/forward_formal_reviews_v1.json` `horizon_days`), year = 365 days.
- A1 (ARITHMETIC). Minimum detectable true annualized Sharpe at one-sided 5% size and 80% power, iid normal approximation: `MDE = (1.645 + 0.8416) / sqrt(T_years)`. Also the 50%-power, t = 2 form `2 / sqrt(T_years)` to reconcile with the repo's stated "about 2.8 at 180 days".
- A2 (ARITHMETIC). Years needed to reject SR = 0 for true SR in {0.5, 1.0}: at 50% power `T = 1.645^2 (1 + SR^2/2) / SR^2`; at 80% power `T = (1.645 + 0.8416)^2 (1 + SR^2/2) / SR^2`.
- A3 (VERIFIED by run). PSR and MinTRL with sample skew and kurtosis on every daily return series committed in the repo (the five series in `research/near_miss_forward/reference_daily_v1.json`). Formula (Bailey and López de Prado 2012, recalled, to be checked against the paper text if reachable): with per-period Sharpe `s`, skew `g3`, raw kurtosis `g4`, `n` periods, `PSR(s*) = Phi((s - s*) sqrt(n - 1) / sqrt(1 - g3 s + (g4 - 1)/4 s^2))`, `MinTRL = 1 + (1 - g3 s + (g4 - 1)/4 s^2) (z / (s - s*))^2`, `s* = 0`, `z = 1.645`. Cross-check: the same quantities from the repo's own implementation in `src/orderflow_edge_lab/review_methods.py` if it exposes PSR; otherwise from a second, independently written implementation using `scipy.stats` moments. Pass rule for the cross-check: the two PSR values agree within 1e-6 and the MinTRL values within 0.5%.
- A4 labelling rule: a watch is MONITOR if its 80%-power MDE exceeds 1.0 (the upper end of a plausible decay-adjusted Sharpe of 0.5 to 1.0), otherwise TEST.

### 0.3 Part B. Family and effective N

- B1 (DEFERRED). Effective N of the forward watches from the correlation matrix of their daily returns on common scored days: participation ratio `N_eff = (sum lambda)^2 / sum lambda^2` over the eigenvalues; BH at q = 0.10 across the family on one-sided Newey-West (5 lags) mean-return p-values; benchmark for any "best watch" claim = expected maximum of N_eff independent standard normals. Needs the forward artifacts.
- B2 (VERIFIED by run, partial substitute that is NOT the forward family). The same `N_eff` on the five committed pre-start daily series in `reference_daily_v1.json`, on their common dates. Reported as a property of those historical series only.
- B3 (VERIFIED by reading). A trial recount over the shared crypto data. Counting rule fixed now: (i) ledgered strategy-search trials as recorded; (ii) every other committed result file that reports a historical performance statistic for a distinct named rule or rule family counts as one family; (iii) where a grid is reported, the number of cells is listed separately as configurations. Report three numbers: ledgered trials, families, configurations. No family is excluded for having failed.

### 0.4 Part C. Reconciliation and attribution

- C1 (DEFERRED). Vintage rebuild: download every available run's report artifacts, diff `daily_returns` for each scored day across runs; a revision is any change above 1e-9.
- C2 (DEFERRED). Determinism: re-run each frozen forward module on re-fetched data at the same cut-off; pass if daily returns match the artifact within 1e-9.
- C3 (DEFERRED). Independent price and funding reconciliation: sample fixed now as all coins of the multi-premia universe present on Binance USDT-M, on every scored day from 2026-10-05 to the audit date. Tolerances: daily open-to-open return gap per coin <= 50 bps absolute (venue basis allowance); funding: sign agreement on >= 90% of coin-days, and per coin-day funding rate gap <= 5 bps. Output an exceptions list.
- C4 (DEFERRED). Attribution: HAC (Newey-West, 5 lags) regression of each watch's daily return on BTC's daily return; split into price, funding, fees and spread from the report fields.
- C5 (VERIFIED by run, substitute available now). Vintage consistency of the monitor record: from every `docs: state: monitor` commit in git history, extract each watch's reported `Nd cumulative%`. Flag a revision when two records for the same watch and the same scored-day count differ by more than 0.01 percentage points (the display rounding). Also flag a day count that decreases between consecutive monitor records.
- C6 (VERIFIED by run). Envelope position: place the latest monitor value of the blend (S4_blend) and trend core (combined) at its scored-day count inside the committed `research/forward_envelopes/envelopes_v1.json` percentiles for both variants (as_backtested, zero_edge). Report the band: below p5, p5 to p50, p50 to p95, above p95. Before using it, check that the monitor's book matches the envelope's book (`S4_blend`, `combined`); if not, report C6 as not comparable.
- C7 pre-mortem, written now: expected disappointments and the diagnostic for each. (1) BTC beta drag: C4 beta and BTC return over the window. (2) Funding sign flips on the carry leg: C3 funding sign rate. (3) Correlation spike across coins compressing XS spread: cross-sectional dispersion of daily returns (DEFERRED). (4) Spread widening on small caps: `research/cost_realism` snapshot versus assumed costs. (5) Venue mismatch: C3.

### 0.5 Part D. The next-day-open tradability mask

- D1 (VERIFIED by reading). Trace every function that uses `opens.loc[d].notna() & ret.loc[d].notna()` with `ret = opens.shift(-1) / opens - 1`, and every book that calls it (blend S2/S3, development scripts, human books, paper account, fast gates, any other caller found by grep).
- D2 (VERIFIED by run, synthetic). Mechanism test in scratch: a synthetic panel where one coin's last open is day d (delists after d). Run `xs_premia.run_xs` unchanged and a scratch variant whose mask is `opens.loc[d].notna()` only. Pass rule for "the mask uses future information": the coin is excluded on day d by the original and included by the variant, with every other input identical.
- D3 (VERIFIED by run, synthetic). Does the repo's truncation check flag it? Run `truncation_check.check_truncation` on `run_xs` (and on `multi_premia_human_forward._xs_weights` if its signature allows) over a synthetic panel with probe dates fixed now as every 7th date of a 120-day panel, seed 20261016. Positive control: a scratch function with a planted one-bar look-ahead (score uses `opens.shift(-1)`) must be flagged; negative control: a causal function must not be. Report whether `tests/test_truncation_invariance.py` covers `run_xs`.
- D4 (DEFERRED). Size on real data: paired replay of S2, S3 and S4 over the development window with the original versus the open-only mask on identical frozen MEXC inputs; report the difference in annualized Sharpe, mean daily return, turnover, and coins dropped per rebalance. Needs MEXC data.

### 0.6 Part E. Provenance and internal consistency

- E1 (VERIFIED by reading). Per forward module, whether its report carries commit SHA, config hash, code hash, data hash (grep of the output dict keys).
- E2 (VERIFIED by run). Declared before data: for each forward config, the first commit date that added it (full history) versus its `prospective_start_utc`; and the first GitHub run of its workflow that could score a day. Pass if the config commit precedes the start.
- E3 (VERIFIED by reading). Coverage of `config/frozen_manifest_v1.json` against the branch's forward configs.
- E4 (VERIFIED by run). The `forward_formal_reviews_v1.json` amendment dated 2026-09-29T21:45Z versus its registration note (2026-09-30): resolve from the git commit dates of that file.
- E5 (VERIFIED by reading, plus ARITHMETIC). Tension 1: list every place the superseded 2.09 / 4.48 and 1.39 / 3.16 figures are still used. Quantify the G2 alarm: with the registered `dev_daily_sd` 0.007152, simulate iid normal 180-day paths (20000, seed 20261004) at annualized Sharpe 1.39 and check the approximation against the registered thresholds (-0.13678, -0.10552). If both are within 20% relative, use the same approximation to report (a) the thresholds that the registered method would give at Sharpe 1.05, 0.67 and 0, and (b) the false-alarm rate of the registered thresholds when the true Sharpe is 1.05, 0.67 and 0. If the approximation misses by more than 20%, report direction only.
- E6 (VERIFIED by reading). Tension 2: quote the venue table rows for S1 (trend) on each venue and window from the committed result files, and list every document that states the trend leg is robust across venues.
- E7 (VERIFIED by reading). Unretained raw data per watch, and a cost estimate for retaining it (artifact size from the GitHub API times runs per day), as a recommendation only.

### 0.7 External arbiters

- X1. Independent vendor reconciliation = C3 (DEFERRED).
- X2. Planted-signal recovery: in scratch, add a known daily mean to an iid normal panel so the true annualized Sharpe of a long-only equal-weight book is 1.5 over 2000 days; pass if the measured Sharpe falls inside its 95% sampling interval (`1.5 +/- 1.96 sqrt((1 + 1.5^2/2)/T_years)`), and the null (mean 0) measures inside `0 +/- 1.96 / sqrt(T_years)`. This checks the audit's own measuring code, not the repo engines (the repo engines need market-shaped data and are covered by D2 and D3).
- X3. Sealed prediction file: write `research/audit_2026_10_16/prediction_seal_v1.json` holding the envelope percentiles at days 30, 60, 90, 180 for the two enveloped watches, the review rules, and sha256 of every frozen forward config. Attempt an OpenTimestamps stamp; if the calendar servers are unreachable, record that and keep the sha256 in git only (author-controlled, so weaker).
- X4. Narrow external review checklist (funding sign, timestamp alignment, point-in-time universe, fee side), written for a human reviewer; not run.
- No arbiter is reported as passed unless it was run in this audit.
