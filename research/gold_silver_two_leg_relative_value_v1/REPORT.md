# Gold/Silver Two-Leg Relative Value v1 — Development Result

## Evidence boundary

This is a **post-observation retrospective development study**, not future OOS.

The protocol was frozen before any two-leg score at commit `b676aac8675d526359d63dff9da2d483a3044b89`.

Canonical development workflow run: `34954501434`

Canonical source head: `ef77e775db4149c9cb9c6b2ec3b3d4093bfcfbf0`

Artifact: `gold-silver-two-leg-relative-value-v1` (`10390194368`)

Artifact digest: `sha256:39dd7261820a2bb254d2943f3a227226f78f50f5abdb90c78e10fe3f0f0501bc`

The locked 2021-2023 internal validation and 2024-2026 retrospective extension were **not opened**.

## Why this experiment exists

The preceding one-leg XAU implementation used the gold/silver ratio to time long/short gold. It preserved state structure and raw economics across an independent cash feed but failed its frozen benchmark because returns remained materially exposed to long-gold beta.

This v1 experiment therefore changes the traded object itself: every strategy is an explicit two-leg gold-versus-silver spread with a causal hedge ratio fixed at signal time.

## Frozen design

- data: independent MT5-style cash XAUUSD/XAGUSD daily bars, pinned to external commit `bda79c6...`
- development: 2010-01-01 through 2020-12-31
- ratio signal: gold close / silver close
- z windows: 126 / 252 trading days
- thresholds: |z| >= 1.0 / 1.5
- modes: momentum / mean reversion
- holds: 21 / 42 trading bars
- hedges:
  - rolling 126-day return beta
  - rolling 63-day volatility ratio
- hedge-ratio clip: 0.1 to 2.5
- completed close -> next common open entry
- both legs enter and exit together
- one active trade
- 5 / 10 / 20 bps round-trip cost on total gross notional; primary 10 bps
- 126-calendar-day dependence clusters
- 10,000 fold-sign randomizations per cell
- BH-FDR q <= 0.10 state gate
- unhedged gold, static equal-dollar spread, and reversed-direction controls
- both long-spread and short-spread subsets must be positive for an economic pass
- neighborhood support required before candidate freeze

## Canonical outcome

- development rows: **2,834**
- cells evaluated: **32**
- state passes: **14**
- economic passes before neighborhood: **0**
- full development passes: **0**
- candidates frozen: **0**

### Strongest state-supported cell

`reversion__rolling_vol_ratio_63__zwin252__z1p0__hold21`

State evidence:

- median fold Spearman: **+0.365996**
- positive state folds: **84.62%**
- sign-flip p: **0.00009999**
- BH-FDR q: **0.003200**

Economics:

- trades: **71**
- median fold net at 10 bps: **+32.6216 bps**
- median fold PF at 10 bps: **1.9539**
- positive economic folds: **62.07%**
- median fold net at 20 bps: **+22.6216 bps**
- overall mean net at 10 bps: **-9.7609 bps/trade**
- reversed-direction mean net at 10 bps: **-10.2391 bps/trade**
- long-spread mean net: **-5.6281 bps/trade**
- short-spread mean net: **-11.0620 bps/trade**

This cell therefore contains a credible state relationship but does **not** meet the frozen executable-economic definition. The positive median fold result is not sufficient to override negative aggregate expectancy and negative directional subsets.

### Strongest raw-economic cells fail state evidence

Several momentum cells have positive development economics but their state relationship has the wrong sign under the frozen state definition. Examples:

- return-beta, z126 / 1.5 / hold42: median fold net **+29.44 bps** at 10 bps and mean **+94.73 bps/trade**, but state rho **-0.2115**, q = **1.0**.
- return-beta, z126 / 1.0 / hold42: median fold net **+16.93 bps**, mean **+46.56 bps/trade**, but state rho **-0.2687**, q = **1.0**.

They are rejected rather than promoted because the project protocol requires state evidence before PnL and does not allow an attractive PnL cell to redefine the state hypothesis after inspection.

## Decision

**Reject this specific ratio-z two-leg implementation as a promotable candidate.**

The important positive result is narrower: gold/silver ratio extremes contain statistically durable information about future hedged relative state, especially in mean-reversion form. The mapping from that state information to a non-overlapping 21/42-day executable strategy is not robust enough under the frozen economic and directional gates.

Therefore:

- do not open the 2021-2023 locked validation;
- do not inspect the 2024-2026 extension for this grid;
- do not test leverage;
- do not authorize future shadow or live execution;
- do not relax the economic gate around the attractive median-fold cells.

A future gold/silver experiment, if pursued, must change the mechanism rather than retune this grid. Reasonable distinct mechanisms include residual convergence with entry/exit bands, cointegration/error-correction dynamics, or event/macro-conditioned relative value, each under a new predeclared protocol.

## Claims

- state information in this grid: **yes**
- executable development edge: **no**
- locked internal validation opened: **false**
- verified future OOS: **false**
- profitable edge established: **false**
- leverage authorized: **false**
- live enabled: **false**
