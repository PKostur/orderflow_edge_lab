# Cross-asset ETF weekly momentum v1 — pre-PnL calculation clarification

Frozen before any strategy PnL is calculated.

- The common-session calendar is the intersection of valid daily-bar dates across all 10 frozen ETFs.
- A weekly decision date is the chronologically last common session inside that ISO week. No substitute ticker or non-common date is allowed.
- `t-5` and `t-63` are positions on the common-session calendar, not calendar-day offsets.
- The score and holding-return dividend sums use `split_adjusted_cash_amount` exactly as frozen. If a required distribution record cannot be represented in that field, the affected calculation is fail-closed rather than silently replaced with another field.
- Portfolio gross return for a holding week is the arithmetic weighted sum of constituent holding returns using the target weights established at entry.
- Portfolio net return = gross return - `cost_bps / 10,000`.
- Turnover cost uses frozen target-weight turnover only. It intentionally ignores small drift-restoration trades when membership is unchanged. This makes the equal-weight benchmark cost zero after its initial establishment and is therefore conservative for the momentum portfolio.
- The reversed bottom-3 control and equal-weight benchmark use the identical holding dates, return arithmetic, dividend treatment and cost model.
- Weekly excess return is original net return minus equal-weight benchmark net return for the same holding week.
- The D0 half gates use the fixed decision-date ranges in `FREEZE.json`; no median split after results.
- Positive contribution concentration is a breadth diagnostic computed from pre-cost ETF contributions: for each ETF, sum `target_weight * holding_return` across D0 weeks in which it is selected; among ETFs with positive totals, concentration = largest positive total / sum of positive totals. If none is positive, the gate fails.
- Data after 2025-04-25 may be read only as needed to close the final D0 holding period. No D3 score, rank, portfolio or D3 performance statistic may be computed unless every D0 gate passes.
