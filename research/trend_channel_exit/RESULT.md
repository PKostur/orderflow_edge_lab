# 20-bar channel trailing exit: result (rejected)

- Protocol: `trend-channel-exit-v1`, declared in `da679d0` before evaluation
- Crypto: 17 perps, 8h, 2020-06 to 2026-09
- Sizing and accounting: inverse-vol, v3, 20 bps
- Status: descriptive, on seen data

| Variant | Sharpe | t | Max drawdown | Down / flat / up month mean | Time in market | Trades |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| core | 1.36 | 3.13 | −13.9% | +0.34% / −0.56% / +5.14% | 88% | 964 |
| core + exit | 0.90 | 2.18 | −10.5% | +0.41% / −0.91% / +2.71% | 66% | 1,586 |
| DON8 → + exit | 1.29 → 0.83 | | −19.8% → −12.0% | down −0.04 → +0.24, up 5.43 → 2.68 | | |
| EMA8 → + exit | 1.28 → 0.80 | | −11.3% → −8.8% | down 0.61 → 0.45, up 4.15 → 1.61 | | |

Year 2021: core +93%, core + exit +25%.

## Reading

The faster exit halves the up-month capture by ejecting positions on normal
pullbacks inside big trends. It barely helps in down months and adds
whipsaw losses in flat ones. Its lower drawdown comes only from less time in
the market. The slow, symmetric exit of the frozen rules is part of the edge.
Rejected. Crash lag should be addressed with a leading signal, not a faster
exit.
