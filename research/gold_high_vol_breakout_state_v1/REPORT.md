# Gold High-Vol Breakout State v1 — Development Result

## Evidence boundary

This is a post-observation mechanism study on 2021-2022 development data. It was generated from the previously observed `rv_persistence` state candidate in `gold-volatility-liquidity-v1`; it is not independent confirmation and is not future OOS.

Canonical workflow run: `34989250682`

Artifact: `gold-high-vol-breakout-state-v1` (`10404403171`)

Artifact digest: `sha256:5cebbec4bb8ec30ad03ffd3dd7d00c6e24bcf05c7ca3ac1b18039f41c9a5e563`

2023 remained physically absent from the input and was not opened.

## Frozen mechanism

- high-volatility activation: prior-hour realized-volatility ratio >= 1.25 versus its 20-observation same-clock baseline;
- normal-volatility control: ratio >= 0.75 and < 1.0;
- prior-hour range frozen at each two-hour New York anchor;
- breakout confirmation: first one-minute midpoint close within 30 minutes beyond the prior-hour high/low plus a 5% prior-range buffer;
- primary state horizon: 30 minutes after breakout confirmation;
- state score positive for continuation in breakout direction, negative for reversal;
- no entries, stops, targets, transaction costs, leverage, or PnL.

## Result

- confirmed breakout events: **2,982**
- dates containing confirmed events: **516**
- high-volatility breakout events: **539**
- normal-control breakout events: **1,187**
- matched daily contrast dates: **218**
- primary high-minus-normal median daily contrast: **+0.066713 prior-hour ranges**
- positive daily contrast fraction: **54.59%**
- two-sided 20,000-epoch sign-flip p-value: **0.239088**

The positive contrast does not mean high-volatility breakouts continued. Absolute high-volatility breakout behavior was reversal:

- high-state median 30m continuation score: **-0.041833**
- high-state positive-continuation fraction: **46.57%**
- long-breakout events: **252**, median continuation **-0.028749**, positive fraction **46.83%**
- short-breakout events: **287**, median continuation **-0.054806**, positive fraction **46.34%**

The normal-volatility group was therefore more reversal-prone than the high-volatility group, creating a positive high-minus-normal contrast even though the high-volatility group itself did not exhibit positive continuation.

## Frozen robustness checks

Horizon high-minus-normal median daily contrasts:

- 15m: **+0.060002**
- 30m: **+0.066713**
- 60m: **+0.086471**

Calendar years:

- 2021 median daily contrast: **+0.060664** across 113 dates
- 2022 median daily contrast: **+0.072290** across 105 dates

Alternative high-volatility thresholds:

- RV ratio >= 1.0: **+0.021775** median daily contrast across 385 dates
- RV ratio >= 1.5: **-0.074592** across 98 dates

The stricter threshold reverses sign, so the frozen threshold-robustness gate fails.

## Gate decision

**REJECT.**

The hypothesis fails because:

1. primary p-value `0.239088` exceeds `0.05`;
2. daily primary-sign fraction `54.59%` is below `58%`;
3. high-state absolute median continuation is negative rather than at least `+0.05`;
4. high-state continuation win fraction `46.57%` is below `55%`;
5. both long and short high-volatility breakout medians are negative;
6. the RV >= 1.5 robustness threshold flips the high-minus-normal contrast negative.

No economic implementation is authorized from this continuation hypothesis. Do not reverse the trade direction inside this protocol after seeing the result.

The symmetric negative long/short medians may generate a separately frozen failed-breakout/reversal hypothesis, but any such child must be explicitly labeled post-observation and cannot be treated as confirmation of this rejected hypothesis.

## Claims

- directional development state pass: **false**
- independent confirmation: **false**
- executable edge established: **false**
- profitable edge established: **false**
- verified future OOS: **false**
- leverage authorized: **false**
- live enabled: **false**
