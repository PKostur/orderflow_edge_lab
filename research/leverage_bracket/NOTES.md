# leverage-bracket-study-v1: reading notes (added after the single run, 2026-10-13)

The result files (`result_v1.json`, `RESULT.md`) are the single look and are not edited. Two reading notes:

1. **P(ruin) is understated in the 50x and 75x cells and wrong in E0_L50_TP10_S1 (shows 0.0).** In those cells the realized account fell below zero on the first days (`first_below_half_day` 0), so the daily return series contains undefined values (equity 0 or negative; the runner warned "invalid value encountered in divide"), and the bootstrap treats those paths inconsistently. The historical path is the decisive fact: every one of the 72 accounts fell below 50% of its start within 0-7 days and ended at about zero. The P(ruin) column is reliable only for the 10x and 20x cells (all 100%).
2. **Max drawdown below -100%** comes from liquidation losses larger than the margin (margin + 0.5% liquidation fee + entry fee) once equity is near zero; equity is not floored (as registered).

Neither note changes the reading: no cell has a positive net expected value; all 72 are negative with 95% intervals far below zero, and none is viable.
