# Public-strategy research: final development closure

## Decision

The original three-strategy lane is closed for promotion. Volume impulse and VWAP reversion failed development economics/robustness. Failed downside initially warranted further descriptive investigation but subsequently failed the independent-venue cost robustness study. **No surviving final candidate, v2 trading specification, prospective T0, watch or order path is justified.** Historical development completion is not a profitability or future-validation result.

This report reconciles the uploaded specification with the retained evidence through merged PR #154, plus a descriptive clock-attribution supplement. Original v1 definitions, evaluator, protocol and retained outcomes remain unchanged. All frozen lanes, payoff geometry and existing session/prospective watches are preserved. No Bollinger strategy was researched or added to this lane.

## Original exact v1 results

Binance Spot native UTC 8h data: BTCUSDT, ETHUSDT, SOLUSDT and LINKUSDT. Common range **2020-08-11T00:00:00Z through 2026-09-30T16:00:00Z**, 6,726 bars per symbol, zero internal gaps or forward filling. BTC/ETH/LINK raw coverage starts January 1, 2020; SOL listing availability sets the common start. Retrieval began October 10, 2026 at 08:30:24 UTC. Four raw-response hashes and four CSV hashes are in the [retained manifest](../artifacts/public_spot_8h_20261010/manifest.json).

The exact draft was run first, with spot long-only next-open entry and fixed hold, no intrabar stop assumption, per-symbol nonoverlap, 20bps assumed round-trip friction and identically timed BTC benchmark. Each strategy represents ETH/SOL/LINK. Costs are assumptions, not historically calibrated fills.

| Strategy | Signals / overlap skips / completed | Weeks | Gross / net20 / BTC net20 / excess bps | Equal-sleeve cumulative return / max drawdown | Final disposition |
|---|---:|---:|---|---|---|
| Volume impulse | 297 / 38 / 259 | 144 | 33.13 / 13.13 / -28.62 / 41.75 | +1.12% / -35.43% | Rejected as specified |
| Failed downside | 255 / 2 / 253 | 120 | 67.09 / 47.09 / 13.05 / 34.03 | +34.90% / -26.04% | Rejected for promotion after venue/cost failure |
| VWAP reversion | 3,519 / 945 / 2,574 | 300 | 11.12 / -8.88 / -6.02 / -2.86 | -75.35% / -86.47% | Rejected as specified |

Equal starting cash sleeves reinvest internally, without cross-symbol rebalancing. Serial-event compounding is a separate diagnostic and must not be called a portfolio return. There are no pending trades at the retained boundary.

| Strategy | Net bps at 10 / 20 / 30 / 40 / 60bps cost | Mean / median MFE bps | Mean / median MAE bps | Win rate / median net bps / PF |
|---|---|---|---|---|
| Volume impulse | 23.13 / 13.13 / 3.13 / -6.87 / -26.87 | 542 / 366 | -469 / -306 | 47.9% / -53.97 / 1.05 |
| Failed downside | 57.09 / 47.09 / 37.09 / 27.09 / 7.09 | 368 / 226 | -358 / -242 | 54.2% / 26.40 / 1.30 |
| VWAP reversion | 1.12 / -8.88 / -18.88 / -28.88 / -48.88 | 285 / 179 | -304 / -199 | 47.7% / -9.98 / 0.94 |

Worst/best trades, correct-direction frequency, adverse excursion in completed bars preceding the favorable candle, adverse excursion before exit and favorable movement after friction are retained in [full diagnostics](../artifacts/public_spot_8h_20261010/diagnostics_final.json) and explained in the [original development report](PUBLIC_STRATEGY_SPOT_8H_DEVELOPMENT_2026_10_10.md). Candle extrema are bounds, not achievable fills or known intrabar ordering.

## Robustness, controls and independent replay

UTC ISO calendar-week clusters pool simultaneous symbols. The fixed-seed 2,000 whole-week resamples, positive-week fractions, leave-one-week and leave-one-symbol results, yearly/regime/volatility splits, coin/month/week concentration and descriptive BTC beta sensitivity are all retained. Three-candidate Bonferroni-width 98.33% excess intervals are respectively **[-44.36,136.05]**, **[-34.29,113.86]** and **[-19.38,14.55] bps**. These are descriptive, not calibrated discovery tests or validated power guarantees.

The +7-bar timing controls have excess means -32.37/-32.69/+2.76bps. Five hundred same-symbol/week random timing placebos have mean excess +76.20/-16.68/-22.75bps; fractions meeting/exceeding the observed values are 86.8%/0%/0%. Placebos permit overlap and are not matched-state causal counterfactuals. They do not rescue failed standalone economics.

The nine one-parameter neighborhood cells (six additional cells) are fully disclosed, with no selected winner. **Retained Git evidence does not prove immutable pre-outcome preregistration of this optional grid:** code and outcomes first appear together in `825efea2da94a1094286c87b00eba077dc9c8a35`. Treat them as exploratory spent-data descriptions. They do not satisfy a formal confirmation gate, justify promotion or authorize retuning. The 25-source/seven-family selection history and minimum cumulative trading-cell count remain disclosed. No retrospective registration is fabricated.

The original baseline re-evaluation independently recomputed overlap/execution/returns but shared the v1 signal detector. True independently implemented streaming signal and opening-event semantics exist for failed downside in [PSR1 replay](../artifacts/public_failed_downside_feasibility_20261010/independent_replay.json): 255 signals, two skips and 253 completed events match the reference within 1e-9bps. No external Freqtrade or NautilusTrader parity run was completed. Since no final candidate survives, no external-engine final-candidate validation is asserted.

The [PSR1 feasibility study](PUBLIC_FAILED_DOWNSIDE_REPLICATION_FEASIBILITY_2026_10_10.md) found impractical precision for the +5bps hurdle and incomplete execution calibration. The separately designed [KuCoin replication](PUBLIC_KUCOIN_REPLICATION_2026_10_10.md) produced 214 trades, gross +24.5454bps, net20 +4.5454bps, net30 -5.4546bps and net40 -15.4546bps. Its excess interval crosses zero; leave-one-week removal reverses excess, reference20 portfolio loses 2.3125% and beta-adjusted intercept is negative. Same-period venue replication is development robustness, not additional independent future evidence. This closes the initially interesting failed-downside candidate without retuning.

## Clock and volatility-description supplement

The engine's `signal_time` is **candle completion**, equal to its earliest hypothetical next-open `entry_time`. The earlier all-signal hour counts are therefore correct for the completion clock, including overlap skips; they are not originating candle-open counts. Retrospective candle-open attribution must never be treated as an executable early signal.

| Strategy | Originating candle-open counts 00 / 08 / 16 UTC | Signal-completion counts 00 / 08 / 16 UTC | Completed entries: Asia only / Asia+London / New York only |
|---|---|---|---|
| Volume impulse | 54 / 139 / 104 | 104 / 54 / 139 | 94 / 42 / 123 |
| Failed downside | 84 / 78 / 93 | 93 / 84 / 78 | 93 / 82 / 78 |
| VWAP reversion | 1,300 / 1,078 / 1,141 | 1,141 / 1,300 / 1,078 | 887 / 964 / 723 |

[Session-clock supplement](../artifacts/public_strategy_completion_20261011/session_clocks.json) uses explicitly declared **fixed UTC point conventions**: Asia [00,09), London [07,16), New York [13,22). Thus an 08 UTC clock belongs to Asia and London; a 16 UTC clock belongs only to New York. London/New York overlap [13,16) contains no 8h grid point. Nonexclusive regional counts can exceed totals; exclusive membership counts reconcile exactly. These conventions are not exchange hours, do not adjust for DST, and cannot reveal intrabar timing or within-candle overlap performance. No session filter, PnL comparison, new trading cell or strategy was added.

The original volatility code used sample standard deviation of **29 prior 8h log returns**, although its retained note said 30. Its direction regime used a 30-bar close change. This is a description correction: old classifications/results are preserved, and no corrected split is selected or recalculated to improve performance.

## Follow-on studies and terminal state

- PSR3 monthly momentum state: rejected as specified.
- PSR4 BTC-relative state: rejected as specified.
- PSR5 eight-hour volume forecasting future volatility: rejected as specified. Aggregate MSE improvement 0.36809846%, below the 1% hurdle; descriptive 99% four-week interval [-0.59856917%,1.26697856%], with negative ETH improvement. The user's eight-hour research choice is complete and closed.
- PSR6 sparse minute source access: feasible access only; execution/prediction unconfirmed.
- PSR7 continuous minute coverage/power/execution audit: complete, research readiness blocked. 276 official checksums matched; 11,219,639 fully audited candles, 841 known missing minutes and 869,760 unquantified rejected-month slots; 271 verified shared weeks fail the fixed dependence scenario and do not establish independence. Historical execution remains unconfirmed. See [full audit](MINUTE_CONTINUITY_EXECUTION_V1.md).

The authoritative [trial ledger](../config/public_strategy_research_ledger_v1.json) records all terminal decisions. There is no finalist to freeze. Do not lower failed thresholds, add leverage, rename a failed rule as validated, or start an automatic watch. A later study requires a genuinely distinct falsifiable question, preregistration before its evaluation, adequate independent information and the required execution inputs.

## Requirement-by-requirement completion evidence

| Original requirement | Authoritative evidence / disposition |
|---|---|
| Refresh main, PR147, Actions and artifacts | PR147 merged at `9a413d82b01d8aa7469e0f9ad7d9192bd1754cb1`; PR148–154 merged; pre-audit main `d88331845040049fd974a8eabe5cfbd042d07ed4`; exact revision checks and remote verified release-manager reports |
| Auditable multi-year native Spot 8h history | Retained eight raw/CSV hashes, listing limit and gap-free common grid in source manifest |
| Exact unchanged draft first | V1 config/evaluator/protocol byte-identical to PR147; retained exact first-run event report |
| Counts, returns, costs, MFE/MAE and path limits | Exact event ledger and full diagnostics; explicit portfolio allocation and intrabar limits |
| Dependence, regimes, concentration and beta | Full diagnostics and original development report; 29-return description corrected here |
| Signal/entry sessions and relevant overlaps | Original completion-clock diagnostics plus explicit clock/overlap supplement |
| Meaningful negative controls | Matched BTC, shifted signals and 500 blocked timing placebos, with limitations |
| Optional bounded grid and trial accounting | Nine disclosed cells; exploratory qualification because immutable preregistration is unproven; no winner selected |
| Survival/rejection and final specification | All three rejected for promotion; canonical ledger and KuCoin closure; no fabricated v2 |
| Conditional future shadow | Not applicable: no survivor, no freeze/T0/watch or reused old prospective boundary |
| Practical independent final semantics | Failed-downside internal parity verified; no surviving final candidate/external parity claim |
| Tests/docs/artifacts/branch/commit/PR/clean merge | Retained merged studies and this completion supplement, with required CI and verified multi-agent gates |
| Frozen-lane and no-order invariants | 14 manifest paths plus v1 definitions/protocol unchanged; only descriptive supplement and documentation/index additions |

## Reproduce the supplement

```text
python -m orderflow_edge_lab.public_strategy_completion --config config/public_strategy_shadow_v1.json --exact-report artifacts/public_spot_8h_20261010/exact_v1_report.json --data-dir artifacts/public_spot_8h_20261010/aligned_csv --output runs/new-completion-audit/session_clocks.json
```

The command requires matching retained specification/source hashes and refuses to overwrite an output. It adds no network, trading, prospective or order functionality. Three tests verify half-open overlapping session boundaries, actual retained clock reconciliation and rejection of changed specifications. Required engineering tests, Ruff and independently verified local/remote multi-agent gates remain distinct from research survival.
