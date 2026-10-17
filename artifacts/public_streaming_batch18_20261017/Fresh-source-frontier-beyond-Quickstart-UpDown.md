# Bounded source frontier beyond Quickstart06 / UpDown40

17 October 2026. **No source admitted; zero new trading cells.** No batch18 outcomes, market datasets/caches, market backtests, repository edits or external orders.

Two calendar-related primary leads were inspected. Their commit/revision, paths, hashes, licensing and source defaults are retained in the companion JSON.

| Lead | Source mechanism | Decision |
|---|---|---|
| [Friday after-hours short script](https://gist.github.com/Cyril-the-Real/8da2ddd456523cd90424ccb2b160a048/d5e13bfe0e3f0bb00ec6004088b04ca613c3a989) | Short at an exact Friday16:00 New York timestamp; request cover during19:00–20:00; skip one specified date | Rejected for this Spot-long8h frontier. It is short-only, tied to equity after-hours, and published as escaped Markdown with unresolved native compilation/defaults. Refusing shorts creates no entry; reversing them would invent a rule. |
| [H22 Turnaround Tuesday](https://github.com/Quantheus/EURUSD_45Hypotheses_Research/blob/957a5ac471b8d5562a82d54c210ea64592beb3aa/EURUSD_Hypothesis_Research.ipynb) | Monday daily return beyond±0.3%; Tuesday08:00 row-close reference; previous-day extreme plus5EURUSD pips as stop;3R target | Quarantined. Detector defaults are available, but full shared simulator sizing/fill/exit lifecycle was not established. M5/calendar/pip assumptions cannot silently become crypto8h rules. |

## Extraction incident

The Tuesday source is a notebook. An overly broad code-cell filter selected the desired detector **and also a literal publisher performance-summary assignment** mentioning H22. Publisher numbers were therefore exposed in tool output. They were not calculated, validated, used for source selection or parameters, or repeated in these notes. Notebook output objects and batch18 outcomes were not selected.

The lead is quarantined rather than represented as a clean blind source-only admission. No additional search was used to replace it or fill a quota. Future extraction should select exact function definitions and exclude assignments, test invocations and outputs; reconsidering this notebook needs an independently blinded source review.

## Source and adaptation limits

The Friday gist carries an MPL-2.0 notice with blank author attribution. Its desired entry/cover clock is not proved by default next-tick execution, and exact New York16:00 does not align with ordinary00/08/16UTC8h opens. Sizing, pending/fill synchronization and missed-session behavior are not frozen.

The Tuesday repository is MIT, copyright Matouš Hajner. Its notebook does contain executable detector source; absence of standalone Python files was only a provisional inventory observation and is not evidence that rules were absent. The full notebook also contains unrelated excluded mechanisms and is not accepted as an isolated candidate artifact. No excluded mechanism was adapted or registered. Shared simulator defaults, complete-day/timezone admission, gap/stop/target ordering, cash sizing and endpoint behavior remain unresolved. Changing its absolute five-pip buffer or entry price anchor would be an explicit new design.

Calendar hypotheses differ from another moving-average or volume-state proxy. Nevertheless, session timing overlaps existing observational research, and Tuesday's contrarian-return premise overlaps Quickstart/UpDown and prior reversion families. Neither lead establishes independent edge.

## Next step

Continue the already prepared work. A future lane should start from an isolated primary implementation with complete causal entry, exit, sizing and order-state defaults. Do not reverse the short-only source, invent risk conversions, weaken gates, retune rejections or treat publisher performance statements as validation.
