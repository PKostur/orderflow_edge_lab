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
