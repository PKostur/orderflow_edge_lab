# Universal shadow operational monitor

This monitor explains why the frozen prospective watch may have no new completed trades. It is operational telemetry only and is not part of prospective evidence.

For each frozen strategy and symbol it reports:

- the currently executed frozen target position;
- whether that position was carried from before the prospective boundary;
- the most recent position-change boundary;
- any position changes that executed after the prospective start;
- counts of currently nonzero symbols, pre-start carryover positions, and post-start target changes.

The monitor uses the unchanged frozen strategy definitions. It does not filter trades, alter the shadow, change Jev v1, or authorize live trading.

A post-start position change here is an operational explanation of what the frozen target generator did. The prospective shadow remains the source of completed-trade evidence and keeps its existing scoring rules.


## First live checkpoint

At `2026-09-24T18:19:57.726213+00:00`, three frozen 8h execution boundaries had occurred since the prospective start: 00:00, 08:00, and 16:00 UTC.

Operational state at that checkpoint:

| Strategy | Nonzero symbols | Long | Short | Pre-start carryover | Post-start target changes |
| --- | ---: | ---: | ---: | ---: | ---: |
| DON8 | 10 | 9 | 1 | 10 | 0 |
| EMA8 | 10 | 10 | 0 | 10 | 0 |
| VOL8 | 10 | 10 | 0 | 10 | 0 |

The single DON8 short is LINK_USDT. Every other frozen strategy/symbol pair is long.

This explains the empty prospective trade ledger: all 30 strategy-symbol positions were already open before the frozen boundary, and none changed target at the first three post-start execution boundaries. These inherited positions are not prospective entries and remain excluded from prospective completed-trade evidence.
