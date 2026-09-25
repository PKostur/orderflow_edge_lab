# Universal Descriptive Regime Labels v1

\`universal-descriptive-regime-labels-v1\` is a separately versioned, preregistered, descriptive-only layer over the unchanged historical Universal Backtest snapshot. It does not alter DON8, EMA8, VOL8, canonical accounting, the frozen prospective session/alignment watch, any live position, or any promotion gate. Same-period results are not untouched future OOS evidence.

## Causal 8h state contract

A trade entered at the open of bar \`t\` is labeled from the latest completed bar strictly before entry, normally \`t-1\`. No current-entry-bar high, low, close, or future value is used.

The five axes are:

1. **Trend efficiency**: 42-bar Kaufman Efficiency Ratio, \`abs(C_t-C_t-42) / sum(abs(delta C))\`. The raw ratio is cut at the 1/3 and 2/3 percentiles of its preceding 540 feature values, producing \`CHOP\`, \`MIXED\`, \`TREND\`.
2. **Volatility**: 21-bar Garman-Klass OHLC volatility, using per-bar variance \`0.5*ln(H/L)^2 - (2ln2-1)*ln(C/O)^2\`, with no annualization. It is cut at causal trailing 540-bar 1/3 and 2/3 percentiles into \`LOW\`, \`MID\`, \`HIGH\`.
3. **Market coupling**: average of all available 90-bar rolling Pearson correlations of close-to-close log returns across the frozen symbol universe. At least 10 valid pairs are required. The market-wide series is cut at causal trailing 540-bar 1/3 and 2/3 percentiles into \`LOW\`, \`MID\`, \`HIGH\`.
4. **Shock**: absolute one-bar log return at least four times the sample standard deviation of the preceding 540 one-bar log returns. \`SHOCK\` covers the completed event bar plus the following nine completed bars.
5. **Drawdown**: close distance from the maximum intrabar high over the trailing 540 bars. Fixed descriptive bands are \`NEAR_HIGH\` at >= -10%, \`CORRECTION\` between -10% and -20%, and \`DEEP_DRAWDOWN\` at <= -20%. These are conventional descriptive thresholds, not crypto-optimized cutoffs.

Trend, volatility, coupling, and drawdown require three consecutive completed bars in a new bucket before an existing stable state switches. Shock is an event-window label and is intentionally immediate rather than persistence-delayed.

## Fixed cell family

The substantive grid is the complete Cartesian product of 3 trend x 3 volatility x 3 coupling x 2 shock x 3 drawdown states, or **162 cells per strategy**. Every cell is emitted, including empty cells. Warm-up trades with unavailable causal labels remain in the report as unclassified instead of being reassigned.

At the frozen primary 20 bps cost case, each cell reports trade count, expectancy, median net return, win rate, profit factor, correct-direction rate, MFE/MAE, correct-direction MFE, and per-symbol compounded returns. Cross-symbol trades are not fictitiously sequentially compounded into one portfolio.

## Joint block uncertainty and multiplicity

The diagnostic reuses the 30-day calendar-block convention already preregistered in Payoff Geometry v1. The same block draws are used across symbols, strategies, and cells, retaining nearby temporal and cross-market dependence better than independently resampling trades.

Each non-empty cell gets a percentile bootstrap interval and a two-sided centered-bootstrap p-value for zero pooled expectancy. The complete non-empty cell family within each strategy is then adjusted with:

- Benjamini-Hochberg false discovery rate;
- Holm family-wise error rate.

Small adjusted p-values remain descriptive. They do not authorize filtering or promotion. If regime cells later influence selection, promotion, or deployment, a new frozen protocol must be created before new evidence is inspected. White Reality Check, Hansen SPA, Deflated Sharpe Ratio, and Probability of Backtest Overfitting remain reserved for that decision-affecting stage.

## Literature basis

- Kaufman ER / KAMA calculation: https://www.tradingview.com/support/solutions/43000773012-kaufman-s-adaptive-moving-average-kama/
- Garman & Klass (1980), *On the Estimation of Security Price Volatilities from Historical Data*: https://www.cmegroup.com/trading/fx/files/a_estimation_of_security_price.pdf
- Cryptocurrency application of Garman-Klass: Finance Research Letters, DOI 10.1016/j.frl.2018.12.023.
- Politis & Romano (1994), *The Stationary Bootstrap*, DOI 10.1080/01621459.1994.10476870. v1 uses fixed non-overlapping calendar blocks rather than the stationary-bootstrap algorithm, but shares the dependence-preserving rationale.
- Benjamini & Hochberg (1995), DOI 10.1111/j.2517-6161.1995.tb02031.x.
- Holm (1979), DOI 10.2307/4615733.
- White (2000), *A Reality Check for Data Snooping*, DOI 10.1111/1468-0262.00152.
- Hansen (2005), *A Test for Superior Predictive Ability*, DOI 10.1198/073500105000000063.
- Bailey & López de Prado (2014), *The Deflated Sharpe Ratio*, DOI 10.3905/jpm.2014.40.5.094.
- Bailey et al. (2017), *The Probability of Backtest Overfitting*, DOI 10.21314/JCF.2016.322.

## Authority boundary

This layer cannot change strategy rules, authorize a regime filter, relabel same-period diagnostics as future OOS, promote a candidate, authorize live order transmission, or authorize leverage.
