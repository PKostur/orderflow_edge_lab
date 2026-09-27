# Multi-horizon trend ensemble: result (not adopted)

- Protocol: `trend-horizon-ensemble-v1`, declared in `43976bb`
- Adoption rule: at least as good as the core on both coin sets, in both halves
- Status: descriptive, on seen data

| Book | Sharpe | t | Max drawdown | Halves (2020–23 / 2023–26) |
| --- | ---: | ---: | ---: | --- |
| core17:core | 1.19 | 2.83 | -15.2% | 1.24 / 1.17 |
| core17:ensemble | 1.19 | 2.81 | -15.0% | 1.29 / 1.09 |
| untouched53:core | 0.91 | 2.00 | -19.6% | 0.97 / 0.85 |
| untouched53:ensemble | 0.96 | 2.13 | -17.4% | 1.09 / 0.83 |

## Reading

The ensemble is at least as good overall and in the first halves, with a
slightly shallower drawdown on the 53 untouched coins. It is marginally worse
in the second half on at least one coin set, so it fails the declared rule.
The core's two horizons are not improved on robustly. Keep the core.
