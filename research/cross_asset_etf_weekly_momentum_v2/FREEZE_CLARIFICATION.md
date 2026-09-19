# Cross-asset ETF weekly momentum v2 — pre-PnL calculation clarification

Frozen before any v2 strategy PnL is calculated.

- The common-session calendar is the intersection of valid daily-bar dates across all 10 frozen ETFs.
- A weekly decision is the chronologically last common session in the ISO week. There is no substitute date if a required common session is unavailable.
- `t-5` and `t-63` are offsets on the common-session calendar.
- Score distributions use only `split_adjusted_cash_amount`, with ex-date strictly after the start score date and on/before the end score date.
- A holding-period distribution is included when `entry_date < ex_date <= exit_date`. This reflects that a buyer at the entry-date open is not entitled to an entry-date ex-distribution, while a holder through the night before the exit-date open is entitled to an exit-date ex-distribution.
- Gross weekly portfolio return is the arithmetic weighted sum of the three constituent holding returns at frozen target weights.
- Net weekly return = gross weekly return minus frozen turnover cost.
- Turnover = `0.5 * sum(abs(target_t - target_previous))`; primary cost = `2 * 5 bps * turnover`; stress cost = `2 * 10 bps * turnover`.
- The bottom-3 reversed control and all-10 equal-weight benchmark use identical holding dates, dividend arithmetic and cost formula.
- Weekly excess = original net return minus equal-weight benchmark net return on the same holding week.
- D0 half gates use the fixed decision-date ranges in `FREEZE.json`; they are not recomputed from the observed sample.
- ETF contribution for the concentration gate = cumulative pre-cost `target_weight * holding_return` over D0 weeks in which the ETF is selected. Concentration = largest positive ETF contribution / sum of all positive ETF contributions. If no positive contribution exists, the gate fails.
- Data after the final D0 decision may be read only to identify the next common rebalance entry and close the final D0 holding period. No D3 score, rank or performance statistic may be computed unless all D0 gates pass.
