# Gold/Silver Macro-Conditioned Relative Value v4 — Development Result

## Evidence boundary

This is a post-observation retrospective development study, not future OOS.

Protocol freeze commit: `21d89671df2d7d3f1920ec16df02733ab4ddd002`

Implementation freeze commit: `b6bbcd5e178cfb97c6d9ecff1fedb1fe244bccc1`

Canonical scored head: `8eefc4b7832dd172671f09eaaf34b13beab90b61`

Canonical workflow run: `34970268123`

Artifact: `gold-silver-macro-conditioned-relative-value-v4` (`10397336273`)

Artifact digest: `sha256:4a663ec0136173de60b8e8968a27d08b767aa6329d4942103f1a87badd7677fa`

The locked 2021-2023 internal validation and 2024-2026 retrospective extension were not opened.

## Question

Can lagged macro state predict which adaptive gold/silver dislocations are actually worth mean-reverting, without post-hoc suppression of the historically weak short-gold/long-silver sleeve?

The frozen prequential model used only prior dependence folds and the following completed/lagged features:

- absolute adaptive innovation z
- innovation side
- 252-bar VIX percentile
- 20-bar change in 10-year real yield (DFII10)
- 20-bar broad-dollar log return (DTWEXBGS)
- side interactions with each macro feature

Two state horizons were tested: 21 and 42 trading bars. The economic layer could trade only out-of-fold events with predicted success probability >= 0.60. Both spread directions still had to work.

## Canonical result

- state hypotheses: **2**
- state passes: **0**
- economic cells: **2**
- economic passes: **0**
- full development passes: **0**
- candidates frozen: **0**

### 21-day state model

- qualifying out-of-fold events: **116**
- scorable folds: **4**
- median fold AUC: **0.0563**
- positive-AUC fold fraction: **25%**
- median fold Brier: **0.2270**
- median constant-rate Brier: **0.2366**
- AUC sign-flip p: **1.0**
- BH-FDR q: **1.0**
- state pass: **false**

Fold AUCs were approximately 0.576, 0.102, 0.011 and 0.000. The model therefore does not generalize directionally; most scored folds are strongly anti-predictive.

The 0.60 probability filter produces only **3 non-overlapping trades**, all short-spread. At 10 bps costs:

- median fold net: **-246.99 bps**
- mean net: **-164.56 bps/trade**
- median fold PF: **0.504**
- long-spread trades: **0**
- short-spread trades: **3**, mean **-164.56 bps/trade**

### 42-day state model

- out-of-fold events: **6**
- scorable folds: **1**
- median fold AUC: **0.0**
- state pass: **false**
- filtered trades: **0**

It fails both breadth and predictive-value requirements.

## Interpretation

The repeated gold/silver research sequence now supports a narrow conclusion:

- relative dislocations do contain state information about subsequent convergence;
- that state information has not translated into robust symmetric executable PnL under ratio-z, rolling error-correction, adaptive equilibrium, or macro-conditioned filtering;
- the persistent directional asymmetry is not explained by this lagged VIX/real-yield/USD feature set;
- disabling the losing spread direction after inspection would remain post-hoc and is not permitted.

## Decision

**Reject v4 and close this gold/silver convergence lineage for now.**

Do not:

- open 2021-2023 validation;
- inspect 2024-2026 for this model;
- invert the classifier because the development AUC is below 0.5;
- drop the short-spread side post-hoc;
- relax probability, trade-count, direction, or state gates;
- test leverage;
- authorize shadow or live execution.

The next gold research lane should be structurally orthogonal rather than another convergence rescue. The recommended next mechanism is scheduled macro-event reaction/continuation versus reversal around CPI, FOMC and U.S. payroll releases using intraday gold data, with event definitions frozen before any PnL inspection.

## Claims

- macro-conditioned state edge: **no**
- executable development edge: **no**
- locked internal validation opened: **false**
- verified future OOS: **false**
- leverage authorized: **false**
- live enabled: **false**
