# Monthly momentum state and economics study

Study `PSR3-MONTHLY-MOMENTUM-STATE`, hypothesis `PSM1-12M-1M-SPOT`: **REJECTED_AS_SPECIFIED**. Six fixed development gates fail. No prospective candidate, watch or retuned successor is created.

## Rationale and evidence boundary

After the public v1 candidates failed, this is one separate hypothesis about return persistence at a monthly horizon. [Moskowitz, Ooi and Pedersen](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum) motivate own-past-return persistence using a 12-month signal; [Liu and Tsyvinski](https://www.nber.org/papers/w24877) investigate crypto return predictability. Neither source establishes an edge for this specification. This original long-only USDT Spot adaptation has no volatility targeting, leverage, short leg or copied strategy implementation. It does not replicate either paper.

The design was committed as `6c2a37f0ba091f557d61efa19e61ed38c966f610` before computing this study's outcomes. Data were already inspected in earlier studies: the commit orders the development analysis but does **not** make the evidence untouched or prospective. The original public v1 candidates remain rejected. Existing DON8, EMA8, VOL8, DV2, D4, payoff studies, cross-sectional strategies and session watches are not modified or reinterpreted.

## Fixed semantics

At UTC month-end, compute the latest closing price divided by the closing price twelve calendar months earlier minus one. A strictly positive result predicts continuation/up and selects a long; zero or negative selects cash. Entry is the next month's 00:00 UTC first8h open, exit the following month's first8h open. Formation and held months must be complete; no gap filling or partial-month substitution. Consecutive selected months explicitly close/reopen and each pays the full stated round-trip sensitivity. This conservative accounting does not claim to reproduce the turnover of an optimized continuous-holding implementation.

The primary market-state endpoint is the positive-state mean future altcoin-minus-BTC return minus the nonpositive-state mean. Secondary direction accuracy is reported separately; no PnL-based feature selection occurs. Trading diagnostics follow with fixed 20/30/40/60/80 bps assumptions, BTC on identical holding windows and equal initial one-third coin sleeves. Each sleeve reinvests its own capital, earns zero while in cash and pays half cost multiplicatively at entry and exit. Event expectancy uses the separately labeled gross-minus-roundtrip-cost convention. Portfolio drawdown uses 8h open marks; MFE/MAE are candle extremes rather than achievable fills.

All source hashes bind the existing Binance Spot CSVs. Source grid: August 11, 2020 00:00–September 30, 2026 16:00 UTC. After excluding incomplete formation endpoints and unavailable following-month exit marks, evaluation entries are October 1, 2021–August 1, 2026, final exit September 1, 2026. September 2026 has no retained October 1 exit mark and is excluded without retrieving new data. BTC is the benchmark; ETH/SOL/LINK form 177 symbol-month observations across **59 shared calendar months**, not 177 independent observations. Positive state selects 93 trades in 39 months; nonpositive state supplies 84 observations in 35 months. Overlap skips and pending evaluated trades are both zero by disjoint monthly scheduling.

## State results before PnL

| Endpoint | Result |
|---|---:|
| Positive-state mean BTC excess | -52.9144 bps |
| Nonpositive-state mean BTC excess | +79.5678 bps |
| Primary state effect, positive minus nonpositive | **-132.4822 bps** |
| Descriptive 98% three-month block interval | [-661.9161, +428.8952] bps |
| Direction accuracy / always-up baseline | 53.6723% / 46.8927% |
| Leave-one-month-out state effect | [-236.1984, -39.3034] bps |

Leave-ETH/SOL/LINK-out state effects are +14.0155/-169.5369/-257.9695 bps. The by-symbol state effect is ETH -420.7966, SOL -95.1423, LINK +59.0987. The sign-classification improvement therefore does not demonstrate the fixed BTC-relative economic endpoint; no alternate endpoint is substituted after inspection.

The circular moving-block bootstrap resamples three successive shared months, retaining all coin rows, 2,000 draws, seed 20261010. All draws contain both states. Its interval is descriptive: it does not correct the full selection history or certify independent market cycles. The preceding 25-source/seven-family/nine-cell survey remains disclosed, with this one cell bringing the **minimum** count to ten. Ten is not a complete calibrated multiplicity correction across the whole repository.

## Economics and controls

| Round-trip cost | Mean event net | Equal-sleeve return | Maximum drawdown |
|---|---:|---:|---:|
| 20 bps | +212.1474 bps | -21.8100% | -67.0352% |
| 30 bps | +202.1474 bps | -24.1386% | -67.2544% |
| 40 bps | +192.1474 bps | -26.3984% | -67.4721% |
| 60 bps | +172.1474 bps | -30.7193% | -67.9029% |
| 80 bps | +152.1474 bps | -34.7882% | -68.3276% |

At 40 bps the median trade is -34.3906 bps, win fraction 48.3871%, arithmetic profit factor 1.2105, worst/best -4630.5707/+7113.4570 bps. Positive arithmetic expectancy coexists with a losing portfolio because trade averaging and compounded sleeve wealth are different estimands; large losses and capital paths matter. No serial trade compounding is substituted for portfolio results.

Mean MFE/MAE are +2262.7078/-1814.4532 bps; medians +1707.3947/-1440.0768. These bounds do not authorize stop/target optimization. The report retains strictly earlier completed-bar adversity before maximum favourable excursion; intrabar high/low order is unknown.

Unconditional monthly-long reference40: 177 events, net +194.6389 bps, BTC excess +9.9585, portfolio -46.7495%, drawdown -86.7709%. Inverted nonpositive-state control: 84 events, net +197.3973 bps, BTC excess +79.5678, portfolio -15.9500%, drawdown -65.1070%. Neither control becomes a selected strategy. The one-month-delayed state has net -187.2362 bps and excess -239.2358. Within-year shared-month permutation (500 draws) averages -118.5039 bps excess, descriptive 98% range [-373.8435,+123.0176]; 30% meet or exceed the observed selected excess. This preserves yearly per-symbol counts and shared mapping, but not runs or all serial dependence; the tail fraction is not a discovery p-value. Largest positive net60 monthly contribution is 15.8529%.

Failed gates: primary state hurdle above +80 bps, positive descriptive lower interval bound, positive leave-symbol effects, positive equal-sleeve portfolio at60, positive selected BTC excess and positive per-event lift over unconditional entries. Trade count, calendar count, both-state coverage and contribution limits pass. The report records every Boolean and all outcomes, without winner selection.

## Disposition, precision and next research step

The longer horizon covers transaction costs in arithmetic trade means but does not establish useful market-state prediction or compounded economic advantage. Reject the definition. Because this development screen fails, the predeclared conditional KuCoin replication is not triggered. Existing venue data are not searched for a rescue.

Only 59 shared months exist after formation/exit requirements; three-month blocks leave roughly twenty block-length units, not hundreds of independent trades. No adequately powered future study is established. Overlapping twelve-month signals and shared market regimes limit precision further. A future-only freeze or ongoing collector is not justified, regardless of engineering checks. The next research question should examine incremental BTC-relative information and capital-path economics before any strategy promotion, with a fresh identifier and practical precision design; changing the lookback, hold, threshold, exit or leverage here is not permitted.

## Reproduction

Set the repository `src` directory on Python's import path and run:

```text
python -m orderflow_edge_lab.monthly_momentum_state --output-dir work/monthly-state-rerun
```

The runner verifies exact committed design bytes and all original CSV hashes, refuses to overwrite its report, and does not retrieve new outcomes. Compare its report with `artifacts/public_monthly_momentum_state_20261010/report.json`. Tests cover calendar boundaries, strict past-only signals, missing grids, exclusion of the exit candle from excursions, and multiplicative fees/equal sleeves/cash.
