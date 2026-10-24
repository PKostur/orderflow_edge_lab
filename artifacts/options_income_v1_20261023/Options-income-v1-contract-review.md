# Current design update: cash-secured put credit spreads only

The initially considered iron condor is superseded before any option-price economics. The current new strategy sells a put at or below 90% of the fixed entry index and buys a lower-strike put at or below 80%, using the same eligible 7-14-day expiry and equal underlying quantity. Calls are excluded. The earlier condor review below is retained as the reason for this change, not as the accepted strategy.

For strikes 0 < Kl < Ks and quantity q, the gross maximum intrinsic loss is (Ks-Kl)*q. Each ITM put has settlement index S < its strike K, so its delivery charge is bounded above by 0.00015*K*q. Therefore the sum bound 0.00015*(Ks+Kl)*q is valid without assuming fee netting. Conservative total net loss is bounded by width*q minus executable gross premium credit, plus all entry fees and that delivery bound. Require consistent common sizing increments and a positive risk denominator; reject invalid/missing strikes, quotes, quantities or credit.

Reserving Ks*q plus the long premium, entry fees and delivery bound is conservative payoff funding. It is not a guarantee against Deribit margin calls: Standard Margin charges positions separately, and short-put initial margin also includes the option mark and an additional risk component. Extreme mark/margin states can exceed strike-only collateral. Account margin, interim liquidation mechanics and actual execution remain unverified.

The proposed 100 USDC worst-net-loss and 2,500 USDC reserve caps per underlying on initial 10,000 USDC are fixed research sizing assumptions. They do not authorize orders. Retain all four leg books for the two underlying spreads; enforce timestamp/depth and sizing gates before economics. Four current quotes still do not establish simultaneous fills or prospective profitability.

---

# Options income v1: contract and execution review

Reviewed October 23, 2026. Official documentation only; no price quotes, strategy outcomes, orders or account access were used. This review concerns the proposed new BTC/ETH linear-USDC iron-condor family.

## Contract and settlement

BTC_USDC and ETH_USDC options are European, quoted/margined/settled in USDC. Their published multipliers are 1 BTC and 1 ETH per contract; fractional trading is allowed, with published minimums 0.01 BTC and 0.1 ETH. Runtime metadata remains authoritative. Since early April 2026, ITM options first generate expiry futures at their strikes; those futures immediately cash-settle USDC. The net intrinsic payoff matches cash settlement. Delivery uses the index TWAP from 07:30-08:00 UTC. An option-generated future does not attract a second delivery fee. Never model a persistent unhedged future or duplicate that fee. Existing expiry futures can change netting; assume none in this isolated study. [Official linear options specification](https://support.deribit.com/hc/en-us/articles/31424932728093-Linear-USDC-Options), [linear futures](https://support.deribit.com/hc/en-us/articles/31424954805405-Linear-Futures).

## Fees: standard tier, no discounts

The current fee page was updated October 22, 2026. Standard option trading is 3 basis points of underlying notional per leg for maker and taker, capped at 12.5% of the premium. For base-coin amount Q, index I and executed premium p per coin, use Q * min(0.0003*I, 0.125*p). Apply separately to all four entry legs and any actual closing legs. No combo discount is justified for four separately modeled book executions. Delivery is 1.5 basis points, capped at 12.5% of ITM option value; conservatively charge each ITM leg using its expiry intrinsic value. Do not infer daily-option fee exemption from DTE; inspect settlement classification. Do not add a second fee for generated futures. Account discounts and actual billing remain unverified. [Official fees](https://support.deribit.com/hc/en-us/articles/25944746248989-Fees).

## Material risk-bound qualification

For equal Q and ordered strikes K_long_put < K_short_put < K_short_call < K_long_call, gross intrinsic loss is bounded by Q*max(put_width, call_width), before credit. This is elementary payoff geometry, not a margin guarantee.

**Inference from the conservative per-leg delivery formula:** if both call legs become ITM and expiry index S increases without bound, their individual delivery charges can also increase without bound. Therefore wing width minus credit plus delivery fees estimated at today's index is not a rigorous all-price maximum total loss. Verify multi-leg delivery-fee netting explicitly before claiming a hard net-loss cap; otherwise label the bound as intrinsic-only and total losses as scenario-dependent. A fixed stress-index ceiling is a stress assumption, not a universal bound. All actual delivery charges and fees must remain included in outcomes.

Standard margin calculates requirements separately per position and does not grant hedging offsets. Portfolio margin uses portfolio stress scenarios. Neither permits assuming collateral equals expiry wing loss, and a defined expiry payoff alone does not establish liquidation-free operation. Margin readiness remains unverified. [Margin models](https://support.deribit.com/hc/en-us/articles/25944811317149-Margin-types-and-usage), [portfolio margin](https://support.deribit.com/hc/en-us/articles/25944756247837-Portfolio-Margin).

## Public data and dimensional checks

Use public/get_instruments, filtering kind=option, base BTC/ETH, USDC quote/settlement and the intended linear type. Confirm exact expiry, strikes, option_type, contract_size, min_trade_amount, tick_size/tick_size_steps and state. An active instrument can be halted, locked or settling: require state=open. min_trade_amount is the base-coin order increment, distinct from contract_size. Convert contracts to underlying amount once; do not multiply a base-coin order-book amount a second time. [Instrument API](https://docs.deribit.com/api-reference/market-data/public-get_instruments).

Use public/get_order_book for each exact instrument. Preserve server timestamp, receipt time, change_id, bid/ask levels and quantities, index, underlying and Greeks. Walk bids for short sales and asks for long purchases; require adequate quantity on all legs. Mark and theoretical prices are not executable. Individual option delta is Black-Scholes delta, not account net-transaction delta or an expiry-win probability. Four REST responses are not an atomic executable combo; assess age/skew and adverse fill/depth stress without assuming simultaneous fills. [Order-book API](https://docs.deribit.com/api-reference/market-data/public-get_order_book).

## Readiness verdict

Documentation supports a distinct options research implementation. It does not establish premium profitability, historical executable quotes, atomic four-leg fills, account eligibility/margin or a universal net-loss cap after delivery fees. Freeze the exact selection, quantity, timing, settlement accounting and rejection/stress rules before inspecting economics. Abstain if any leg, source field, sizing unit or execution requirement fails. Keep live transmission disabled and existing strategies/frozen lanes unchanged.

## Pre-price implementation review: evaluator commit 2dc0128

Eight synthetic unit tests passed independently, without any market-price request. Fee caps, put intrinsic payoff, conservative delivery-fee bounds, doubled-cost sizing, amount-step flooring and public-method allowlist behave consistently with the stated design.

Before capture, bind the exact committed specification and design/evaluator identities in the result; reject duplicate depth price levels and validate actual best bid/ask arrays against scalar summaries; and verify identical BTC/ETH historical scenario timestamp anchors before describing joint blocks as synchronous. These are provenance/validation fixes, not parameter selection. No option prices or scenario outcomes were inspected in this review.
