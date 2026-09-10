# Research protocol

## Evidence boundary

Any observation inspected while selecting, filtering, tuning, or modifying a
candidate is discovery data. The frozen registry records the last spent-data
timestamp for each candidate. Evidence for that candidate must occur strictly
after that timestamp.

Changing timeframe, path, direction, setup family, horizon, or a numeric filter
creates a new candidate and a new future-only eligibility boundary.

## Sequence

1. Define the response variable and executable horizon.
2. Freeze candidate rules and all thresholds.
3. Hash configuration and input data.
4. Run complete chronological future windows.
5. Mark windows incomplete when the predeclared minimum event and active-day
   counts are not met.
6. Report raw directional returns and, where applicable, market/beta-adjusted
   and matched-control excess returns.
7. Adjust families of hypothesis tests for multiplicity.
8. Keep a final holdout inaccessible to ordinary discovery output.
9. Use trade-level or sub-minute data when a bar can hit stop and target in the
   same interval.
10. Treat paper/shadow execution evidence as separate from statistical edge
    evidence.

## No profitability claim

A positive in-sample result, a synthetic test, or one positive future window
does not establish a profitable edge. Live transmission remains outside this
repository.
