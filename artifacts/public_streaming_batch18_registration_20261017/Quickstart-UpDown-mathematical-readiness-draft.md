# Quickstart06 and UpDown40 mathematical readiness draft

Design recorded at **2026-10-16 22:53:05 UTC**, before inspecting any EMV17 outcome. This fixes both sources for synthetic readiness work only. Neither is registered or market-tested by this draft. TD remains unadmitted.

## Common declared research scope

Three separate ETHUSDT, SOLUSDT and LINKUSDT sleeves each start with **10,000 USDT**. Fixed source units are preserved: Quickstart one unit; UpDown ten units. Source examples start with 100,000; reducing research capital is an explicit adaptation, with no quantity scaling or extra cash to rescue rejected orders. Pair selection is fixed, never conditional on funding or returns. The strategies are separate study drafts, not a combined portfolio.

Signals use completed 8h OHLCV bars. The first eligible feature close is **zero-based index 239**, when 240 bars have closed; earliest fill is **open index 240**. This differs by one bar from the retained earlier probe, which first allowed decisions at index 240 and fills at 241. Both timings will be tested separately and never silently substituted.

Mathematical feature values use only available history. Brokers remain flat with no pending orders during warmup. At admission, Quickstart has no fill clock; UpDown has no position or pending order. Their signal features are stateless functions of causal history, so no earlier source startup trade/state is carried. A declared streaming framework runtime (`preload=False, runonce=False`) supplies independent, bounded source-class comparisons. This is not unchanged default-preloaded bot parity.

Source quantities are all-or-reject at the next opening price. A request remains pending from signal close through that next opening event; no replacement, pyramiding, fractional resize, delayed retry, or capital increase is introduced. An unfunded request is terminally rejected and the strategy remains flat. Later entry attempts are allowed only when the unchanged source condition is true on a later eligible close. A terminal rejection clears the pending reference. A rejected exit retains its position and can be requested again at a later close only under the original exit predicate.

Baseline declared friction is **40 bps round trip**, booked as 20 bps per side for the synthetic mathematical checks. A separate price-impact convention must be frozen before registration; the synthetic funding fixture uses opening reference price plus explicit side charges, not hidden extra costs. Quickstart's source example leaves commission unset; the UpDown publisher harness specifies 0.1% per side. These source settings are disclosed, not substituted for the common research burden. No cost/control gate is weakened.

No protective stop, target, trailing order, or new holding timeout is added. At an end-of-segment/final cutoff, pending orders lacking a subsequent eligible opening event are canceled as **administrative no-fill**, not turned into a priced exit. Remaining positions are right-censored. No forced source exit, invented settlement, or realized return is created.

## Quickstart06

Source: official Backtrader tutorial `quickstart06.py`, commit `e20cea18b88e1693b65e408f8778cc076ab21a67`, SHA256 `47b82d6ae2e3940bff80450e8c17a7074204c1f7ff70f7e56a25fe0e988e0d4c`; Daniel Rodriguez, GPL-3.0-or-later. Source/framework remains outside Git.

- Entry: when flat with no pending request, `close[t] < close[t-1]` and `close[t-1] < close[t-2]`; buy **one unit**.
- Exit clock: completion at opening index **E** records the completed-entry bar. At completed close **E+5**, if still holding without a pending request, submit a one-unit sell; ordinary next-open fill is **E+6**. Do not replace this with a five-open hold.
- Equality does not satisfy either declining-close comparison. No order is created before two prior closes exist. This valid-history definition applies before the common cash-admission gate; it does not claim native default startup equivalence.

## UpDown40 actual source rule

Source: cloudQuant Backtrader test implementation, commit `b418caf7364e1134983a4c4b394768686e1916aa`, file `tests/strategies/test_85_up_down_candles_strategy.py`, SHA256 `35b643f11fb5aba0041fae5ae19ab3a8bf312865ef9be126ab8cfb2c181b45e4`; repository GPL-3.0. Its credited original repository is unavailable; original-author parity remains unestablished.

For index t with 40 prior closes, compute **`r = (close[t] - close[t-40]) / close[t-40]`** in that operation order. A zero denominator returns zero, following source behavior. Before valid history, the mathematical helper returns NaN and no advice. The unused 20-bar candle-strength indicator stays unused.

- Entry: when flat with no pending request and **r < −0.01**, buy **ten units**.
- Exit: while long with no pending request, the source's outer `abs(r) < 0.01` return gate applies; its long-close predicate is therefore **r >= +0.01**, not merely a positive return or a return near zero.
- Long-only scope explicitly refuses the upstream flat-position short-entry branch. No new short-to-cash exit predicate is introduced. Existing longs close only under the source long exit above.
- Equality at −0.01 does not enter; equality at +0.01 closes a long. No alternate precision tolerance or threshold is added.

## BTC benchmark contract

Each source sleeve has a separate BTC benchmark sleeve, initially 10,000 USDT. When an asset entry actually fills, record its entry notional as a fraction of that source sleeve's equity immediately before entry. Request that same fraction of the BTC sleeve's **own** pre-entry equity at the corresponding BTC opening reference, charging BTC's own declared costs. The benchmark follows the matched asset exit/censoring times. It never uses asset profits or scaled source-unit exposure as BTC profits. Its funding and cutoff handling are explicit and independent. A rejected asset entry creates no matched benchmark trade; a benchmark rejection is recorded rather than resized or silently repaired.

## Required synthetic evidence and limits

Own scalar/array feature agreement; future-tail/prefix independence; source numeric comparison only in the stated valid-history domain; index239 versus retained index240 admission; funded and unfunded fixed-size entries; terminal margin/rejection handling; zero denominator; pending lock and cancellation; exact boundary comparisons; source E+6 timing; final cutoff with no invented fill; long-only refusal of upstream shorts.

Full partial-fill, exchange lot/minimum, liquidity/gap/slippage, source-fork runtime and exceptional asynchronous callback parity remain unproved unless separately demonstrated. Mathematical all-or-reject behavior is a declared adapter, not proof that an actual exchange cannot partially fill. No registration or viable-candidate claim follows from passing synthetic fixtures.
