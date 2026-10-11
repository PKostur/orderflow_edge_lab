# Public Dual Thrust batch 9 results

One published-source default-intent mathematical adaptation was frozen before outcomes. No native Jesse route, order/cancel or fill parity is established. Historical development evidence is spent; no candidate is viable until separately frozen untouched future confirmation passes.

Baseline main `f311091f1eb1e6bf3ef453d289fe9bcf9d2eecd0`; design `43a385e9fe3af963a98dfb32f32be34c0de24106`; evaluator `9cde8ddc1316acf801150554e59cddd71773c49b`; evaluator SHA256 `2106de7e08d42106c970bfec1b2fc9c5222c0abd07e8845feae8af15a146b807`.

## Data and declared source adaptation

Binance Spot BTCUSDT, ETHUSDT, SOLUSDT, LINKUSDT:2023-04-01 through2026-09-30 inclusive,1,841,760minutes /3,837 eight-hour bars each. First eligible next-open entry2023-06-20T00Z after240closed bars. Unchanged longest common complete segment selected by quality, no repairs or2022bear coverage. BTC benchmark; three independent altcoin sleeves.

Pinned public Dual Thrust source preserves21bar inclusive available-history slices, .71up/.67down coefficients, LOWcolumn4 for down_max_high, strict thresholds around the dailyopen of signalbarOPEN UTC day, ATR14×2signalstop and2percent capital-cappedrisk. Selected helper417f876 and pinnedjesse_rust1.3.0wheel define an explicit hybridmath contract, not native source-runtime parity. ATR uses last240bars inclusivecurrent; early14startup follows selectedkernel. No target/trailing/timeout or heldflagstopreanchor. MIT2020jesse-ai; MichaelChalek attribution unverified. Bothgapmodels identical withsinglestop.

Three10000USDT researchsleeves. Source_quote=min((cash*.02/(signalclose-stop))*signalclose,cash); source_q=Decimalfloor8(source_quote/signalclose); q=Decimalfloor8(min(source_q,cash/(signalclose*(1+sidecost)))). Fixedatdecision; nextopen all-or-reject withoutresize/borrow/short/pyramid/orders. Stop=signalclose−2ATR, notfill-reanchored; invalidATR/stopreject. Scheduledsourcebearishclose firstatnextopen; otherwise immediateadverseopengap orfirstminute lowtouch activatesstop. Heldrawflags countedbeforeliquidation, no sameboundaryreentry. Costs20/40/60/80RTbps eachhalfside actualnotional. Realizedgap/cost riskmayexceed2percent. FundedBTCowncash, MFE/MAEbounds, cutoffCENSORED_MTM and8hclose drawdown.

## Frozen result

| Candidate | Completed / pending | Net40 / net80 bps | PF40 | ROI40 / DD40 | Placebo tail | Decision |
|---|---:|---:|---:|---:|---:|---|
| DualThrust8hPinnedKernelSpot | 24 / 1 | 604.229489 / 561.896897 | 2.462679 | 19.107295% / -17.085047% | 0.906000 | REJECTED_AS_ADAPTED |

Failed gates: all_symbols_positive, completed_events, entry_weeks, excess_descriptive_ci, net_descriptive_ci, placebo_tail.

Entry weeks 19, calendar weeks including zeros 172; descriptive97.5% intervals `{'net_bps': [-247.35362553883317, 1754.6488225461576], 'excess_lower_bps': [-852.620215043927, 538.2441015755157]}`. Fixed alpha0.025 is a conservative carryover for ONE new cell, not two registrations or global repeated-search inference. Worst leave-week mean 353.326066bps; positive year fraction 75.00%.

| Symbol | Admitted / completed / pending | Net40 bps | Flags |
|---|---:|---:|---|
| ETHUSDT | 10 / 9 / 1 | 1453.719732 | `{'raw_entry_flags': 20, 'accepted_entries': 10, 'held_entry_ignored': 10}` |
| SOLUSDT | 4 / 4 / 0 | 350.687668 | `{'raw_entry_flags': 5, 'accepted_entries': 4, 'held_entry_ignored': 1}` |
| LINKUSDT | 11 / 11 / 0 | -75.837343 | `{'raw_entry_flags': 14, 'accepted_entries': 11, 'held_entry_ignored': 3}` |

Seven-bar lag summaries: `{'conservative_limit': [{'admitted': 24, 'completed': 23, 'censored_mtm': 1, 'mean_net_bps': 196.0491114888758, 'median_net_bps': -466.431243862771, 'mean_completed_only_net_bps': 161.3385491452091, 'per_unit_profit_factor': 1.4997686320418946, 'cash_profit_factor_with_cutoff_marks': 1.1621904929543512, 'completed_cash_profit_factor': 1.0531112578895536, 'win_fraction': 0.3333333333333333, 'mean_gross_bps': 236.91503979143656, 'mean_btc_excess_lower_bps': -82.64507363260817, 'mean_btc_excess_upper_bps': -38.90010623781521, 'mean_mfe_lower_bps': 2372.0262768153916, 'mean_mfe_upper_bps': 2372.0262768153916, 'mean_mae_lower_bps': -518.8776118314375, 'mean_mae_upper_bps': -487.54680041419005}], 'opening_price_improvement': [{'admitted': 24, 'completed': 23, 'censored_mtm': 1, 'mean_net_bps': 196.0491114888758, 'median_net_bps': -466.431243862771, 'mean_completed_only_net_bps': 161.3385491452091, 'per_unit_profit_factor': 1.4997686320418946, 'cash_profit_factor_with_cutoff_marks': 1.1621904929543512, 'completed_cash_profit_factor': 1.0531112578895536, 'win_fraction': 0.3333333333333333, 'mean_gross_bps': 236.91503979143656, 'mean_btc_excess_lower_bps': -82.64507363260817, 'mean_btc_excess_upper_bps': -38.90010623781521, 'mean_mfe_lower_bps': 2372.0262768153916, 'mean_mfe_upper_bps': 2372.0262768153916, 'mean_mae_lower_bps': -518.8776118314375, 'mean_mae_upper_bps': -487.54680041419005}]}`.

All cost/gap cases, UTC session memberships, calendar clusters, source-state/symbol/year/weekday/hour, funded BTC, excursion and leave-out diagnostics remain retained.500 entry-week randomized controls rerun own position-dependent exits and duration; no observed endogenous lengths reused.2000 moving4calendar-week blocks include zeros. Control tails and intervals are descriptive.

## Evidence and next step

1,065 mandatory tests (18new) and Ruff passed. Independentpre-outcome review independently checked scalar feature/clock fixtures and minute-step position/accounting oracles. Exact details and SHA bindings retained inpre-outcome-review.json. Finalbaseline reproduction uses samefrozenengine plus separate accounting reconstruction; not nativeJesse execution or an independentrerunof500control paths. Mandatoryreview hash-bound andcommittedbeforeANYrawmarketload; missingreviewcoldprobe failedclosedbeforedata.

Fourteen frozen hashes and66prior definitions/artifacts remain intact. DON8, EMA8, VOL8, DV2, D4, existing payoff geometry, session watches and prospective protocols are unchanged. Bollinger is excluded; no order path added. Minimum cumulative attempted22trading/23signal-model cells; related control/cost/gap variants are not independent trials. Source-readiness searches remain separately counted and bounded.

A historical survivor can only start a separately frozen, adequately powered future confirmation with calibrated costs/execution and paper reliability. Rejection remains closed; no source option or threshold is changed after this result. Conditional prospects are outlined separately with unresolved requirements, not promotions.

Full result SHA256 `594bd5b8ac9ea1fbbf5957446b93e9e47db831e1d54851a2a24ccbae6134f29e` (14455305bytes); lossless gzip SHA256 `ca7fb962832eb54a30e94aafa54c71376a3726cd8b2de90b7925bcb86cd0744d` (1362320bytes). Baseline full paths/events retained; placebo cohort means+seed and lag summaries retained. Full control paths reproducible but not stored.

## Rerun

Pinned Windows Python3.13.14 / NumPy2.2.4 / pandas2.2.3, registration Git commit and exact raw archives/receipts required. New output path required; no overwrites.

```powershell
$env:PYTHONPATH='src'
python -m orderflow_edge_lab.public_dual_thrust_batch9 --raw ../../outputs/Minute-continuous-source-data --cache ../protective_batch5_cache --output ../../outputs/DualThrust-batch9-rerun.json
```
