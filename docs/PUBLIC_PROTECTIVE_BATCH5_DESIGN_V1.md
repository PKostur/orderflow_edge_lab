# PSR11 public protective batch5: pre-outcome design

This new design registers two declared long-only Spot adaptations before their
market outcomes are inspected. Preserve the six prior rejected adaptation IDs,
all original public v1 definitions and all frozen lanes. Exclude Bollinger
entirely. No network/order client is part of the evaluator. This is hypothetical
development screening; user completion still requires untouched future
confirmation after an eventual survivor is frozen.

## Source defaults and adaptations

[MAGen](https://github.com/jesse-ai/example-strategies/blob/7c91e0a37bf62165790120d730442e4f6eb00364/MAGen/__init__.py)
uses close linear-regression5/20 bull crossover with ADX8>13, long exit when
fast<slow and ADX8<15, ATR32 stop2/target5 and3% cash risk sizing. Source already
cash-caps notional. Use actual pinned Rust kernels, not a numerically close
independent linear-regression port: strict crossover decisions differed on
synthetic linear paths. Nonsequential ATR/ADX use240inputbars, sequential MAs
use supplied prefix. The pinned framework rejects unchanged protective
assignments inside its Spot `go_long`; this compatible lifecycle is an explicit
port, not an unchanged native strategy run.

[Ichimoku](https://github.com/pcjtse/trading-view-strategies/blob/7b03cff0d80ebd048c8e94d452fd797a8f4b973f/strategies/ichimoku.pine)
uses unshifted9/26/52 spans; close above both spans and Tenkan>Kijun enters,
each qualifying long close replaces stop at close−3ATR14 and target at
close+2ATR14. Convert source short reversals into cash liquidation. Preserve
brackets when neither condition holds; do not invent monotonic trailing stops.
Source intends100% equity. Independent mathematical implementation only; no
source code copied, license unestablished.

Both source timeframes are unenforced;8h signals with1m hypothetical execution
are explicit choices. Disable shorts/pyramiding, add fee reserve and fixed
signal-close quantity rounded down8decimals. Execute next-minute-open only after
a completed8h candle; reject unaffordable gaps without resizing. Brackets remain
anchored to signal close, activating immediately after modeled entry. No source
supplies a30bar timeout and none is added. There is no native Pine fill parity,
queue guarantee, latency calibration or exchange lot-size proof.

## Data freeze and clock

Use the **longest** shared complete-day segment in the prior quality inventory,
selected without PnL:2023-04-01 through2026-09-30 inclusive, all four symbols.
First entry eligibility is2023-06-20T00:00Z after240closed8hbars/80days. The
manifest and quality-file hashes are pinned in the JSON design. Reverify all
retained raw/checksum/receipt versions. Aggregate aligned8hOHLCV from audited
complete minute observations. No repair, imputation, bridging or new download.
This narrower selection does not cure or change old PSR7 readiness failures,
does not test2022bear coverage, and is spent historical data.

Process each held minute under the existing bracket before calculating its
8hclose decision. A pending market exit executes at the next open before range
touches. Stop gaps reference the adverse opening price. Conservative target
gaps use the limit; a separate complete opening-improvement sensitivity rerun
uses the open. Same-minute both-touch ambiguity forks **full** histories. Keep
all paths up to64per symbol/4096joint; overflow fails the screen. No independently
favorable trade sums may be called portfolio bounds.

Do not filter entries by future missingness or study-end proximity. Refuse any
unexpected gap. A final unavailable next open is unexecuted. Held exposure at
the fixed cutoff stays `CENSORED_MTM`, with quantity, bracket and pending orders;
mark known finalclose less hypothetical sale burden without recording a sale or
completed trade. Report completed-only statistics separately because truncating
unresolved outcomes can bias them. The principal all-admission estimand includes
those fixed-cutoff marked reference returns, not unknown future completed returns.

## Economics and diagnostics

Use20/40/60/80nominalroundtripbps, eachside half on actual modeled notional.
These include assumed fees/friction and are not historical execution evidence.
Own-cash risk sizing and benchmark capital reconcile every entry and exit.
Equal10000cash sleeves form the three-symbol portfolio; retain each complete
branch history and marked inventory. Fund a separate BTC cash comparator using
the alt entry's fraction of preentry cash. It enters at synchronizedBTCopen,
exits at that same point or minute's low/high bounds, and retains its own fees,
cash and inventory. A BTC8hclose cannot replace an unknown intrabar exit.

Return net per committed purchase cash is
`10000*((exit/entry)*(1-sidecost)/(1+sidecost)-1)`. Gross MFE/MAE distinguish
known pre-exit extremes from uncertain exit-minute extremes. Include pending
marks, entry-week/month/year/symbol/weekday/hour, fixed UTC session memberships
and overlaps (Asia0–9,London7–16,NY13–22), and causal30barBTC direction and
29prior-return volatility split2.5%. These are attribution, never filters.

Retain all signal accounting, portfolio path, exposure, source/config/runtime
hashes, leave-entry-week and leave-symbol diagnostics, and funding/execution
limits.2000fixedseed moving4calendar-week block bootstrap replicates include
zero-event weeks. Report entry-week ratio-of-sums intervals for net and conservative
same-exit BTC excess, alpha0.05/2 per candidate. These are descriptive; no
global repeated-search significance or established independence is claimed.

500fixedseed placebo runs randomize **raw entry flags** within the same entry
week, preserving their count. Rerun source exit logic and recompute causalATR
geometry, sizing and durations. Do not preserve observed endogenous stop
durations. Compare the maximum placebo cohort mean with the minimum original
history mean. Add a causal7bar delayed-entry control with the same risk engine.
Controls are associated versions of these two cells, not new independent trials.

## Decisions and trial accounting

Every supported history/gap model must meet the JSON's frozen conjunction:
100completed events,52entryweeks, all-admission net40mean>5bps and net80>0,
all3symbols positive net40, at least2/3observedyears positive, drawdown<30%,
positive worst leave-entry-week mean, positive descriptive net40 and conservative
BTCexcess lower intervals, placebo tail≤0.05, and no history overflow.

A pass is `SCREEN_SURVIVOR_FOR_FUTURE_REGISTRATION`, not viable or profitable.
A fail remains rejected under this version. Never weaken gates or redesign
after outcomes without a new registered study and full trial accounting.
Previously completed minimum:15tradingcells and16signal/modelcells. Register
two new cells here:17tradingcells and18signal/modelcells minimum, retaining the
broader historical forecast/feasibility/source-survey record separately.

An eventual survivor must receive a separate powered future-only protocol with
trial allocation, measured execution assumptions and paper reliability gates,
frozen before observations begin. No future confirmation window is invented or
treated as already observed. No candidate has satisfied the user's endpoint.
