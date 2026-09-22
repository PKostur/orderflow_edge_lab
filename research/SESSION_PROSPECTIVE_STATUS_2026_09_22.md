# Prospective session watch status - 2026-09-22

Status: **ACCUMULATING / no eligible forward window completed yet**

## Boundaries

### W1 / W2

Prospective boundary: `2026-09-22T15:39:58Z`

Watches:

* `SESSION_W1_ALIGNED_SHORT_ASIA_OPENING`
* `SESSION_W2_ALIGNED_BTC_SHORT_ASIA_OPENING`

The frozen phase is `ASIA_OPENING`, the first third of the Tokyo session, which is 09:00-12:00 Asia/Tokyo.

Four new Continuous Order-Flow Discovery capture batches arrived after the boundary in the latest cumulative artifact. Their evaluated signal timestamps span approximately 16:06-20:26 UTC on 2026-09-22.

Those captures are New-York-only time under the frozen named-session definitions. Therefore:

* prospective W1 eligible signals: **0**
* prospective W2 eligible signals: **0**
* no development rows were backfilled
* no pass/fail interpretation is permitted

The first possible post-boundary Asia-opening window begins on 2026-09-23.

### W3

Watch: `WATCH_CVD_LNY_WIDE_RANGE_BTC_AGAINST_V1`

Prospective boundary: `2026-09-22T18:10:00Z`

Frozen filter requires:

* family: CVD
* regime: London + New York overlap
* spread: wide > 3 bps
* local range-to-spread: high > 6
* BTC flow alignment: against
* primary horizon: 30s
* primary cost: 4 bps
* stress cost: 8 bps

The 2026-09-22 London-New-York overlap had already ended before the W3 prospective boundary. Therefore W3 also has **0 eligible prospective observations** so far.

### Evidence-v2 cross-strategy forward watch

Frozen watch: `evidence_v2_cross_strategy_session_forward_v1`

Prospective start: `2026-09-23T00:00:00Z`

Primary hypothesis:

> The unchanged DON8 Donchian-55 8h strategy will continue to produce positive after-cost equal-weight portfolio contribution during 08:00-16:00 UTC and outperform its own 00:00-08:00 UTC contribution.

The successful pre-start workflow artifact correctly reports:

* days elapsed: 0
* scored intervals: 0
* Asia contribution: 0
* London/overlap contribution: 0
* formal verdict withheld

This is the expected result before the prospective start and confirms that pre-start development returns are not leaking into forward scoring.

## Repository integration

PR #112 opens the session-research branch against `main`.

The only merge conflict was `src/orderflow_edge_lab/session_metrics.py`, where `main` contained the DV2 fixed-UTC setup attribution API and the research branch contained the DST-aware named-session research API.

A two-parent merge commit reconciled both implementations without removing either API. PR #112 is now mergeable; CI remains the final integration gate.

## Current decision

No session-conditioned strategy is promoted.

No live-trading or leverage authorization follows from the current evidence.

The next valid evidence must come from timestamps after each frozen prospective boundary.
