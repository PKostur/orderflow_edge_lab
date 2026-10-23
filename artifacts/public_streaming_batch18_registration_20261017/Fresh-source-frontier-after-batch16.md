# Source frontier after batch 16

Completed 17 October 2026. Source inspection and synthetic execution only: no market data, market returns, registration, repository changes, or external orders. EMV17 remains separate.

## Three bounded leads

| Source | Published mechanics | Readiness finding |
|---|---|---|
| [Official Backtrader quickstart06](https://github.com/backtrader/backtrader-docs/blob/e20cea18b88e1693b65e408f8778cc076ab21a67/docs/quickstart/quickstart06.py) | Buy after two strict declining-close comparisons across three closes. Fixed default one unit; initial cash 100,000. Submit exit five bar counts after entry completion. | Clear rule, but unguarded startup reads preloaded future rows. Synthetic execution confirms entry open **E**, exit open **E+6**, rather than a five-open hold. |
| [cloudQuant TD Sequential](https://github.com/cloudQuant/backtrader/blob/b418caf7364e1134983a4c4b394768686e1916aa/tests/strategies/test_65_td_sequential_strategy.py) | Lag four, setup nine, countdown thirteen; buy ten units on its ideal buy condition, close on its ideal sell. Several declared cancellation options are unused or no-ops. | Startup future contamination reaches persistent setup state. Order submissions do not establish the advertised pending-order reference. No unchanged causal port accepted. |
| [cloudQuant UpDownCandles](https://github.com/cloudQuant/backtrader/blob/b418caf7364e1134983a4c4b394768686e1916aa/tests/strategies/test_85_up_down_candles_strategy.py) | Actual signal is contrarian 40-bar return: enter long below −1%; close long at **at least +1%**. Ten units. Its candle-strength feature is unused. | First return requests one unavailable historical observation. Synthetic future mutation changes the first order side. Explicit cash-origin and eligible-state proofs remain necessary. |

All three lack active source stops and targets. The quickstart exit clock is published; no new timeout or protection was invented. The cloudQuant test harnesses specify cash 100,000 and commission 0.1%; exchange spread, slippage, cash limits, precision and 8h adaptations remain separate declarations.

## Synthetic evidence

A hash-checked Backtrader 1.9.78.123 wheel executed the actual pinned strategy classes with logging suppressed. Upstream market-loading and result/assertion code was excluded. Each class received two 64-bar synthetic fixtures whose first 63 bars were identical; only the final bar changed.

- Quickstart: the first pending entry changed; observed fills changed from indices 1/7 to 3/9.
- TD: index 4 changed from no buy trigger/count zero to buy trigger/count one.
- UpDown: index 39 changed from return −0.76 to +23.0, producing opposite order sides at index 40.

This proves startup contamination in the tested runtime. It does not establish full cloudQuant fork-native parity, eligible-period contamination after a declared cash reset, or an economic result. Proof details are retained in `Fresh-source-frontier-native-synthetic-proof.json`.

## Provenance and licensing

The official tutorial carries Daniel Rodriguez attribution and GPL-3.0-or-later. cloudQuant publishes the inspected test implementations under repository GPL-3.0 and credits earlier repositories; original-author parity remains unestablished. The referenced TD repository was pinned, but its license was not established; the credited UpDown repository returned 404. Source, framework and harness code stays outside Git; the repository receives no copied GPL implementation from this survey.

The companion JSON records immutable commits, exact file hashes, source defaults, state quirks, dependency evidence, and scope limits. This is three source leads and **zero new trading cells**, not three tested candidates.

## Concrete next step

Draft either the two-down-close rule or the actual 40-bar contrarian-return rule as an explicitly declared mathematical Spot port. Preserve the source entry/exit numbers, define a 240-completed-bar **flat cash admission**, and prove that no startup position, pending order, or future-contaminated persistent state enters the eligible period. Then verify source-sized cash feasibility, terminal-order handling, next-open timing and future-prefix independence using synthetic fixtures before registration.

TD needs a separate causal initialization and pending-order/state contract. Replacing its startup guard or implementing missing textbook cancellation rules would be a declared redesign, not unchanged replication. OBV's outstanding callback lifecycle remains unresolved.

All frozen lanes, existing rejections, costs, controls, acceptance gates and untouched-future requirements remain unchanged. No viable candidate or exhaustive source-search claim is made.
