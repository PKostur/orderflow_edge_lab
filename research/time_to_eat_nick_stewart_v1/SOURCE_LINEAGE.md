# Time To Eat / Nick Stewart v1 Source Lineage

## Purpose

This file records source-adjacent lineage that can help interpret terminology without silently changing the Time To Eat specification.

Nick Stewart's Play Book 2.0 explicitly credits Don Vo for the Onion and Celery naming and says the Time To Eat team learned nuances from him. Don Vo's older public Forex Playbook is therefore useful corroborating context, but it is not automatically an authoritative specification for Nick Stewart's current implementation.

A Don Vo rule may enter the Time To Eat mechanical specification only when Nick's own material independently supports the same mechanic, or when it is explicitly frozen as a separate lineage-derived operationalization before any PnL is viewed.

## Corroborating Don Vo mechanics

The public Don Vo playbook makes a useful distinction between a setup and an entry. A setup is a market condition such as a close outside a range, while the entry is a later trigger such as a candle flip or break of a prior candle high/low.

### Breakout lineage

The older playbook describes a range followed by a close outside the range. It distinguishes a small-wick continuation variant, where the next candle is allowed to form and the trade triggers through the relevant prior candle high/low, from a steeper-wick variant that may use a current-candle flip. It also describes a Breakout plus Celery sequence when the initial breakout does not immediately push and a subsequent opposite-color candle respects the breakout area before the next trigger.

This is consistent with Nick Stewart's current public description that a breakout requires a range exit close and that entries can use current-candle or previous-candle high/low breaks. It does not resolve the exact Time To Eat rule for classifying a wick as small versus steep, nor the exact trigger selector.

### Celery lineage

The older playbook describes an opposite-color candle after a range break that remains outside the range and respects the relevant prior extreme. A stop entry is then placed through that confirmation candle's high/low in the breakout direction.

This materially corroborates Nick Stewart's Play Book 2.0 description of Celery / Booby Trap: after a breakout, a stalling or pullback candle is acceptable if it closes outside the range, regardless of body color, and its high/low can become the directional trigger.

It still does not resolve the exact range algorithm, support/resistance tolerance, order expiry, or re-entry policy.

### Onion lineage

The older playbook describes a bullish close at support within a range, or bearish close at resistance, followed by a high/low break entry aimed toward the remaining range or opposite boundary. It includes small-wick, steeper-wick, and Onion plus Celery variants.

This supports the general Time To Eat Onion concept of waiting for a pullback, then support/resistance confirmation, then taking a directional trigger. It does not resolve Nick Stewart's exact trend definition, support/resistance construction, wick classification, or trigger selector.

### Stops

The older playbook uses current-candle and previous-candle extremes as possible protective-stop locations depending on entry style. This is consistent with Nick Stewart's current public explanation. It does not establish a unique deterministic stop selector for the Time To Eat implementation.

## What this lineage does not authorize

This source lineage does not authorize:

- importing Don Vo's claimed profitability or win rate into the Time To Eat claim;
- treating every Don Vo setup variant as a Nick Stewart rule;
- resolving subjective concepts after observing backtest outcomes;
- choosing the best-performing wick, range, stop, or support/resistance definition post hoc;
- opening locked validation before a candidate freeze.

The Time To Eat v1 scoring gate therefore remains closed.
