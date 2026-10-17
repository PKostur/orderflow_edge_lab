# Causal runtime checks for the source frontier

Completed 17 October 2026. **Synthetic inputs only. No market data, performance evaluation, registration, repository changes or external orders.** Original default-preloaded failures remain retained unchanged in `Fresh-source-frontier-after-batch16` and its original native proof.

## Runtime variants tested

The hash-checked Backtrader 1.9.78.123 wheel executed the pinned source classes with `preload=False, runonce=False`. Source class bodies and default parameters were unchanged. Upstream test bodies, market readers and performance assertions were excluded; logging was suppressed and scalar state/fill tracing added.

Two variants were kept separate:

1. **Streaming source:** no cash gate; source initialization and ordinary order behavior retained.
2. **Streaming with explicit cash origin:** source calculations continue during warmup, but order-creation wrappers refuse every buy/sell/close before zero-based index 240. No startup position or pending order enters admission. At index 240, 240 prior bars are completed and new source orders may be submitted for the next open. Causally accumulated indicator/countdown state is retained, rather than reset to manufacture agreement.

Three source classes × two variants × baseline, future-tail mutation and shorter-prefix feed produced **18 synthetic executions**.

## Results

| Source | Future-tail scalar/state comparison | Completed fills before mutation | Shorter-prefix comparison | Cash origin flat with no prior pending order |
|---|---|---|---|---|
| Quickstart06 | Pass in both variants | Pass | Pass | Pass |
| TD Sequential | Pass in both variants | Pass | Pass | Pass |
| UpDownCandles | Pass in both variants | Pass | Pass | Pass |

The mutation changed only synthetic bar 319; earlier 319 bars were identical. A separate feed ended at bar 299. Comparisons included source persistent scalar fields, indicator outputs, position/pending state and fill events—not only entry flags. Per-run trace fingerprints and admission snapshots are retained in the companion JSON/native output.

Quickstart's admitted entry filled at open 241 and endogenous exit at open 247, confirming **E+6** open-to-open timing. TD generated buy/close events but still lacks a source pending-order lock. UpDown's original two-sided execution generated an admitted short; this is not proof of a Spot-long adapter.

Streaming removes future-buffer access in these fixtures. It does not establish intended textbook startup: an unavailable negative index can resolve to the *currently known* tail. UpDown's first 40-row return is consequently zero in this runtime. No period or source guard was changed. The earlier preloaded future-contamination failures remain valid for that different runtime.

## Readiness limits

- **Sizing:** source sizes remain one unit for Quickstart and ten for TD/UpDown. Exchange minimums, rounding, fractional cash caps and per-symbol budgets are unproved.
- **Fills:** only normal, funded, full market fills were exercised. Partial fills, margin/rejection, delayed acceptance, cancellation and exchange friction remain untested.
- **Lifecycle:** Quickstart/UpDown ordinary pending-order completion was observed. TD submissions still do not assign `self.order`; passing these immediate fills does not admit TD's unresolved order lifecycle.
- **Source scope:** cloudQuant classes ran in the pinned standard Backtrader wheel, not a separately pinned cloudQuant fork runtime. No full source-bot or exchange parity claim follows.
- **Cash admission:** refusing warmup submissions is an explicit runtime adaptation. It is not unchanged default execution or permission to carry original startup positions into research.
- **Proof domain:** one deterministic synthetic family and its mutation/truncation, not universal causality, economic survival or untouched confirmation.

**TD remains unadmitted.** Quickstart and UpDown now have bounded evidence for a declared streaming/cash-origin runtime; their mathematical Spot specifications, source-sized cash policy and outstanding lifecycle cases remain unfrozen. No candidate is registered or promoted.

## Evidence hashes

| Artifact | SHA256 |
|---|---|
| Companion readiness JSON | `09d5cabd6f462f7ba05b92c410449a34e4d9105cdcdffdeb125fa5142b7c385e` |
| Own harness, outside Git | `3dbf85e2fb925f288165d9accf426df5e23298a9f5fee5a954eeedfe059c6e42` |
| Synthetic fixture JSON, outside Git | `af8a62b9c31e83a45f49f728a6b9c37b0bdc399edb892d238eb098c857a4ffcd` |
| Streaming native output JSON | `f0508d105a549a8e8a2968fc70c479a28b7001070894b4673aef040078ea90c9` |
| Backtrader wheel | `9a07a516b0de9155539a35c56e9404d8711dd7020b3d37b30495e83e1b9d5dfd` |

Source commits, file hashes, attribution/licensing and original failure receipts are bound in the companion JSON. GPL source/framework code remains outside Git.

## Next step

Choose the intended source lane before inspecting later market outcomes, then freeze its streaming/cash-origin/long-only sizing and order-state contract. Exercise the outstanding synthetic rejection, delay and cancellation cases before any registration. Keep EMV17 separate and preserve all costs, controls, acceptance gates, rejection decisions and frozen lanes.
