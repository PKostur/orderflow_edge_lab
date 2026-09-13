# Methodology Expansion v1

This is a retrospective development lane used while the forward candidates accumulate untouched evidence. It does not modify any frozen candidate and cannot create an OOS or profitability claim.

## Specialist scope

The work is intentionally limited to the smallest relevant pods: mean reversion, trend/structure, volatility regime, derivatives positioning, execution economics, risk path, transfer/generalization, and research validity.

## Added methodologies

### 1. Lagged one-bar reversal

On the fixed 10-symbol MEXC panel, the sign of the last completed 15-minute close-to-close return is used only after that candle is complete. The reversal arm takes the opposite sign at the next candle open and holds one bar. An otherwise identical continuation arm is retained as the reversed-direction control. Costs of 12, 16, 20 and 30 bps are all retained.

### 2. Lagged cross-sectional funding carry

The last already-realized public MEXC funding rate is ranked across the fixed panel. The strategy waits until the next 8-hour open, then goes long the most negative-funding contracts and short the most positive-funding contracts. Both one-per-side and two-per-side portfolios are tested, with an exactly reversed-carry control. Only funding cashflows strictly after the position is open are credited. Funding-aware testing is blocked if any frozen symbol lacks observed funding coverage.

## Candidate stability neighborhoods

These tests are diagnostics, not reselection mechanisms.

- HTF trend: a small predeclared neighborhood around EMA 24/96 with the frozen ATR-normalized threshold represented explicitly among neighboring timing and threshold cells.
- Cross-sectional momentum: the frozen 30d/7d dollar-neutral specification is surrounded by a small lookback/holding-period neighborhood.
- ENA mean reversion: the signal remains exactly BB40/2 with RSI25/75 and a 20-bar maximum hold. Only the already-studied 1.0, 1.5 and 2.0 ATR stop neighborhood is retested over the longer sample.

## Economics and validity

All predeclared cells are retained. No cell is ranked or promoted by highest PF. Funding is never imputed as zero before public coverage exists. Trading costs are never reduced below the stated cases to improve results. Fold results are retained for temporal stability, but overlapping and historical folds are not described as independent OOS trials.

The fixed current 10-coin panel carries survivorship bias and is not a reconstructed point-in-time universe. That limitation remains explicit.

The forward candidates, discovery-v1, regime-research-v1, v1.1, v1.2, state thresholds, conditioned strategy protocol, paper-only execution boundary, and live-transmission prohibition are unchanged.
