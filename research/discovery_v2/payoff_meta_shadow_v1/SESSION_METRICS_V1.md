# DV2 Payoff Meta Forward Shadow: Session Metrics v1

Status: **EXPLORATORY OBSERVATIONAL DIAGNOSTIC ONLY**

Introduced: `2026-09-22`  
Frozen strategy prospective boundary: `2026-09-17T00:00:00Z`

## Purpose

Add intraday session attribution to the existing daily next-open-to-next-open forward shadow without changing the frozen strategy, payoff model, TRADE/PASS threshold, execution assumptions, or promotion state.

Because every frozen setup enters at the UTC daily open, assigning a setup to an "entry session" would be uninformative. Session metrics therefore attribute each completed 24-hour setup's realized price and funding PnL across the hours inside the holding period.

## Fixed UTC session views

Named session views:

- Asia: `00:00-08:00 UTC`
- London: `08:00-16:00 UTC`
- New York: `13:00-21:00 UTC`

London and New York overlap from `13:00-16:00 UTC`. Named-session totals therefore must not be added together.

For additive reconciliation, the report also preserves mutually exclusive buckets:

- Asia: `00:00-08:00 UTC`
- London pre-overlap: `08:00-13:00 UTC`
- London/New York overlap: `13:00-16:00 UTC`
- New York post-overlap: `16:00-21:00 UTC`
- Late transition: `21:00-24:00 UTC`

These are fixed UTC research windows. They do not shift for daylight-saving time.

## Attribution

Session attribution uses MEXC public 1-hour candles and the exact frozen setup weights. Each hourly price contribution is measured against the original setup entry notional so the exclusive hourly contributions telescope to the frozen daily open-to-open price PnL. Actual funding inside the holding interval is assigned to the hour in which the funding timestamp occurs.

Round-trip transaction costs remain separate from session PnL. The report reconciles the sum of all hourly gross contributions minus the exact frozen standalone round-trip cost against the already-existing `standalone_label_bps`.

## Research boundary

These metrics were defined after the September 17 prospective boundary and are therefore descriptive only.

They may be used to understand where prospective PnL accrued. They may not:

- change the frozen model or threshold;
- create a new session filter for the current shadow;
- retroactively rescue the failed D0 rule;
- count as D4 validation;
- justify candidate promotion;
- justify live execution or leverage.

Any future rule that conditions TRADE/PASS on a session result requires a separately frozen protocol before later observations are inspected.
