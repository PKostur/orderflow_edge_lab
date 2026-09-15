# Gold High-Vol Failed-Breakout Reversal v1 — Development Result

## Evidence boundary

This is a post-observation child study on 2021-2022 development data. It was generated after the rejected high-volatility breakout-continuation study showed negative absolute continuation medians in both original breakout directions.

It is not independent confirmation and is not future OOS.

Canonical workflow run: `34989920706`

Artifact: `gold-high-vol-failed-breakout-reversal-v1` (`10405202817`)

Artifact digest: `sha256:f9767f3335ce3993d3839e4350b0f4309db73a63687824b3df6f440e3b47f8a4`

2023 remained physically absent from the input and was not opened.

## Frozen mechanism

- prior-hour RV ratio >= 1.25 defines the primary high-volatility state;
- 0.75 <= RV ratio < 1.0 defines the normal-volatility control;
- original breakout must first confirm outside the prior-hour range plus a 5% range buffer;
- failed breakout requires the first one-minute midpoint close back inside the original prior-hour range within 15 minutes after breakout confirmation;
- reversal state score is positive only when price subsequently continues opposite the original breakout direction;
- primary horizon is 30 minutes after failure confirmation;
- no entries, stops, targets, costs, leverage, or PnL.

## Result

- confirmed breakout events: **2,982**
- failed-breakout events: **1,936**
- dates with failed-breakout events: **507**
- high-RV failed-breakout events: **364**
- normal-control failed-breakout events: **774**
- high-RV failure rate conditional on breakout: **67.53%**
- normal-control failure rate conditional on breakout: **65.21%**
- matched daily contrast dates: **143**

Primary 30-minute high-minus-normal daily contrast:

- median: **-0.065184 prior-hour ranges**
- daily primary-sign fraction: **53.85%**
- two-sided 20,000-epoch sign-flip p-value: **0.435028**

The primary contrast is negative, opposite the frozen desired reversal-excess direction.

## Absolute high-RV reversal behavior

- median reversal score: **-0.010907**
- positive reversal fraction: **48.08%**

Original breakout direction audit:

- original long breakouts: **175** events, median reversal **-0.022420**, positive fraction **48.00%**
- original short breakouts: **189** events, median reversal **-0.010191**, positive fraction **48.15%**

Thus both original breakout directions fail to show positive reversal-state behavior after the mechanical failure confirmation.

## Horizon and year diagnostics

High-minus-normal median daily contrasts:

- 15m: **-0.090410**
- 30m: **-0.065184**
- 60m: **-0.205106**

Both calendar years share the negative contrast sign:

- 2021: **-0.017960** across 67 dates
- 2022: **-0.109738** across 76 dates

This sign consistency does not rescue the hypothesis because the sign is opposite the frozen candidate direction and the absolute high-RV reversal state is negative.

## Threshold robustness

Alternative high-RV thresholds reverse the contrast sign:

- RV >= 1.0: **+0.034266** across 286 matched dates
- RV >= 1.5: **+0.080358** across 58 matched dates

Therefore the frozen threshold-robustness requirement fails decisively.

## Gate decision

**REJECT.**

The hypothesis fails because:

1. the primary high-minus-normal contrast is negative rather than positive;
2. the primary p-value `0.435028` exceeds `0.05`;
3. the daily primary-sign fraction `53.85%` is below `58%`;
4. high-RV absolute median reversal is negative rather than at least `+0.05`;
5. high-RV positive-reversal fraction `48.08%` is below `55%`;
6. both original breakout directions have negative median reversal scores;
7. the RV-threshold robustness controls flip the contrast sign.

No economic implementation is authorized.

This closes the high-volatility breakout / failed-breakout reversal lineage. The surviving parent information is only the previously established development-period realized-volatility persistence state. That state must not be treated as directional trading edge.

## Claims

- failed-breakout reversal development state pass: **false**
- independent confirmation: **false**
- executable edge established: **false**
- profitable edge established: **false**
- verified future OOS: **false**
- leverage authorized: **false**
- live enabled: **false**
