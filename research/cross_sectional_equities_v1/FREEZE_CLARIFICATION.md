# Cross-sectional equities v1 — pre-PnL calculation clarification

Frozen before any cross-sectional equity hypothesis PnL is calculated.

- A selected name's gross contribution is `0.25 * direction * (exit_open / entry_open - 1) * 10,000` portfolio bps.
- Primary friction is allocated equally through weights: each selected name contributes `0.25 * 4 = 1` portfolio bp of cost; stress friction contributes `0.25 * 8 = 2` portfolio bps. Thus four selected names sum to exactly 4 bps primary or 8 bps stress cost.
- The positive-PnL concentration denominator is the sum of positive cumulative **primary-net name contributions** across the full D0 window. The numerator is the largest such positive cumulative name contribution. If no name has a positive cumulative primary-net contribution, the concentration gate fails.
- A portfolio session is eligible only if all eight frozen names have every exact minute required by that family. The universe may not be shrunk on an incomplete day.
- Cross-sectional ties are broken alphabetically exactly as frozen.
- D0 halves are 2026-07-06..2026-07-17 and 2026-07-20..2026-07-31.
- Reversed control flips all four selected directions at the same ranking, decision, entry and exit and pays identical friction.
- Any family failing any D0 gate is terminally falsified under that ID; its August holdout remains sealed.
