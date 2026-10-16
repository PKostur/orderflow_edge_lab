# KAMA mathematical specification draft — not registered

This is a specification for an independently authored mathematical implementation. No market test, registered candidate or production approval. The original AGPL Go/helper/harness/build remain outside Git. Source URI/hash and synthetic numerical receipts provide provenance; no GPL-family source is to be copied into the repository.

Source: Hulme-Labs/indicatorgo pinned35bd387db11de8e544ad545c68f198677ce4c6b7, strategy/trend/kama_strategy.go and trend/kama.go. Source action is a repeated state comparison, despite crossing language in its prose. Native proof:4714 KAMA values/4924 actions,21 fixtures,11 prefix/3 future checks; see independent source readiness receipt.

## Equations and initialization

Let p[i] be the finite positive completed-bar close. Fixed ER period10, fast period2, slow period30. Maintain d[i]=abs(p[i]-p[i-1]) for i>=1. The rolling denominator contains the last10 differences. Its arithmetic uses Neumaier compensated addition: for signed term x and current sum S, form T=S+x; add (S-T)+x to correction C when abs(S)>=abs(x), otherwise add (x-T)+S; then set S=T. Process the incoming d[i] before the negative outgoing d[i-10] (outgoing is0 for the first10 differences). Maintain a10-element circular buffer in original arrival order. If S+C is nonfinite, clear S/C and recompute current buffer entries in physical index order0..filled-1. Publish denominator V[i]=S+C for i>=10.

At i=10 seed previous adaptive level with p[9]. E[i]=abs(p[i]-p[i-10])/V[i]. IEEE0/0 is NaN, not an opportunity to substitute0 or a default ratio. Let f=2/3 and s=2/31, and a[i]=(E[i]*(f-s)+s)^2. Adaptive level K[i]=previousK+a[i]*(p[i]-previousK); carry K without resets. Preserve the sequence of scalar double operations. First public KAMA is at index10; indices0..9 have no indicator output. Source NaN persists recursively even after the denominator recovers; do not restart the level.

Native source prepends10 HOLD recommendations even when input has fewer than10 observations. A candidate interface must return only already-available bar slots: first min(10,n) are HOLD and no phantom bars are introduced. This is an explicit adapter alignment contract, not a claim that native stream lengths match for short inputs. Admission warmup remains240 complete bars.

BUY every p[i]>K[i], SELL every p[i]<K[i], HOLD equality or unordered comparisons. No crossing trigger, threshold, epsilon or positive-state repair. KAMA is computed once from the retained history origin and carried continuously, not re-seeded at240, a trade, session or calendar boundary. The original signal uses no volume. No new incremental-volume or orthogonality claim.

## Declared cash adaptation to review before registration

Original educational OutcomeWithContext uses initial balance1, full-balance shares at the same close and cost-free marks. This supplies full-cash intent, not a native exchange bot or unit1 size. Proposed cash scope uses the existing frozen FI-style adapter: three10000USDT sleeves; signal-close fee-reserved quantity floored to8 decimals, fixed before next minute OPEN; all-or-reject fee-inclusive debit, no resizing, borrowing, shorts, pyramiding, partials or orders. Held BUYs counted ignored before original SELL exit; no same-boundary reentry. No stop, target, trailing or timeout. Funded BTC owns its cash/quantity/costs. Final inventory is CENSORED_MTM, final queued SELL stays pending and final flat BUY is unexecuted. Eight-hour-close drawdown is not an intrabar bound.

500 weekly randomized flags and seven-bar lag replace the entire BUY qualifier; they may enter while KAMA is invalid and SELL remains false, leaving a censored holding. Each control has its own funding, admissions and endogenous duration. Preserve all existing20/40/60/80 cost cases, identical no-protection gap labels,2000 moving4-calendar-week blocks including zero weeks, fixed descriptivealpha.025,64/4096 fail-closed caps, all diagnostics and acceptance gates. No global repeated-search correction is implied.

This proposed version has not been registered or market-tested. Current completed history through Keltner has minimum27 trading/28 signal-model attempts and18 rejected fresh adaptations. Any next freeze must follow verified parent publication on a new branch, exact committed-source independent review, tests and source-preservation checks before first market load. Any historical survivor only permits a separate frozen untouched future confirmation; viability requires its pass.
