# Quickstart06 / UpDown40: mathematical draft readiness

**62 selected synthetic checks passed.** No market data or EMV17 outcome was inspected. No strategy registration, repository edits, source-code copy into Git, external order or viability claim.

## Fixed before outcome inspection

The initial design was recorded at **2026-10-16 22:53:05 UTC**. Both sources remain distinct drafts:

- Quickstart06: one fixed unit, two strict declining-close comparisons, source exit filled at **E+6** under ordinary next-open execution.
- UpDown40: ten fixed units; 40-bar return below −1% enters long, at least +1% exits long. Candle strength remains unused and upstream flat-position shorts are explicitly refused.

The standard first eligible completed feature is **index 239**, followed by earliest fill at **open 240**. A separate fixture retains **decision 240 / fill 241** for comparison. The earlier frontier/runtime artifacts remain unchanged.

ETHUSDT, SOLUSDT and LINKUSDT are three fixed research sleeves of 10,000 USDT each. Published source initial cash is 100,000. No source-unit scaling, cash increase, or pair selection is allowed to avoid funding rejection. The selected synthetic burden is 20 bps per side; source friction differs and is disclosed.

## What passed

- Independent scalar/array feature agreement, exact threshold and zero-denominator behavior, causal prefixes and future-tail invariance.
- Pinned source classes in declared streaming, cash-origin and Spot-long wrappers agree with the own mathematical implementation on selected funded and rejected-order fills, including an oscillating fixture with repeated entries/exits.
- Both admission boundaries and Quickstart's source fill-notification clock; flat/no-pending state before admission and pending-at-signal-close behavior.
- Final-close entry without a following open remains unfilled. A pending final exit does not fabricate liquidation; the mathematical sleeve keeps its position censored and administratively cancels the undeliverable request.
- Own pending lock, cancellation and later source-signal reentry fixtures; fixed-unit quantities are preserved.
- BTC **own-equity** same-fraction sizing arithmetic, rather than substituting asset returns for BTC results. Full matched BTC lifecycle remains unproved.

## Funding finding: execution-only checks rejected

The pinned broker's default `checksubmit=True` performs a created-close precheck before opening execution. With cash 10,000 and unchanged source units:

| Fixed notional at created close → next open | Outcome |
|---|---|
| 10,050 → 9,000 | Submission-stage Margin, although the open is affordable |
| 9,000 → 10,050 | Accepted, then execution-stage Margin |
| 9,000 → 9,000 | Completed |

Both source classes match the explicitly declared two-stage mathematical funding policy in selected fixtures. Turning `checksubmit` off fills the first gap-down case, so it is not interchangeable. Source class bodies and default signal parameters were unchanged; research cash, friction, admission and refusal of shorts are declared adapters.

## Boundaries before registration

These are drafts with bounded mathematical evidence. Generic `Rejected` callbacks distinct from Margin, asynchronous delays/cancellation, partial fills, exchange tick/lot/minimum rules and a full matched BTC benchmark lifecycle remain unresolved. Pending cancellation fixtures are mathematical-only; they are not native exceptional-order parity. The cloudQuant source runs in the pinned standard Backtrader wheel, not a proved publisher-fork/default-bot runtime. No protective stop, target or new exit condition was added. TD remains unadmitted.

The complete specification is the retained initial draft **plus** the funding/origin clarification. Root must freeze the remaining execution and benchmark scope before registration or market evaluation. All costs, controls, existing rejections and untouched-future requirements remain unchanged.

## Evidence

| File | SHA256 |
|---|---|
| `Quickstart-UpDown-mathematical-readiness-index.json` | `f25e889d5c420c7ff6a3fd5042e3a07cf4524fce9b0400ba61eb45d104de47c8` |
| `Quickstart-UpDown-mathematical-synthetic-proof.json` | `eee419b0fafb07f7bb17b0090cdd763784f230342f24336927b5037848f9b7a5` |
| `Quickstart-UpDown-selected-native-output.json` | `287d6ffa2ceec4fe1e08a741988c4cf81815ee92f240edb19ac80ae1105a828d` |
| Own feature/state helper, outside Git | `c71abc35003eb3011ea1f33c2f79e8883eb5d3a87bcb30616f16b89b61124729` |
| Own synthetic harness, outside Git | `72252bbd73143650ef001370882d2746bbd160de61fb9e10c1483b1333b86d83` |
| Selected numeric fixtures, outside Git | `6f26da594180c33c00bc94b7eeefbf700f42328cef79e3e9e8d8adfb912aa2f8` |

The proof binds source hashes, wheel hash, broker dependency hash/method locations, helper, harness, fixtures and both specification documents. GPL upstream source/framework and the harness remain outside Git.
