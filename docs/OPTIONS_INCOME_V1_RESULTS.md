# New options income strategy: first executable-quote test

**Decision: no portfolio admission.** This new option-premium strategy is separate from existing trend, basis and gamma-indicator lanes. Rules and code were committed before one live quote capture. There were no price- or result-dependent strike, expiry, quantity, asset or fee changes.

## Actual quotes and scenario result

- BTC: no feasible position. The earliest eligible7–14day expiry lacks the required protective strike at/below80% of current index. No narrower wing or different expiry was substituted.
- ETH: executable short-put bid and protective-put ask yielded a positive premium, but historical downside scenarios failed the frozen development screen.

| ETH scenario | Net entry credit | Conservative total-loss bound | Mean scenario PnL | Worst scenario | Bootstrap5th percentile of mean |
|---|---:|---:|---:|---:|---:|
|Standard published fees|2.904248USDC|87.271252USDC|-3.970417USDC|-87.256226USDC|-6.709719USDC|
|Double fees,10% less credit|2.244495USDC|88.106505USDC|-4.643337USDC|-88.076453USDC|-7.385679USDC|

ETH instruments: `ETH_USDC-6NOV26-2100-P` short and `ETH_USDC-6NOV26-1800-P` long, underlying amount0.3. Quotes crossed the real bid/ask depth. Capture exchange span1.391seconds. Indicative REST quotes are not atomic fills.

All160 scenarios use nonoverlapping42-bar terminal underlying returns from the existing2020Aug11–2026Sep30 panel, normalized to the current USDC index. The observed loss frequency was12.5%, with an87.5% non-loss rate; high win frequency did not imply a positive mean. This is NOT a historical option backtest: historical option premiums, IV, spreads and fills are unavailable here. The bootstrap is a development diagnostic, not untouched future evidence.

## Implementation and review

Design commit `75915a50df16e1610a80b2e80c33cb95523b799e`; executed evaluator `a8f28a791cb15d9877e30708fcfeafaf10d2c9bf`; exact evaluator SHA256 `1608bbb3025bd0f03c33e2bdb25c5a82f3e7e0cc968e2b3c5a7bf052d8a0bbdd`. All raw public API replies, request URLs/times and hashes are retained alongside the full report. The committed configuration and history manifest are bound by hashes. Source contract/margin review is archived; the result review states its independent coverage.

Eight new tests include1000 randomized/extreme put-loss-bound cases, piecewise intrinsic/delivery PnL, fee caps, real depth and refused shortfalls/duplicates, deterministic selection, lot flooring, conservative sizing and refusal of authenticated/order endpoints. Full suite1234 tests passed; Ruff passed. Existing frozen source, configs, prospective protocols and watches are unchanged.

The full-strike reserve is a conservative payoff funding rule, not exchange margin certification. Actual account margin, liquidation behavior, quote-to-fill reliability and venue access remain unverified. Generated expiry futures immediately cash-settle USDC; no extra futures delivery fee is charged. Stablecoin/venue losses are outside the contractual option payoff bound. No live orders, active paper positions, prospective confirmation or profitability claim.

## Reproduction

```powershell
$env:PYTHONPATH="src"
python -m orderflow_edge_lab.options_income --history artifacts/public_spot_8h_20261010 --output NEW_CAPTURE_DIRECTORY
```

A new capture produces new quotes, not the archived first test; it must not be presented as a blind rerun of the same market. Existing evidence directories cannot be overwritten. Do not rescue this rejected version by narrowing strikes or dropping the infeasible BTC sleeve.
