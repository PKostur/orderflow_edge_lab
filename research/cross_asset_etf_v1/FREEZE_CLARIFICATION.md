# Cross-asset ETF v1 — pre-result calculation clarification

Frozen before any strategy PnL is calculated.

- Session identity is UTC calendar date. September 2026 regular-session minutes are evaluated exactly in the frozen UTC windows.
- Returns are arithmetic executable proxies: `direction * (exit_open / entry_open - 1) * 10,000` bps.
- Net return subtracts the frozen round-trip friction once per signal. Primary discovery gate uses 5 bps; 2 and 10 bps are reported diagnostics.
- Fully reversed control uses identical signal, entry and exit timestamps with direction multiplied by -1 and identical friction.
- ORB15 requires all 15 opening-range minutes 13:30..13:44 UTC, the chosen signal minute, exact next-minute entry, and exit open exactly 15 minutes after entry. The first qualifying breakout from 13:45..14:44 is the only signal for that ticker/session.
- BB20 requires 20 exact consecutive one-minute closes ending at the signal bar. Population variance is `mean(x^2)-mean(x)^2`; zero or negative numerical variance is ineligible. Signal z is `(close-mean20)/sd20`.
- BB20 signals are processed chronologically per ticker/session. After accepting a signal at time `t`, entry is `t+1m`, timed exit is `t+11m`, and no signal with timestamp `< t+11m` may be accepted. A signal exactly at the prior timed exit is eligible if all other conditions pass.
- Every signal is one pooled observation. Instrument and session PnL contributions are sums of 5-bps net signal returns.
- Positive-PnL concentration uses positive contributions only: largest positive contribution divided by the sum of positive contributions. If no positive contribution exists, the concentration gate fails.
- A family failing any discovery gate is terminally falsified under that ID and its August replication performance is not inspected.