# Professional practice for a research program at the "many forward watches, one downgraded lead" stage

Scope note. Web fetches of two secondary pages failed (DNS), so several formulas below come from the original papers as I know them, not from a page I read this session. They are marked [formula from memory of the paper; verify]. Numeric examples marked [my derivation] are my own arithmetic from those formulas. No source I found applies anytime-valid methods to Sharpe ratios specifically.

## 1. Can an N-day forward record ever answer the question? (PSR, MinTRL, sequential testing, kill/continue rules)

### Takeaway
At roughly 16 days, and even at the 180 or 365-day review horizons, a daily-return Sharpe test has almost no power unless the true Sharpe is above about 2.5 to 3.5. The forward watches can falsify gross implementation failure or a collapse, but cannot confirm a Sharpe-1 premium. Professionals therefore pre-commit what a watch is able to decide (power or MDE statement, futility boundary) before it starts, and use the forward period mainly for implementation, attribution and tail-envelope checks.

### Cited Findings
- Bailey and López de Prado's "The Sharpe Ratio Efficient Frontier" (Journal of Risk) introduces the Probabilistic Sharpe Ratio. The abstract says PSR establishes the track-record length needed to reject, at a given confidence, that a measured Sharpe is below a threshold. Negative skew or high excess kurtosis lengthens the required record. — [IDEAS/RePEc listing](https://ideas.repec.org/a/rsk/journ4/2223785.html), [Risk.net](https://www.risk.net/journal-risk/2223785/sharpe-ratio-efficient-frontier)
- The Deflated Sharpe Ratio (Journal of Portfolio Management, 2014) extends PSR to correct for selection bias under multiple testing and non-normality. — [SSRN 2460551](https://papers.ssrn.com/abstract=2460551)
- Formulas [from memory of the paper; verify]. With per-period Sharpe SR_hat, sample length T, skew g3, kurtosis g4 (non-excess):
  - PSR(SR*) = Phi( (SR_hat − SR*) · sqrt(T−1) / sqrt(1 − g3·SR_hat + ((g4−1)/4)·SR_hat²) ).
  - MinTRL = 1 + (1 − g3·SR_hat + ((g4−1)/4)·SR_hat²) · (z_(1−alpha) / (SR_hat − SR*))², in the same units as the Sharpe is measured (daily SR gives days).
  - Normal iid special case: Var(SR_hat) ≈ (1 + SR²/2)/T, with SR and T in matching units.
- Worked numbers [my derivation, iid normal, annualized SR with T in years, one-sided 95% so z=1.645]:
  - To reject SR=0 when true SR=1: T ≈ 1.645² · (1 + 0.5) / 1² ≈ 4.1 years (about 1,480 days). Two-sided 95% (z=1.96): about 5.8 years.
  - SR=0.5: T ≈ 2.706 · 1.125 / 0.25 ≈ 12 years.
  - After a 16-day record, the SE of annualized SR is about sqrt(365/16) ≈ 4.8. A realized "Sharpe 1" is z≈0.2, and a realized Sharpe of −2 to −3 is also well within noise of a true Sharpe of +1.
  - Minimum detectable true Sharpe at 5% one-sided size and 80% power is roughly 2.49/sqrt(T_years): about 3.5 at 180 days, about 2.5 at 365 days. Fat tails, autocorrelation and the Sharpe-estimation-error term all push this higher (MinTRL grows as skew falls or kurtosis rises).
  - Note that crypto trading calendars are 365 days; annualizing with 252 understates T.
- Anytime-valid inference: Howard, Ramdas, McAuliffe and Sekhon (2021) gave time-uniform nonparametric confidence sequences for bounded means; Waudby-Smith et al. gave asymptotic (CLT-based) confidence sequences (Annals of Statistics 52(6), 2024); Wang and Ramdas revisit Lai's Gaussian confidence sequence with unknown variance (arXiv 2310.03722). Confidence sequences hold at all times simultaneously, so repeated monitoring does not inflate false alarms. — [Wang and Ramdas](https://arxiv.org/html/2310.03722v3), [Annals of Statistics](https://projecteuclid.org/journals/annals-of-statistics/volume-52/issue-6/Time-uniform-central-limit-theory-and-asymptotic-confidence-sequences/10.1214/24-AOS2408.full), [Howard et al.](https://arxiv.org/abs/2103.06476v5)
- Software: `glide-py` implements an anytime-valid empirical-Bernstein confidence sequence. — [glide-py docs](https://glide-py.readthedocs.io/en/latest/api/confidence_sequences/). (The `confseq` package accompanies Howard et al.; I did not open its docs this session.)
- PSR/MinTRL/DSR libraries: `jsharpe` (PSR, MinTRL, non-Gaussian and autocorrelation adjustments), `sharpebench` (min_track_record_length, deflated_sharpe_ratio, expected_max_sharpe with n_trials), `pypbo` (PSR, MinTRL, MinBTL, DSR, PBO; old pinned statsmodels, tests incomplete), backtrader's `sharpe_ratio_stats`. Maintenance not verified. — [jsharpe](https://pypi.org/project/jsharpe), [sharpebench](https://pypi.org/project/sharpebench/), [pypbo](https://github.com/esvhd/pypbo)
- Repo status: the repo already has stationary/block-bootstrap drawdown envelopes computed once from pre-start data, with as_backtested and zero_edge (demeaned) variants (`scripts/build_forward_drawdown_envelopes.py`); `assert_single_look`; and a null-consistent deflated Sharpe (`review_methods.deflated_sharpe_null_consistent`). I found no MinTRL/PSR power statement, sequential/futility rule, or confidence-sequence code in the files I grepped (`review_methods.py`, `RESEARCH_PROTOCOL.md`, `SESSION_STATE.md`).

### Inferences
- A concrete "decision-grade or not" label per watch should come from a pre-computed MDE: if MDE at the review date exceeds any Sharpe the strategy could plausibly have (post-haircut, say 0.5 to 1), the watch is a monitor, not a test. This is derivable now with no new data.
- The repo's "single look" rule is the conservative alternative to sequential testing: valid, but it forfeits the ability to stop early on clear failure. A confidence sequence or a one-sided futility bound (stop if the upper bound of the SR confidence sequence falls below the minimum economically useful Sharpe) adds early kill without alpha inflation. Pre-register it as an additional rule, not a change to existing single-look watches.
- A professional kill rule is asymmetric: kill early on implementation failure or when the realized path breaches the pre-computed zero-edge or as-backtested envelope tails; do not "confirm" early.
- Consider a Bayesian prior framing (backtest Sharpe shrunk by a decay factor, see section 4) so the forward record updates a prior of about 0.3 to 0.6 Sharpe, not a null of zero versus the backtest value.

### Gaps
- Exact PSR/MinTRL formulas were not re-verified against the paper text this session (fetch failed).
- No source found applying e-values or confidence sequences to Sharpe/return-stream monitoring in finance; applying them is an adaptation (bounded-return or sub-Gaussian assumptions need justification for fat-tailed crypto).
- SPRT specifics (Wald boundaries) not researched this session.

## 2. Managing ~15 concurrent watches (multiplicity, selection bias, triage)

### Takeaway
Treat the 15 watches as one declared family with one pre-registered summary rule. Emphasizing the best survivor afterward recreates selection bias, so correct for the full count (or the effective count after accounting for correlation) and triage out watches that cannot be decision-grade.

### Cited Findings
- Harvey, Liu and Zhu (RFS 2016) catalogue about 316 factors and argue a new factor should clear t > 3.0 (p about 0.0027) rather than 2.0. Counts vary slightly across sources. — [NBER w20592](https://nber.org/papers/w20592), [summary](https://www.cxoadvisory.com/big-ideas/taming-the-factor-zoo/)
- Harvey and Liu "Backtesting" (JPM 2015) proposes Bonferroni, Holm and BHY haircuts to Sharpe ratios; per a secondary summary, haircuts are almost always above 50% for gross SR below 0.4 and at most about 25% for SR above 1.0, so a flat 50% rule is lenient for weak and harsh for strong strategies. Code exists in a third-party quantstrat R sandbox. — [Duke copy](https://people.duke.edu/~charvey/Research/Published_Papers/P120_Backtesting.PDF), [CXO summary](https://www.cxoadvisory.com/big-ideas/navigating-the-data-snooping-icebergs/), [quantstrat profitHurdle](https://rdrr.io/github/braverock/quantstrat/man/profitHurdle.html)
- A 2022 paper argues most claimed cross-sectional findings are likely true, a dissenting view on the proliferation-of-false-findings consensus (Chen and Zimmermann, arXiv 2206.15365 per the search listing). — [arXiv](https://arxiv.org/pdf/2206.15365)
- Repo status: `bh_family` (BH at q=0.10, one declared family) is in `review_methods.py`; the protocol requires one declared family per registration. The multiplicity unit is per-registration, which I did not see extended across all concurrent watches.

### Inferences
- Pre-commit a single cross-watch summary: for example, "the pre-declared primary watch is X; all others are secondary and reported as a family with BH." Report the full set always, with no ranking by P&L.
- Many of the 15 are highly dependent (blend, trend core, vol-target and cross-asset trend share legs and BTC beta). Effective number of independent bets is far below 15; estimate it from the correlation matrix of daily watch returns (eigenvalue-based N_eff), and use it for DSR's n_trials (a conservative choice is the raw count).
- Triage criteria professionals use: (a) MDE above plausible edge, so non-decision-grade; (b) redundancy (correlation above about 0.9 with a retained watch, keep one representative); (c) known-failed or near-miss designs with no prior positive evidence (counted trials mostly FAIL), which add trials and no evidence; (d) watches whose decision would never change an action; (e) watches with different review dates, since staggered looks encourage opportunistic early reading. Stopping a watch should be pre-declared and logged, never silent, and the stopped watch stays in the trial count.
- Leave-one-out sanity: any "best watch" claim should be reported as an order statistic of the family (expected max of N noisy series) with the DSR-style expected-max benchmark, which the repo already has in `expected_max_normal_z`.

### Gaps
- No practitioner source found that specifically addresses "portfolio of paper forward tests" governance; the above is inference from the multiple-testing literature.
- Effective-N methods for correlated strategy families not sourced this session.

## 3. Attribution and pre-mortem: forward P&L versus the backtest's predicted distribution

### Takeaway
Professionals decompose forward returns into market beta, known factor exposures, costs and funding, and a residual, and compare realized path statistics to a pre-computed envelope. The repo already has the envelope; attribution to beta/factor/funding and cost legs is the likelier gap.

### Cited Findings
- The repo computes block-bootstrap drawdown envelopes once from pre-start data, with a zero-edge variant, so forward drawdowns can be read against both "backtest is true" and "no edge" distributions (`scripts/build_forward_drawdown_envelopes.py`, `orderflow_edge_lab.drawdown_envelopes.bootstrap_envelopes`).
- Liu, Tsyvinski and Wu (Journal of Finance 2022) find crypto market, size and momentum factors capture cross-sectional expected returns (sample 2014 to 2018, 109 coins growing to 1,583). — [NBER w25882](https://www.nber.org/papers/w25882.pdf), [SSRN](https://papers.ssrn.com/abstract=3379131)
- The repo's registration protocol already asks for raw, market/beta-adjusted and matched-control excess returns (`docs/RESEARCH_PROTOCOL.md`, item 9) and an action-matched null (999+ draws).

### Inferences
- Pre-mortem practice: before the review date, write the list of ways the result is expected to disappoint (beta drag in a down BTC tape, funding sign flips, correlation spike across legs, spread widening, data-venue mismatch as already found for carry) with a pre-registered diagnostic for each. Being down 2 to 9% at 16 days in a market with a down BTC move is expected to be mostly beta; test it rather than assume it.
- Regression attribution: daily watch return on BTC return (and a market-cap-weighted or equal-weight crypto basket, plus LTW size/momentum proxies if constructible), with HAC (Newey-West) errors via `statsmodels`. Report alpha with its CI, which at 16 days will be wide; the information is in the betas and the cost/funding legs.
- Funding and costs should be separate P&L ledgers (price P&L, funding P&L, fees, spread/slippage), so a repeat of the funding-source mismatch is visible as a ledger-level discrepancy before the Sharpe is computed.
- Compare realized forward returns to the backtest's predicted distribution by (a) percentile of realized cumulative P&L inside the bootstrap distribution at the same horizon, (b) realized drawdown versus envelope, (c) realized daily vol and turnover versus backtest values. Persistent vol/turnover mismatch signals implementation or regime differences even when P&L is uninformative.
- Expected-shortfall bands and PIT (probability-integral-transform) uniformity of daily returns against the backtest model are standard calibration checks; I did not source a specific crypto reference.

### Gaps
- I did not verify whether the repo already does BTC-beta regression on the live watches; the protocol requires it for registrations, but I did not read the forward report code.
- No source for factor-model attribution on 16-day windows.

## 4. Implementation fidelity (shadow versus backtest reconciliation, implementation shortfall)

### Takeaway
The cheapest high-information test available now is to run the backtest engine on the same day, same inputs, and require that it reproduces the forward book's weights, trades and P&L to tolerance. This answers a question that is decidable in days, unlike Sharpe.

### Cited Findings
- I found no primary or authoritative web source this session describing a named reconciliation standard for shadow-vs-backtest; this is general desk practice (the repo's docs refer to reconciliation evidence as a promotion requirement in AGENTS.md).
- He, Manela, Ross and von Wachter, "Fundamentals of Perpetual Futures": perpetual futures lack expiry convergence; funding keeps futures near spot; they report large Sharpe from a simple strategy even at high trading costs (v2 abstract; later versions may differ). — [arXiv 2212.06888](https://arxiv.org/abs/2212.06888v6)

### Inferences
- Reconciliation hierarchy: (1) signal parity (same features at the same timestamps), (2) position parity (target weights equal between engine and forward book), (3) fill/price parity (assumed versus actual or observed prices), (4) funding parity (venue-specific rate and timing, which is where the carry mismatch arose), (5) P&L parity. Any break is a defect investigated before interpreting performance.
- Implementation shortfall (Perold): decision-price P&L minus realized P&L, split into delay, spread/impact, fees and opportunity cost. For a daily-rebalance 70-coin book, measure signal-time vs execution-time price drift, and compare with the cost wall already computed in `cost_wall_bps`.
- Freeze a venue-consistency manifest (price source, funding source, symbol map, timestamps) per watch and assert equality in CI; the funding-source-check episode is precisely a missing assertion of this type.
- Point-in-time universe checks (listing/delisting, survivorship) belong here; the Zarattini, Pagani and Barbon crypto trend paper emphasizes a survivorship-bias-free coin dataset since 2015, reporting Sharpe above 1.5 on a top-20 liquid rotation after fees (abstract, not verified). — [IDEAS](https://ideas.repec.org/p/chf/rpseri/rp2580.html), [author page](https://abarbon.com/papers/catching-crypto-trends)

### Gaps
- Open-source reconciliation tooling for backtest/live parity: none identified; most desks build in-house. Not researched deeper.

## 5. The research process as the object of review (trial ledgers, forking paths, replication base rates, crypto evidence)

### Takeaway
The right prior for a new anomaly or blend is heavily shrunk. Published-anomaly base rates and decay imply a backtest Sharpe of 1 to 1.4 in-sample should be expected to deliver materially less live, and the repo's roughly 11 counted trials are a lower bound on the true search degrees of freedom.

### Cited Findings
- McLean and Pontiff (JF 2016), 97 predictors: returns fell 26% out-of-sample and 58% post-publication (earlier drafts reported different values, for example 35% and 56%). The authors treat the 26% as an upper bound for data-mining bias; decay is larger for predictors with higher in-sample returns. — [Ivey copy](https://ivey.uwo.ca/media/3775549/pontiff.pdf), [summary](https://academicnewsletter.sufe.edu.cn/info/359722)
- Hou, Xue and Zhang (RFS 2020): of 452 anomalies, 65% fail |t| ≥ 1.96 and 82% fail a multiple-testing hurdle of 2.78 once microcaps are mitigated; trading-frictions anomalies fail 96%. — [IDEAS](https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2019-2133..html), [NBER w23394](https://www.nber.org/papers/w23394.pdf)
- Harvey-Liu-Zhu t > 3.0 hurdle (see section 2).
- Crypto: LTW report market, size and momentum as the priced factors (see section 3); perpetual-futures funding and basis deviations are large and decline as markets mature (He et al. above); Zarattini et al. report trend ensembles with vol sizing (abstract-level claims, author-reported).
- Repo status: frozen thresholds, candidate freeze, holdout audit, trial ledger, BH family, DSR (null-consistent), CSCV/PBO and a Reality-Check-style block-bootstrap family test (`research/discovery_v2/PROTOCOL.md`, `discovery_v2_evaluation.py`), plus anti-gaming flags (scale invariance, concentration, boundary, cost wall).

### Inferences
- Keep the trial ledger honest: count variants that were considered and dropped before a formal run, any "near-miss" watches (they are searches), the data-venue choices, and the holdout peeks. Under the garden of forking paths, researcher choices (venue, universe size of ~70, daily rebalance, equal leg weights, vol window) are degrees of freedom; a robustness table across plausible alternatives, reported without selecting, is the professional counterpart.
- The downgraded holdout is an instance of a failure mode professionals call data-snooping through data: the holdout was "run once" but the data pipeline had a venue mismatch discovered afterward. Lesson: audit data lineage before the one-shot test, not after. Re-using that holdout after the correction is a second look; treat it as spent for confirmatory purposes.
- A decay-adjusted prior: apply a McLean-Pontiff-style discount (26% to 58%) and the Harvey-Liu haircut to the post-correction Sharpe of about 1; the resulting expected live Sharpe of well under 1 reinforces the section 1 power conclusion (the forward watch cannot resolve it in a year).
- Funding carry and trend are structurally motivated premia, which professionals weight more than data-mined signals; but carry is crowded and its sign and size are venue-dependent, so the venue-consistent estimate (not the earlier one) is the only admissible one.

### Gaps
- AQR, Man AHL, Two Sigma and Robeco/Research Affiliates practitioner pieces on live-vs-backtest decay were not retrieved this session. I do not have a verified citation for any specific firm claim, so none is asserted.
- Crypto-specific post-publication decay evidence: not found.

## 6. Tools (what exists, what each is for)

### Takeaway
Mature open tools cover PSR/DSR/MinTRL, block bootstrap, and performance reporting. Nothing mainstream covers reconciliation or multi-watch governance; the repo's in-house code is at or beyond typical open-source practice on selection-bias controls.

### Cited Findings
- `jsharpe`, `sharpebench`, `pypbo`, backtrader `sharpe_ratio_stats` — see section 1 for links and caveats.
- `glide-py` anytime-valid confidence sequence. — [docs](https://glide-py.readthedocs.io/en/latest/api/confidence_sequences/)
- quantstrat `profitHurdle` implements Harvey-Liu haircuts (R). — [rdrr.io](https://rdrr.io/github/braverock/quantstrat/man/profitHurdle.html)
- Not verified this session (from general knowledge, check before relying): `arch` (`arch.bootstrap`: StationaryBootstrap, CircularBlockBootstrap, MovingBlockBootstrap, optimal_block_length; SPA/StepM/MCS in `arch.bootstrap`), `statsmodels` (HAC OLS, multipletests for BH), `quantstats`, `empyrical`/`pyfolio` (unmaintained originals; community forks exist), `alphalens` (factor IC/quantile analysis; forks), `vectorbt`, `confseq`, mlfinlab (commercial/closed since 2021; its open implementations survive in forks and `skfolio`/`mlfinpy`-type projects).

### Inferences
- Use arch's `optimal_block_length` (Politis-White/Patton) to justify the bootstrap block length rather than a fixed value; sanity-check that the repo's `mean_block_days` is consistent with it.
- Prefer thin, tested in-house implementations of PSR/MinTRL (about 20 lines) cross-checked against `jsharpe` or `sharpebench` over adding dependencies; the repo already has pinned reviewable methods.

### Gaps
- Library maintenance status and licences not checked.

## Summary: done versus missing (against the repo, from files I grepped)

Already done: frozen thresholds, trial ledger, BH family, null-consistent DSR, CSCV/PBO and Reality-Check-style test, block bootstrap, one-time drawdown envelopes (as-backtested and zero-edge), action-matched null, single-look enforcement, anti-gaming flags, venue/funding source check.

Likely missing (not found in files I searched; confirm before acting): per-watch MDE or MinTRL statement; futility/early-kill boundary (confidence sequence or SPRT) separate from single look; cross-watch family declaration with effective-N; BTC-beta and factor attribution with separate price/funding/cost ledgers on every watch; daily backtest-engine-vs-forward-book reconciliation with a venue manifest assertion; decay-adjusted prior for the expected live Sharpe; watch triage log (stop/merge decisions recorded as ledger entries).
