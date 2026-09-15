# Gold Macro Event Reaction v1 — Development Result

## Evidence boundary

This is a **post-observation retrospective development study**, not future OOS.

The strategy protocol was frozen before scoring. The final successful run changed only event-calendar acquisition/materialization after hosted-runner HTTP failures; it did not change the 12 strategy cells, event semantics, costs, state gates, or economic gates.

Canonical scored source head: `070f18f0362bad94e01e17feb0f132a03406bf1f`

Canonical workflow run: `34972106226`

Artifact: `gold-macro-event-reaction-v1` (`10398380143`)

Artifact digest: `sha256:cb01262685bb43b7846b706f1f56ee260586ab01c9f0e4038b03afb0a7c02ba0`

The 2023 locked internal validation and 2024-2026 retrospective extension were **not opened**. Leverage was not tested.

## Data integrity

- XAUUSD M15 source rows: **190,665**
- development bars (2018-2022): **104,533**
- median full-day bars: **92**
- scheduled development events: **159**
  - CPI: **60**
  - Employment Situation: **60**
  - regular scheduled FOMC decisions: **39**
- event calendars are vendored from official BLS/Federal Reserve schedules so the canonical scorer has no runtime event-calendar network dependency.

Exact-bar admission reduced usable events for the strategy cells to:

- CPI: **49**
- Employment Situation: **50**
- FOMC: **34**

No missing event/entry/exit bars were interpolated.

## Frozen design

Each event measures the first 30-minute XAUUSD reaction, enters at the exact M15 open 30 minutes after the scheduled release, then tests:

- continuation vs reversal of the initial reaction;
- 60-minute vs 180-minute holding horizons;
- CPI, Employment Situation, and FOMC separately.

This gives **12 predeclared cells**.

State evidence is event return in excess of matched same-time placebo observations at +/-7 calendar days. State dependence uses 182-calendar-day clusters with 20,000 sign flips and BH-FDR across the 12 frozen cells.

Execution costs are 3/5/10 bps round trip, with 5 bps primary and 10 bps high-cost stress.

## Canonical outcome

- cells evaluated: **12**
- state passes: **0**
- economic passes: **0**
- full development passes: **0**
- candidates frozen: **0**

### CPI

CPI continuation over 180 minutes is the best raw CPI cell:

- usable events/trades: **49**
- median fold event-minus-placebo state excess: **+3.38 bps**
- positive state folds: **66.7%**
- state sign-flip p: **0.3622**
- BH-FDR q: **1.0**
- median fold net @5 bps: **+5.07 bps**
- median fold PF: **1.30**
- positive economic folds: **55.6%**
- mean net @5 bps: **+9.69 bps/trade**
- long trades mean: **+22.49 bps/trade**
- short trades mean: **-0.74 bps/trade**

It therefore fails state significance, fold stability, and the both-direction economic requirement.

The other CPI cells are negative or weaker.

### Employment Situation

No payroll cell is close to promotion. The 180-minute continuation state excess is mildly positive (**+3.85 bps median fold**) but has only **55.6%** positive state folds and q **1.0**. Economics are negative overall (**-1.40 bps/trade** @5 bps), with long trades negative and short trades positive.

The 180-minute reversal cell has a positive median-fold net (**+2.22 bps**) and PF **1.12**, but aggregate mean is **-8.60 bps/trade**, state evidence has the wrong sign, and the long sleeve is strongly negative.

### FOMC

The strongest-looking raw cell in the entire tournament is:

`fomc__reversal__hold180m`

- usable events/trades: **34**
- median fold event-minus-placebo state excess: **+20.27 bps**
- positive state folds: **77.8%**
- state sign-flip p: **0.2267**
- BH-FDR q: **1.0**
- median fold net @5 bps: **+11.00 bps**
- median fold PF: **1.82**
- positive economic folds: **77.8%**
- mean net @5 bps: **+8.77 bps/trade**
- reversed-direction mean net: **-18.77 bps/trade**
- long trades: 17, mean **+20.19 bps/trade**
- short trades: 17, mean **-2.65 bps/trade**

Despite attractive raw economics, it fails the frozen state-significance test by a wide margin after dependence-aware placebo adjustment, its short sleeve is negative, and the paired 60-minute FOMC reversal horizon is negative. It is therefore **not a candidate**.

FOMC 60-minute continuation/reversal and 180-minute continuation are negative after costs.

## Interpretation

The simple post-release claim — trade the first 30-minute gold move either as continuation or reversal for the next 1-3 hours — does **not** produce a robust development edge across CPI, payrolls, or FOMC under matched-time placebo controls.

FOMC 3-hour reversal is an interesting descriptive pattern, but this experiment does not establish it as an edge. Testing additional thresholds, reaction windows, or only the profitable direction after seeing this result would be post-hoc tuning and requires a new separately frozen protocol.

## Decision

**Reject Gold Macro Event Reaction v1.**

Therefore:

- do not open the 2023 locked validation;
- do not inspect the 2024-2026 extension for these 12 cells;
- do not freeze the FOMC 3-hour reversal cell as a candidate;
- do not lower state-significance or directional gates;
- do not test leverage;
- do not authorize shadow or live execution.

A future event lane, if pursued, must add genuinely new information rather than retune timing. The most defensible next question is whether **release surprise magnitude/sign** (actual versus consensus) or pre-release positioning/volatility predicts post-event gold behavior. That requires a new pinned surprise dataset and a fresh protocol before PnL inspection.

## Claims

- scheduled-event state edge: **no**
- executable development edge: **no**
- locked internal validation opened: **false**
- verified future OOS: **false**
- profitable edge established: **false**
- leverage authorized: **false**
- live enabled: **false**
