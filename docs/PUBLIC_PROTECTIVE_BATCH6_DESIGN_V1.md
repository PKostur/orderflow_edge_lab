# PSR12: public protective batch 6, frozen before outcomes

Two independently implemented mathematical adaptations, PSARReference8hSpot and CMF21Spot8hMinuteCloseROI. The configuration is the complete mechanical contract. Sources and primary framework/reference audits are pinned and retained. No source code is copied; no native execution parity is claimed. Bollinger is excluded. Prior definitions, results, payoff geometry and prospective watches remain frozen.

## PSAR

From the pinned Parabolic SAR Pine source: .02 initial/increment, .2 maximum, strict close crosses, reverse-to-cash, ATR14 stop3 and target2. Use the official documented recurrence: undefined bar0; bar1 close increase seeds bullish otherwise bearish, prior opposite extreme and current directional extreme; advance SAR, test strict reversal, reset on reversal, otherwise increment acceleration only after first trend bar and strict new extreme, finally clamp prior one/two opposite extrema. Continuous fixed origin, no restart at warmup. The pinned Rust SAR failed synthetic parity before market outcomes, so it is excluded. Each original long qualifying close reanchors brackets even if held or control entries differ.

## CMF

CMF21 below0 enters, above0 exits. Preserve the published arithmetic order and rolling21 NaN behavior. This is an explicit5m to8h adaptation, not an unchanged native bot. Stop is5% of actual accepted entry. ROI uses the native fee-aware profit ratio with a declared0.1% fee each side, Python rounding to8decimals and strict >1%. Inspect completed minute close, queue exit for next minute open. No resting ROI target or high-touch fill. Known source exit takes reason priority over queued ROI at a shared boundary; stop is processed before the same minute close ROI observation. Native limit/off-exchange defaults and tick rounding are adapted to continuous reference prices and hypothetical market exits. Fees plus friction use unchanged20/40/60/80bps cases. Fee in ROI trigger is fixed; total economic cost varies independently. No intrabar re-entry, timeout, borrowing or pyramiding.

## Evidence contract

Reuse the already audited longest common complete segment2023-04-01 through2026-09-30, four Binance Spot symbols including funded BTC reference, 240bar warmup. Signal/strategy sleeves are ETH, SOL, LINK; BTC is benchmark. This has no2022bear coverage and is spent development evidence. Data choice is unchanged and quality based. Preserve source hashes, cache binding, fixed signal-close quantity, next-open affordability rejection, same-minute uncertainty enumeration for PSAR, cash/BTC accounting and censored cutoff observations. Controls rerun the same causal engine, including original bracket updates, with their own endogenous durations.

Use unchanged500 randomized-entry controls,7bar lag,2000 moving4calendar-week bootstrap draws with zero-event weeks, alpha.05/2 descriptive intervals, per-symbol/year/session/cluster/MFE/MAE/BTC diagnostics and all existing numeric gates. Full trial accounting is19registered trading cells/20signal-model cells after these two. Source searches and related variants are not independent successful trials. No repeated-search global inference.

Any screen survivor requires a new immutable future-only confirmation protocol frozen before observation, adequate samples, actual execution/cost calibration and paper reliability. A survivor is never a viable candidate yet. No orders are authorized. Rejections remain recorded without retuning. Runtime and reused dependencies are bound in configuration; commit both design and evaluator before market outcomes.
