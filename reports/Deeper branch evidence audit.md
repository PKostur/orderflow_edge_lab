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

## 1. Results

Section 0 was committed as `7bee829` (2026-10-16T14:17Z) before any computation below. Scratch code: `part_a.py`, `part_b2.py`, `part_c5.py`, `part_d.py`, `part_e5.py`, `part_x2.py` in the session scratchpad (not committed; each is described where used). One correction was made during execution and is reported: the first C5 parse cut the monitor timestamp at the hour, which split one watch name; the regex was fixed and C5 re-run with the same rule. No other test was run twice.

### Part A. What each watch can decide

- A1, A2 (ARITHMETIC). All 16 forward watches are MONITOR under the pre-registered rule; none is a TEST. The 80%-power MDE is 3.54 at 180 days, 2.49 at 365 days and 5.01 at 90 days (canonical v3 companion). The repo's "about 2.8 at 180 days" is the 50%-power, t = 2 form (`2 / sqrt(180/365) = 2.85`), so the two figures agree once the power assumption is stated. Rejecting SR = 0 takes 4.1 years at true SR 1.0 (50% power) or 9.3 years (80%), and 12.2 or 27.8 years at true SR 0.5. TOM and the cross-asset watches score trading days, so their true MDE is somewhat higher than shown.
- A3 (VERIFIED by run). PSR and MinTRL on the five committed reference series. The cross-check passes: PSR from the audit's scipy implementation and from the repo's `deflated_sharpe_null_consistent(x, 1)` agree to 1e-16.

| Series (window) | Ann. Sharpe | Skew | Kurtosis | PSR(0) | MinTRL days (moments) | MinTRL days (iid) |
|---|---:|---:|---:|---:|---:|---:|
| cascade 1x (2023-07 to 2026-09) | 1.73 | 7.3 | 106 | 1.000 | 183 | 332 |
| cascade 2x | 1.66 | 8.1 | 128 | 1.000 | 194 | 361 |
| CTREND 1x (2022-06 to 2026-09) | 0.95 | 0.1 | 8.7 | 0.976 | 1104 | 1104 |
| trend core 1x (2023-01 to 2026-09) | 1.05 | -0.4 | 11.7 | 0.977 | 927 | 902 |
| trend core 2x | 1.02 | -0.3 | 11.3 | 0.974 | 977 | 956 |

  Reading: these are already-seen windows (the cascade's development window, Sharpe -0.12, is not in the file), so PSR here is not evidence for the rules. They show that even at a historical Sharpe near 1, a watch needs 2.5 to 3 years of forward days to reach 95% confidence, and that the cascade's extreme positive skew is what shortens its MinTRL.

### Part B. Family and effective N

- B1: DEFERRED (needs the forward artifacts).
- B2 (VERIFIED by run, historical series only). On the 1188 common days of the five reference series, N_eff = 2.79. The 1x and 2x versions are near copies (correlation 0.985 cascade, 0.998 trend core), and the three families are almost uncorrelated with each other (|r| <= 0.05). Five watched books carry about three independent bets.
- B3 (VERIFIED by reading; configuration count is a heuristic floor). Ledgered strategy-search trials: 11 (9 in `strategy_search_v1/trials.jsonl`, 2 in `strategy_search_v3/trials.jsonl`; the remaining ledger rows are ineligible candidates or leverage notes). Families evaluated on the shared crypto data outside the ledger: 21 (multi-premia blend and its human, robustness and stress variants; funding overlay; regime switch; trend channel exit; trend ensemble; chop-regime search; portfolio vol target; XS low-vol; strategy zoo v1 and v2; custom sentiment; Kronos; prop-firm v1 to v7; leverage bracket v1 and v2; trend-core leverage; human-constrained grid; payoff geometry; volatility-state D4; LSK conditional), plus the 157-batch orderflow discovery ledger. Configurations: at least 403 Sharpe-bearing result entries in those folders' JSON files plus 360 bracket cells (72 + 288), so at least about 760. Cumulative N = 11 is the ledger count, not the search size. Deflating with N = 11 understates the multiple-testing burden by an amount this audit cannot pin down, because many entries are sub-periods or neighbours of one rule.

### Part C. Reconciliation and attribution

- C1 to C4: DEFERRED (exchange hosts and artifact storage unreachable).
- C5 (VERIFIED by run). 249 monitor records from 29 monitor commits (2026-10-03 19:44Z to 2026-10-16 09:03Z), 10 watches. Day counts never decrease. There is one silent revision: the human 5-coin book at 14 scored days read -3.24% at 2026-10-13 22:32Z and -3.21% at 2026-10-14 06:32Z and 14:32Z. A scored day changed after it was first reported. The cause cannot be identified without the run artifacts (C1). Possible causes are a MEXC bar revision, a coin whose data arrived late, or the replay recomputing a day under the next-day-open mask (Part D). Nothing in the monitor or dashboard surfaces revisions today.
- C6 (VERIFIED by run). The books match (`S4_blend`, `combined`). At 16 scored days:

| Watch | Value | As-backtested p5 / p50 | Band | Zero-edge p5 / p50 | Band |
|---|---:|---:|---|---:|---|
| Blend S4 | -2.79% | -2.32% / +0.50% | below p5 | -3.53% / -0.75% | p5 to p50 |
| Trend core combined | -4.02% | -2.77% / +0.11% | below p5 | -3.45% / -0.58% | below p5 |

  Reading: one pointwise look at day 16, among 29 monitor looks, is not a verdict (the formal reviews are at 180 days and G2 is the registered alarm). But both lead watches are already outside the band their own backtest implies, and trend core is outside the zero-edge band too. This is the first quantity the next review should attribute (C4 beta and C3 venue checks).
- C7 pre-mortem: items 1 to 3 and 5 are DEFERRED with C3 and C4. Item 4: the only committed cost evidence (`research/cost_realism/snapshot_2026_09_26.json`) covers 15 mostly liquid instruments, all inside the assumed 20 bps round trip. The small caps that dominate the capacity study's impact (AKE, NIL, RARE, PHA, LSK) are not covered, so spread risk on the blend's tail coins is untested.

### Part D. The next-day-open tradability mask

- D1 (VERIFIED by reading). The mask `opens.loc[d].notna() & ret.loc[d].notna()`, with `ret = opens.shift(-1) / opens - 1`, appears in four places: `xs_premia.run_xs` (line 54), `multi_premia_human_forward._xs_weights` (line 43), `scripts/multi_premia_human_eval_2026_09_28.py` (line 71), and `scripts/xs_low_vol_eval_2026_09_28.py` (line 32). Books that inherit it:
  - through `run_xs`: the blend watch (`multi_premia_forward` S2 and S3, hence S4), the zoo-mirror watch, strategy zoo v1 and v2, the development, robustness and stress scripts, and the Kronos evaluation;
  - through `_xs_weights`: the human books, the paper account, paper-fill scenarios and (via reports) fast gates G1.
  So the blend's development Sharpe, its holdout and its forward watch all share the mask, not only the human watch.
- D2 (VERIFIED by run, synthetic). Pass: the mask uses future information. A coin with the top momentum score on day d, whose last open is day d, gets weight 0 under the original and 0.25 under the open-only variant. One other coin's weight changes, and `run_xs`'s day-d return differs (-0.027% against -0.093%). Only that day differs. One more thing appeared: under the open-only variant, the delisting coin's missing return is filled with 0, so removing the mask alone would also be wrong. A correct successor needs an explicit delisting settlement rule (last traded price or a stated haircut).
- D3 (VERIFIED by run, synthetic). Neither form of the repo's truncation check detects this mask, so no test can catch it today.
  - At lag 0 the check flags 15 of 16 probes. This is the known last-day effect the repo's existing test documents, and it fires on every coin, so it is not specific to delisting.
  - At lag 1, the form the repo uses to call the legs causal, it passes everywhere, including a probe placed on the delisting day.
  - The planted one-bar look-ahead is flagged (positive control), and causal momentum passes (negative control). The check works as designed but cannot see this kind of look-ahead.
  - `tests/test_truncation_invariance.py` tests the scores and `coin_targets`, not `run_xs`. It records the mask as "documented, not a lookahead", and D2 shows that label is too generous.
- D4 (size on real data): DEFERRED. The bias acts only on rebalance days just before a delisting or data hole, so it is probably small. Its direction is unknown: dropping a soon-delisted name from the short side removes a likely winner trade.

### Part E. Provenance and internal consistency

- E1 (VERIFIED by reading). Only `near_miss_forward`, `fade24_forward` and `tradfi_perps_forward` write a config hash and data digests into their reports, and `hyperliquid_vaults` writes one digest. No forward report writes a commit SHA or a code hash. The blend, human, paper account, zoo, prop paper, fast gates, TOM, trend portfolio, cross-asset (and so trend core), vol-target and canonical v3 reports carry none. The GitHub artifact metadata does bind each artifact to its run's head SHA (`workflow_run.head_sha`), so the link exists outside the file for as long as the artifact lives.
- E2 (VERIFIED by run). Pass. Every forward config was first committed before its `prospective_start_utc` (lead times 15 hours (canonical v3) to 6 days; news sentiment 31 days). The only later edits (paper account, fast gates, liquidation flow) were also committed before their starts. For the 11 watches whose import closure was checked (blend, human, paper account, trend core via cross-asset, vol-target, zoo, fast gates, trend portfolio, prop paper, TOM, canonical v3), no module in the closure has a commit after that watch's start; near-miss, fade24, TradFi and liquidation flow were not checked. Caveat: these are git committer dates, which the author controls. Push times or an external timestamp would be the independent check, and neither is available here.
- E3 (VERIFIED by reading). `config/frozen_manifest_v1.json` hashes 13 older configs (discovery, regime, session, conditioning, LSK) and none of the branch's forward-watch configs. The seal in X3 now records sha256 for 72 configs whose status begins FROZEN or DECLARED.
- E4 (VERIFIED by run). `forward_formal_reviews_v1.json` was first committed at 2026-09-29T22:01:57Z (`12dc796`), and the amendment was committed at 2026-09-29T23:31:02Z (`e0e219b`). The amendment's recorded date (2026-09-29T21:45Z) is 16 minutes before the file existed, so it is mis-stamped by about 1h46m. The substantive claim still holds: the commit is 29 minutes before the first blend, human or trend-core day could be scored (stamps after 2026-09-30T00:00Z). The "Registered 2026-09-30" note uses local time.
- E5 (VERIFIED by reading, plus ARITHMETIC).
  - Superseded figures in live use: `config/fast_gates_v1.json` calibrates G2 at Sharpe 1.39 and records `dev_sharpe_raw` 2.0879. `scripts/dashboard_snapshot.py` lines 45 and 49 show the 1.39 / 3.16 and 2.09 / 4.48 rows with verdict "pass". The 1.39 row carries a "not decision-grade" note; the 2.09 row's note reads "robust to neighbours 1.6–2.2", with no funding caveat. `SESSION_STATE.md` line 42 still states "dev Sharpe 2.09 (t 4.48), robust to neighbours" without the funding caveat. Other mentions are historical result documents and benchmarks.
  - G2 quantification: the iid normal approximation is within the 20% registered bound (13.7% on drawdown, 19.0% on rolling 60d), so it is used. It runs deeper than the bootstrap (8.4% false alarm at 1.39 against 3.6% registered), so read the following as relative changes. Relative to the alarm's design point, the registered thresholds' false-alarm rate rises 1.4x if the true Sharpe is 1.05, 2.0x at 0.67 and 3.3x at 0. Equivalently, the method would set the drawdown threshold about 1.2, 2.6 and 5.4 points deeper at those Sharpes.
  - Reading: G2 is calibrated to a blend that the repo's own later tests no longer support. Its stated "<= 5% false alarm" holds only if the true Sharpe is 1.39. At a corrected Sharpe near 1 it alarms more often than stated. That is the conservative direction for a breakage alarm, but it should be stated in the review.
- E6 (VERIFIED by reading). This corrects my earlier report (`reports/Deeper research branch review.md`).
  - "Trend (S1) is robust to both checks" in `research/fast_gates/RESULT.md` and SESSION_STATE.md refers to robustness to the funding swap. That claim holds: S1 is 0.42 to 0.40 on development coins and 0.65 to 0.56 on untouched coins when Binance funding is replaced by MEXC funding.
  - Across venues, Binance gives S1 1.22 against 1.17 for MEXC on the same coins. Bybit gives 0.68, from a defective run with 58 of 70 coins.
  - The Hyperliquid 0.65 against 1.19 comparison is not like-for-like: Hyperliquid covers 1158 days from 2023 and the reference covers 2229 days from 2020. The only committed common-days comparison is for S4.
  - So "the trend leg is weaker on other venues" is not established. What is established is that S1 was weak in 2025-06 to 2026-09 on both funding sources (0.40 to 0.65).
  - S1 on Hyperliquid's common days is DEFERRED.
- E7 (VERIFIED by API, recommendation only). Report artifacts expire 90 days after creation (`expires_at` = created + 90 days on the latest blend run). The earliest blend forward-day artifacts (2026-09-29) expire around 2026-12-28. The blend workflow has run 54 times in about 17 days, roughly 3 runs a day, at about 11 KB per artifact. Retaining a daily input digest plus compressed bars, funding and per-day weights would cost little storage. The real constraints are the 90-day expiry and the lack of a vintage archive.

### External arbiters

| Arbiter | Status in this audit | Result |
|---|---|---|
| X1 independent vendor reconciliation (C3) | DEFERRED | hosts blocked |
| X2 planted-signal recovery (audit code) | run | PASS by rule: true 1.5 measured 0.68 (interval 0.28 to 2.72); null measured 0.43 (interval -0.84 to 0.84). The width of the interval is itself the Part A point. |
| X3 sealed prediction file | written, `research/audit_2026_10_16/prediction_seal_v1.json`, sha256 `ffdd23f5…dd720` | OpenTimestamps not stamped: calendar servers blocked; git-only, author-controlled |
| X4 external review checklist | written below, not run | n/a |
| Repo test suite on this commit | run | see Section 2, item 11 |

X4 checklist for a human reviewer (scope: the blend, paper account and trend core code paths, about 600 lines):
1. Funding sign: a long position pays positive funding; check `run_xs` `(w * f).sum()` against MEXC's sign convention.
2. Timestamp alignment: confirm the funding print at the 00:00 bar is charged to the day it is earned, not the next day.
3. Point-in-time universe: the next-day-open mask (Part D) and any universe filter using a full-history length (`len(f) >= 250` in `coin_targets`) must be checked against the trading date.
4. Fee side and size: taker on every rebalance, 20 bps round trip in development against `max(taker, 2bp) + 5bp` in the paper account.
5. Delisting settlement: what return a held coin gets on its last day.

## 2. Findings

What the live claims actually support. The forward watches can detect breakage but cannot confirm an edge before about 2029. Two of them already sit below the 5th percentile of their own backtest envelopes. The headline historical numbers they were built on are superseded and still drive the G2 calibration and the dashboard. The blend's cross-sectional legs share a confirmed one-day survivorship look-ahead, of unknown size, that the repo's look-ahead test cannot detect. Every forward config and watch module was in place before its start.

1. No watch can test a Sharpe-1 edge in its review window. All 16 are monitors (A1).
2. Blend and trend core are below the as-backtested p5 at day 16, and trend core is below the zero-edge p5 too (C6).
3. One silent revision of an already reported day exists, and nothing in the monitoring chain surfaces revisions (C5).
4. The next-day-open mask is in `run_xs`, so it affects the blend's development, holdout and forward series. It uses future information (D2), the truncation check is blind to it (D3), and a simple removal would credit delisting coins 0% (D2).
5. Trial accounting: 11 ledgered trials, against at least 21 unledgered families and at least about 760 configurations (B3).
6. Five reference books carry about 2.8 independent bets (B2).
7. Frozen-before-start holds for every watch config and code path (E2). The formal-review amendment is mis-stamped but still precedes the first scorable day (E4).
8. Most forward reports carry no provenance hash, the frozen manifest omits every forward config, and artifacts expire after 90 days (E1, E3, E7).
9. G2's false-alarm statement holds only at Sharpe 1.39 (E5).
10. Correction to my earlier report: "trend robust" refers to funding, and that holds. A cross-venue weakness of the trend leg is not established (E6).

Unresolved (DEFERRED, rules fixed in Section 0): B1, C1 to C4, D4, X1, and S1 on Hyperliquid common days. They need `data.binance.vision`, `fapi.binance.com`, `api.mexc.com`, `contract.mexc.com`, `api.hyperliquid.xyz` and the GitHub artifact storage host (`*.blob.core.windows.net`) to be allowed, or a run on your machine. Each runs once, unchanged.

Decisions for you (none acted on):
1. Merge main into this branch (clean merge, 101 commits behind).
2. Open a landing PR to main, which would also deliver the backtest-workflow fix main still lacks.
3. The TradFi B1 rule for a symbol permanently missing on Yahoo.
4. Whether a successor version should fix the mask with an explicit delisting settlement rule. The frozen watches stay as they are.
5. Whether to download and archive the forward artifacts before the first ones expire around 2026-12-28.
6. Whether to allow the blocked hosts so the deferred tests can run.

## 3. Recap

| Claim | Evidence layer used | Result | Arbiter | Label |
|---|---|---|---|---|
| Watches can decide the edge question | registered horizons | No: all 16 MONITOR | arithmetic, PSR cross-check | ARITHMETIC / VERIFIED |
| Forward results in line with backtest | monitor history, committed envelopes | Blend and trend core below as-backtested p5 at day 16 | envelope file (pre-committed) | VERIFIED |
| Reported forward days are stable | 29 monitor commits | One silent revision (human book, 14d) | git history | VERIFIED |
| Mask is "not a lookahead" | code, synthetic run | Refuted: future information used; truncation test blind | positive/negative controls | VERIFIED |
| Mask size | none available | Unknown | paired replay | DEFERRED |
| Cumulative N = 11 | ledgers, result folders | Floor; at least 21 families, at least about 760 configurations | file reading | VERIFIED (config count heuristic) |
| Frozen before start | full git history | Pass for all configs and code closures | git (author-controlled dates) | VERIFIED |
| G2 false alarm <= 5% | registered thresholds | Only at Sharpe 1.39; 1.4x to 3.3x higher below | iid approximation within 20% | ARITHMETIC |
| Trend leg robust | committed venue tables | Robust to funding; cross-venue weakness not established | file reading | VERIFIED |
| Prices, funding, P&L correct | none available | Not testable here | independent vendor | DEFERRED |
