# Frozen LSK conditional regime experiment

This is trial LSK-CONDITIONAL-001, a separately versioned test of the continuation/absorption hypothesis. It does not modify discovery-v1 or strategy-state-mapping-v1. Known captures, including new-to-this-review historical runs, remain exploratory. No tuning, parameter sweep, winner selection, or automatic promotion is supported.

## State and decision definition

Use LSK_USDT with BTC_USDT context. Preserve discovery-v1 flow/book/microprice thresholds (.25/.25/.20), five-print minimum, two-second same-direction cooldown and 30-second horizon. Fix the old same-timestamp BTC lookahead by consuming records in file order. BTC flow context expires after five seconds. Require an applied depth update within one second of the signal. These quality restrictions apply equally to all controls.

Every five seconds build state from strictly earlier received-time records. Quote activity counts only depth records with `depth_applied=true`; trades carrying cached BBO never refresh quote age. A valid 15-second window has no applied-depth gap over one second. Missing legacy depth flags are unavailable, not assumed valid. Trade state must be at most five seconds old. No future returns enter this stage.

Baseline: preceding 300 seconds, at least 40 valid grid anchors and coverage back to the first grid interval. Current anchor is excluded. A snapshot or recorded sequence-gap increase resets the state epoch and requires a fresh warm-up; pre-recovery state cannot classify a post-recovery signal. Linear-interpolated quartiles and medians are causal, with no updates based on PnL. Flat interquartile ranges in participation, quote activity, range or efficiency force abstention.

Inputs:

- Participation: existing rolling ten-second trade count.
- Quote activity: applied depth updates per second over 15 seconds.
- Range: prior 15-second high/low midpoint range in bps.
- Displacement/spread: 15-second signed midpoint return divided by current spread bps, oriented by the current ten-second flow.
- Range/spread: range bps divided by spread bps; must exceed inherited low-range boundary 2.
- Directional pressure: original aligned flow/book/microprice signal; rolling absolute flow ratio supplies the normalized pressure comparison.
- Price-response efficiency: flow-oriented ten-second midpoint return, divided by current spread bps and `max(0.25, abs(10s flow ratio))`. The inherited .25 floor prevents a near-zero flow denominator. Weak-flow anchors remain in the baseline.
- Spread change and volatility expansion: current spread/range compared with the anchor 15 seconds earlier; range is also compared with its trailing median.
- BTC alignment: known, fresh BTC flow agrees with original LSK signal side.

ORIGINAL requires above-median participation and quote activity, range above both its trailing median and 15-second-lag value, positive upper-quartile efficiency, displacement greater than one and at most four spreads, and non-widening spread.

REVERSED requires upper-quartile absolute flow, lower-quartile efficiency that is declining versus 15 seconds ago, prior displacement greater than four spreads, nonincreasing participation and quote activity, nonexpanding range and nondecreasing spread. Flow at the lagged state must have the same side as current pressure. A spread above five bps vetoes both directions. Current state flow must still agree with the original signal. These interaction choices are hypotheses, not verified market laws.

All other states, insufficient history and invalid inputs produce NO_TRADE. No fallback takes whichever direction subsequently won.

## Economics and comparison

Always-original and always-reversed use the same BTC-aligned opportunities. Unconditional-aligned uses the unchanged aligned signal without requiring BTC agreement; it is a distinct opportunity universe. Compare all four under 4/8 bps round-trip fees and two extra stresses:

| Case | Fee RT | Entry/exit latency | Slippage RT | Adverse selection RT |
|---|---:|---:|---:|---:|
| Conservative | 8 bps | 250 ms | 2 bps | 2 bps |
| Severe | 8 bps | 1000 ms | 4 bps | 4 bps |

Entry crosses ask for longs or bid for shorts; exit uses the opposite BBO. Thus spread is already paid and must not be subtracted again. Reversal recomputes fills rather than negating original return. Zero-latency entry uses the actual signal BBO; delayed entry and exit use first eligible applied-depth quote at/after the target, within one second. The horizon runs from signal time with latency on both ends. Stress amounts are assumptions, not measured fill guarantees or verified account fee rates. Fees and stresses can be changed only with a new frozen version; baseline cases remain reported.

Signals overlap. Summed bps and PF describe equal-notional event economics, not a portfolio return. Report intended trades, missing interior fills and capture-tail censoring; missing selected interior fills block a positive screen. Tail censoring is not a zero-return trade. Summary-only historical artifacts cannot reconstruct this classifier or delayed fills and must be reported separately.

## Dependence, freeze and forward test

Transitive intervals separated by no more than 300 seconds form one cluster. Choose the representative with most valid timestamped state anchors, then earliest start, then lexical source SHA256. Never choose by PnL. Duplicate downloads cannot inflate the cluster count.

Freeze JSON is exclusively created, never overwritten. It records actual UTC freeze time, source/config/dependency hashes, known replay hashes and trial identifier. Any source or config change fails verification and requires a new version. Pre-freeze capture timestamps cannot become forward evidence even if their hashes were not in the initial inventory.

The first **ten independent forward clusters** are the fixed assessment, preserving discovery-v1's inference minimum. Retain at least 150 minutes before considering candidate revision. Do not stop early on success, omit losses, or relax the rule if it produces few trades. Both branches must contribute at least 20 trades across three clusters. Severe-cost screen additionally requires at least 60 total trades, PF >1.20, positive median cluster expectancy, at least 80% positive clusters, no more than 50% of positive cluster profits in the best cluster, and positive expectancy after removing the best cluster. Numeric screen pass is not promotion.

Untouched provenance, candidate/holdout and trial-ledger audits, existing promotion gates, independent replication, realistic execution validation and paper reliability remain mandatory. `promotable`, `ready_for_live`, and `verified_out_of_sample_evidence` remain false in the exploratory runner. Forward mode enforces temporal eligibility but cannot certify that no human viewed the data. Numeric conditions are reported separately; `numeric_screen_pass` remains false until a chronological ledger audit establishes that all first-ten capture attempts (including failures) were retained and the cohort was not selected after outcomes. The runner does not certify that audit. No order transmission exists.

Delayed entry and horizon exit must stay within the signal's sequence/snapshot epoch. A reset invalidates pending fills and is counted as missing interior execution, blocking a successful numerical assessment if selected. No hypothetical PnL is imputed across the gap. Source/config/dependency hashes normalize text newlines for Windows/Linux portability; replay source hashes remain byte-exact.

## Running

After editable installation:

```powershell
orderflow-lsk-conditional known_capture.jsonl --freeze config/lsk_conditional_regime_v1.freeze.json --output artifacts/lsk/exploratory.json
orderflow-lsk-conditional new_capture.jsonl --mode forward --freeze config/lsk_conditional_regime_v1.freeze.json --output artifacts/lsk/forward.json
python scripts/lsk_forward_capture.py
```

The shipped freeze already records all twelve known source hashes. Do not use `--create-freeze` again. The last command registers and starts a new twenty-minute public-data capture, retaining an attempt record even on failure. It does not place orders. For aggregation, supply the accumulated eligible forward capture paths in one invocation; keep historical and forward inputs separate. Preserve the full replay, capture logs, source run/commit identity, freeze, decision ledger and report.
