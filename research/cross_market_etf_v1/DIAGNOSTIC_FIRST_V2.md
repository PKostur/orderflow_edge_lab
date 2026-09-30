# Diagnostic-first strategy research v2

This document adds a simpler exploratory layer before formal candidate freezing.

It does not rewrite or invalidate prior frozen results. Existing frozen family IDs and their historical verdicts remain immutable audit records.

## Why this layer exists

The previous ETF D0 framework asked broad robustness questions before answering the more basic trading questions:

1. Does the signal get direction right often enough to be interesting?
2. When direction is right, how far does price actually travel?
3. What is the realized expectancy under a simple executable exit?
4. How much favorable movement is being left uncaptured?
5. How much adverse excursion occurs before or during successful trades?

A signal can fail a finished-strategy robustness gate while still containing useful directional or excursion information. This layer is intended to diagnose that information before strategy construction.

## Stage A: signal diagnostics

For every raw signal family, report first:

* Directional win rate: fraction of signals whose gross executable return at the diagnostic exit is positive.
* Net win rate: fraction still positive after the simple frozen friction haircut.
* Average net win.
* Average net loss.
* Net expectancy per signal.
* Average and median maximum favorable excursion (MFE).
* Average maximum adverse excursion (MAE).
* Average and median MFE conditional on the frozen direction finishing positive.
* Favorable-excursion hit rates at practical movement thresholds.
* Realized capture ratio: realized favorable return divided by MFE on directionally correct signals.

These are descriptive diagnostics, not promotion gates.

## Stage B: strategy construction

Only if Stage A shows potentially usable signal or excursion structure:

* Use the discovery window to design one simple trade-management rule.
* Possible components include stop placement, profit target, time exit, break-even logic, or trailing logic.
* Prefer economically interpretable levels suggested by the MFE and MAE distributions rather than large parameter grids.
* Once one concrete rule is chosen, assign a new candidate ID and freeze it before any holdout result is viewed.

Any stop, target, exit, or filter designed after viewing discovery diagnostics creates a new candidate ID. It is not a rescue of the old frozen family ID.

## Stage C: validation

After the new candidate is frozen:

* Evaluate the untouched historical holdout.
* Use realistic friction and slippage.
* Then perform independent replication where possible.
* Then prospective future shadow.
* Leverage or live trading remains prohibited until those later stages support it.

## Practical principle

Early research should filter signals primarily by directional information, expectancy, and excursion structure.

Broad cross-ticker robustness, calendar-half consistency, reversed controls, and concentration remain useful evidence, but they should not automatically terminate exploration before the underlying signal behavior has been understood.
