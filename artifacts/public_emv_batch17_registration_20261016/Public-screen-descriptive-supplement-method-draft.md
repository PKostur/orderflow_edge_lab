# Historical descriptive supplement v1 — method draft

This completes descriptive reporting requested in the original uploaded specification: best/worst returns, median excursions, adverse movement before the favorable maximum, correct-direction frequency, movement remaining after costs, positive weeks, concentration, matched-BTC beta sensitivity and raw-signal session distribution. The existing frozen ledgers, strategy rules, fills, parameters, controls, acceptance gates and decisions are inputs and remain unchanged. Zero new strategy trials. This is not a prospective protocol or a new route to promotion.

The method is defined after the KAMA screen and before loading raw paths for this supplement. Its descriptive status and timing must be recorded. KAMA's seven-gate rejection cannot be changed by these metrics. Future candidate supplements may use these definitions frozen before their market results. No data-selected threshold, filter, hedge, sizing or favorable peak execution is introduced.

## Event population and accounting

Report all admissions and completed events separately. Retain CENSORED_MTM status and include final known minute highs/lows through the cutoff; never count a cutoff as a completed trade. Worst/best admissions are ordered by per-unit net basis points and retain symbol, entry time, endpoint status and cash PnL. This is different from ranking cash PnL or pooling funded portfolio returns. Cumulative return continues to use the original separate cash/NAV portfolio paths.

Report medians of lower and upper MFE and MAE bounds, strict-positive endpoint gross-return frequency, and definite/possible positive-excursion frequency. Means and original return/portfolio diagnostics remain in the unchanged result. A trade's mean/median bounds are descriptive bounds, not evidence that both endpoints can occur jointly.

## Adversity before the first favorable maximum

Only minute OPEN entries are supported: require entry_price equal the entry minute OPEN; intraminute and legacy eight-hour entry adapters are refused. Use the original event's minute indexes, entry price, reference endpoint, endpoint interval and MFE/MAE bounds, bound to the retained validated minute panel. Recompute the original MFE/MAE envelope and reject a mismatch. Completed OPEN exits exclude later endpoint-minute high/low; cutoff CLOSE marks include the full final known minute. Entry OPEN is always a candidate maximum. Repeated maxima use the first attaining minute, not a later tie chosen to improve the result.

If the entire held path's maximum is already its entry OPEN, adverse excursion before that first maximum is zero. If a global maximum is identified in a fully held minute, prior minute lows and that minute's OPEN are known to precede it. Its LOW might precede or follow an intraminute HIGH. The pre-first-MFE adverse-price interval therefore runs from min(prior known low, peak-minute LOW) to prior known low. When the maximum is the minute OPEN, its later LOW is excluded from both endpoints. Convert prices to negative/zero entry-relative bps. If the first maximum is the endpoint OPEN, use only prior fully held minute lows; exclude all later endpoint-minute extremes.

For an ambiguous intraminute protective exit whose possible maximum is unresolved in its exit minute, use a conservative bound from the original full-path MAE lower bound to zero and record the first-maximum minute as undefined. A strictly identified larger prior maximum can still use the full-minute method. These are partial-identification bounds; no tick order, stop/target path repair or exact peak time is claimed.

Report original MAE through the endpoint and gross MFE giveback to the endpoint. Apply original side burden to the known/possible peak-price envelope as (peak/entry)*(1-side)/(1+side)-1. Label it a hypothetical retrospective peak net move, never a realized/available peak fill or an exit optimization. Its signs describe whether movement could clear friction, not whether the bot captured it.

## Calendar, concentration and BTC sensitivity

Report active entry-week mean returns and positive-week fractions using both active weeks and the original full calendar denominator including zero-event weeks. No week, symbol or month is selected. Existing clustered bootstrap, leave-out, year and causal BTC-state diagnostics remain unchanged.

For symbol, entry month and entry week, allocate the sum of absolute individual-event cash PnL, alongside signed cash PnL, counts, allocation shares and their HHI. Do not substitute absolute group net PnL; losses can cancel profits inside a group. These measures reflect actual source sizing/cash paths and are not an equal-risk comparison.

Fit unweighted paired-event net-return OLS against matched BTC net returns separately at each BTC endpoint-reference scenario. Report slope and intercept; constant BTC returns or fewer than two observations produce undefined values. Endpoint-scenario fits are sensitivities, not beta confidence bounds. Overlapping durations, symbol mixtures and clustered observations remain dependent. Intercepts are not causal alpha, an executable hedge or evidence of incremental information. Completed-only sensitivity is separate.

## Cost and clock descriptions

Report exact two-notional-side reference returns at10/20/30/40/60/80 nominal round-trip bps, conditional on the unchanged baseline admission set, entry/endpoint prices and durations. Existing20/40/60/80 funded simulations remain authoritative for their cash outcomes. The additional10/30 rows are conditional price-return arithmetic, without counterfactual funding/admission/quantity claims, new strategy trials, weakened gates or rescue of rejected versions.

Raw eligible BUY flags use completed-candle availability time, including ignored/rejected and final-unexecuted flags; the warmup begins at feature index warmup_bars-1. The last signal becomes known at the cutoff but has no next available OPEN. Use the existing fixed UTC session labels: Asia[00,09), London[07,16), New_York[13,22), with nonexclusive region and exclusive membership counts. No DST/exchange-hour, within-candle arrival-time or session-filter inference. Accepted-entry clocks remain separate.

## Validation and provenance

Synthetic tests cover OPEN/CLOSE endpoints, intraminute ambiguity, first tied maxima, peak-at-OPEN low exclusion, no favorable move, medians/extremes, calendar zeros, cash concentration, known/undefined beta, cost arithmetic, warmup/session clocks and no mutation. Independent method/code/test review is required before applying the supplement to retained paths. Record exact source, test, method, input-result and data/receipt hashes. A later execution SHA must not be substituted into an earlier immutable report. No source decision is recomputed or promoted by this supplement.
