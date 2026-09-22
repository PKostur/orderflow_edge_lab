# Trading session metrics

`orderflow-session-metrics` analyzes strategy returns or market bars by DST-aware Asia, London and New York sessions.

This is separate from `orderflow-session-audit`, which is an operational paper-session integrity tool.

## Default sessions

The defaults are defined in local market time and converted with IANA time zones:

* ASIA: 09:00-18:00 `Asia/Tokyo`
* LONDON: 08:00-17:00 `Europe/London`
* NEW_YORK: 08:00-17:00 `America/New_York`

This is deliberately DST-aware for London and New York.

Membership is multi-label. A timestamp inside the London-New York overlap belongs to both sessions. The report also includes mutually exclusive regimes such as:

* `ASIA`
* `ASIA+LONDON`
* `LONDON`
* `LONDON+NEW_YORK`
* `NEW_YORK`
* `OFF_SESSION`

## Strategy/trade metrics

For a CSV, JSON or JSONL ledger with timestamps and net returns:

```powershell
orderflow-session-metrics path\to\trades.csv --mode trades --output session_report.json
```

The analyzer reports:

* observations and distinct dates;
* cumulative net bps;
* mean and median EV;
* win rate;
* average winner and loser;
* break-even win rate;
* profit factor;
* constant-notional max drawdown;
* largest-winner and top-three positive-PnL concentration;
* average MFE/MAE when present;
* delta in EV and win rate versus the all-session strategy baseline.

Supported timestamp fields are auto-detected, including ISO timestamps, exchange milliseconds and observation nanoseconds. Naive timestamps are rejected unless the caller explicitly provides a timezone-aware representation.

## Market-bar metrics

For OHLCV bars:

```powershell
orderflow-session-metrics path\to\bars.csv --mode bars --output market_sessions.json
```

Per session-day it computes:

* open-to-close return;
* absolute return;
* high-low range;
* realized volatility from bar-to-bar log returns;
* volume.

The report then aggregates average and median behavior across session-days.

## Market-condition integration

Future `orderflow-market-conditions` reports now carry both:

* legacy `utc_session` buckets;
* DST-aware `trading_session_regime`.

This lets existing order-flow signal families be stratified by named session without changing the signal definitions themselves.

## Research discipline

Session analysis is descriptive until a rule is frozen before new data.

A strong-looking session on an inspected period is not permission to:

* delete other sessions post hoc;
* change signal thresholds;
* alter exits;
* add leverage.

The intended workflow is:

1. measure session behavior;
2. inspect whether strategy economics differ for a plausible reason;
3. define a small session-context hypothesis;
4. freeze it;
5. test later untouched captures.

## ETF limitation

The current filtered ETF H1/H2 entries occur after the US open. In the exact historical ledgers, all 41 H1 trades and all 25 H2 trades fall inside the London-New York overlap under the default session definitions.

Therefore those ETF ledgers cannot identify Asia versus London versus New York session effects. Session conditioning is primarily useful for the project's 24-hour crypto/order-flow branches.
