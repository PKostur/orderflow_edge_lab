# Cash trend portfolio v1: actual result

**Decision: REJECTED_AS_DEFINED.** The strategy made historical net profits but failed the frozen requirement to exceed the always-long control at both costs. No retuning, new confirmation claim, or live orders.

Manifest-verified four-symbol Spot panel: 6,726 synchronized8h bars each, August11 2020–September30 2026. Longest-lookback warmup; funded evaluation August16 2021 08UTC–October1 2026 00UTC. Every observation is spent development evidence.

| Portfolio | Cost per side | Final $10,000 | Net return | CAGR | Max close DD | Fills |
|---|---:|---:|---:|---:|---:|---:|
| trend | 20bps | $12,434.08 | 24.34% | 4.34% | -5.30% | 635 |
| always_long | 20bps | $13,051.17 | 30.51% | 5.33% | -18.56% | 1072 |
| btc | 20bps | $17,605.17 | 76.05% | 11.67% | -76.94% | 1 |
| trend | 40bps | $12,288.76 | 22.89% | 4.10% | -5.58% | 633 |
| always_long | 40bps | $12,957.35 | 29.57% | 5.19% | -18.64% | 1072 |
| btc | 40bps | $17,534.88 | 75.35% | 11.58% | -76.94% | 1 |

Cash benchmark0%. All liquidation values include hypothetical exit costs. Fills are wallet adjustments, not independent trades. Controls share dates/costs; always-long uses the same volatility formula and target cap but has more realized exposure, so this is not equal-realized-risk proof.

Baseline strategy mean gross exposure5.36%, average cash94.64%; its low historical drawdown partly reflects low deployment. Strategy2022 return−1.69%;2023+11.86%;2024+10.61%;2025+0.87%;partial2026+0.25%. Baseline/stress same-bar-low stress bounds−5.37%/−5.65% are conservative synchronized-low bounds, not an attainable intrabar path or future loss limits.

Baseline rebalance costs$130.80 and terminal liquidation$1.69; stress$260.05 and$3.35. Terminal NAV was independently reconstructed; the review artifact states exact coverage. All leave-one-calendar-year-out compounded strategy returns were positive. None of these historical statistics proves future profitability.

Rules committed before evaluation: design82551c6; executablecc28b8200631524cc9658f8044ea7266342b36d3. Seven new tests cover wallet conservation, shortfalls, delayed signal/fill clocks, log-volatility indexing, future-price perturbation and prefix invariance, and benchmark liquidation. Full suite1233 tests passed; Ruff passed. Frozen existing files are unchanged.

Reproduce from repository root (requires Python and PYTHONPATH=src):

```powershell
$env:PYTHONPATH="src"
python -m orderflow_edge_lab.cash_trend_portfolio --data artifacts/public_spot_8h_20261010 --output fresh-results.json.gz
```

The evaluator refuses evidence overwrite. No exchange credentials, balances or orders are used. Source rationale and assumptions: [design](CASH_TREND_PORTFOLIO_V1.md). Do not deploy or promote the rejected version. Existing prospective watches remain frozen; genuine forward confirmation is still required for any eventual candidate.
