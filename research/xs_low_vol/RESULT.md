# Cross-sectional low-vol premium (`xs-low-vol-v1`, declared `84cf303`): FAILS, not adopted

Long lowest-vol quartile, short highest-vol quartile, each side at unit ex-ante vol, weekly, 20 bps, funding proxy.

| Sample | S5 Sharpe | t | Max DD | Halves | 3-leg blend | 4-leg blend |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| Development (70 coins) | 0.09 | 0.21 | −70% | 0.25 / −0.11 | 2.12 | 1.81 |
| Confirmation (60 coins) | 0.15 | 0.35 | −73% | 0.16 / 0.14 | 1.35 | 1.15 |

No standalone premium, and adding it lowers the blend on both samples. Correlation with trend +0.2, with momentum −0.2,
so it is not a diversifier either. The multi-premia blend stays at three legs; no forward watch.
