# Funding and admission clarification for the mathematical drafts

This is an explicit clarification of `Quickstart-UpDown-mathematical-readiness-draft.md`, whose retained SHA256 is `62452c120cf3bb0af6a83ce556f6fd07ac8479597b70fb94b7fd4bb1dccfcdf5`. That initial draft described next-open all-or-reject sizing but did not establish whether source funding was checked earlier. The execution-only interpretation is **not accepted**.

## Two-stage funding contract for the draft

The pinned standard Backtrader broker defaults to `checksubmit=True`. For a fixed-unit entry submitted after a completed close, it can reject using the **created closing reference**, before attempting the following opening fill. A second funding check is required at the actual opening reference. The proposed mathematical policy therefore preserves both stages, with no resize:

1. Retain the fixed quantity and created-close price in the pending request.
2. At the next opening processing event, reject at the submission-check stage if source cash cannot pay quantity × created-close plus the declared entry charge.
3. If that succeeds, reject at the execution stage if source cash cannot pay quantity × opening-reference plus its declared entry charge.
4. Fill only if both succeed; clear the pending request on either terminal rejection. A later source signal may submit a fresh request; do not auto-retry the rejected order at a new price.

Synthetic native evidence with cash 10,000, one unit and 20 bps per side:

| Created close → next open | Default native notifications | Result |
|---|---|---|
| 10,050 → 9,000 | Submitted → Margin | Reject before opening execution, despite an affordable open |
| 9,000 → 10,050 | Submitted → Accepted → Margin | Reject at execution |
| 9,000 → 9,000 | Submitted → Accepted → Completed | Fill; endogenous exit fills at E+6 |

Disabling `checksubmit` fills the first gap-down case, so it is a materially different runtime and is not the declared funding policy. The probe is retained in `Quickstart-UpDown-native-funding-probe.json`. Its source bodies are unchanged; research cash/friction, streaming and admission are explicitly declared runtime adaptations. Source-harness/default-bot parity is not claimed.

## Correct admission boundary

The standard lane first admits a feature decision at completed close **239** after 240 closed bars; its first possible next-open fill is **240**. This differs from the retained earlier synthetic probe's close **240** / open **241**. Both are separate fixture cases. Before each chosen origin, no position or pending order is carried. No source quantity, threshold, stop, target or exit clock changes.

## Remaining boundary

The mathematical draft uses all-or-reject full fills. Partial fills, lot/minimum rules, asynchronous external callbacks and exchange matching remain outside the proved domain. Fixed source units and 10,000-USDT sleeves are retained even when they cause repeated rejections; no cash increase or pair change is allowed to rescue them. No market data or EMV17 outcome was inspected.
