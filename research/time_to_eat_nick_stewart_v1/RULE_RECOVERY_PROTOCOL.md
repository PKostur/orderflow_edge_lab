# Time To Eat / Nick Stewart v1 Rule-Recovery Protocol

## Research boundary

This lane is structurally separate from the gold/silver relative-value lineage. It starts from the completed `research/gold-silver-trend-exhaustion-v6` evidence state, but it does not reuse or retune any gold/silver candidate.

The objective is to test the Time To Eat / Nick Stewart Playbook as a mechanical intraday strategy without inventing missing rules.

The order is fixed:

1. recover source rules;
2. freeze a deterministic mechanical specification;
3. test state behavior before PnL;
4. score development economics with realistic costs and controls;
5. freeze any candidate before locked validation;
6. independent replication;
7. future shadow only after all earlier gates pass;
8. leverage/live only after positive unlevered expectancy and all promotion gates.

Locked data must remain unopened until a candidate is frozen. Same-period cross-symbol tests are transfer evidence, not genuine future OOS.

## Source hierarchy

Use sources in this order:

1. preserved prior-chat material if it can be recovered verbatim;
2. Nick Stewart / Time To Eat first-party videos, streams, course pages, or written material;
3. transcripts of those first-party videos;
4. third-party summaries only to locate first-party statements or as explicitly labeled external sanity checks.

Never fill an unresolved rule from intuition, chart familiarity, or a profitable backtest outcome.

## Recovered source facts as of 2026-09-15

Primary current source: Time To Eat Trading, `The Play Book 2.0`, published 2026-08-29, YouTube video id `shc8w71iK_o`, with a publicly indexed transcript.

Recovered claims and mechanics:

- Higher-timeframe context is based on the Daily and 4-hour candles.
- The Playbook is intended to align lower-timeframe entries with an anticipated higher-timeframe move, except the Fade, which may oppose the current higher-timeframe direction after a target is reached.
- Preferred execution timeframe is 30 minutes. The 15-minute and 1-hour timeframes are also explicitly used.
- Nick states a preference for the New York session and repeatedly emphasizes high-volume periods such as session opens and news events.
- Gold is the primary market in the Playbook examples. In an August 2026 interview Nick described Gold as roughly 90 to 95 percent of his trades, with selective NQ trades.
- Nick states that three core entry types in his own tracking produced 75 percent-plus win rates, and later describes the Playbook as approximately a 75 percent win-rate system. This is a claim to test, not accepted evidence.

### Breakout

Source-faithful description:

- begin with Daily / 4-hour directional bias;
- lower timeframe is ranging after a prior move;
- mark the range and do not trade while price remains inside it;
- require a candle close outside the range in the bias direction;
- the next candle is the trading candle;
- entry is associated with breaking the relevant candle high for longs, or low for shorts;
- nearest resistance/support and the higher-timeframe wick-fill area are described as targets;
- partial profit may be taken at the nearby level and a runner may continue;
- high-volume conditions are preferred.

### Onion

Source-faithful description:

- used in a trending market aligned with the higher-timeframe bias;
- do not chase an already extended move;
- wait for a pullback;
- for a bullish case, wait for support to form after the pullback, with the inverse for shorts;
- that support/resistance candle is the confirmation candle;
- the next candle is the trading candle;
- entry uses a break of a relevant candle high/low;
- nearest resistance/support and higher-timeframe wick fill are target concepts;
- partials may be taken at the nearby target.

### Celery / Booby Trap

Source-faithful description:

- begins around a prospective breakout from a range;
- require a breakout candle close outside the range;
- if the following candle is stalling or pulling back, wait for that candle to close;
- if it closes back inside the range, the breakout is not valid for the original-direction entry;
- if it closes outside the range, that candle is the confirmation candle regardless of whether its body is bullish or bearish;
- place the directional stop entry at the break of that confirmation candle high/low;
- high-volume conditions are preferred.

### Fade

Source-faithful description:

- a higher-timeframe target or major support/resistance has already been reached;
- the prior directional move may therefore be exhausted;
- lower-timeframe target completion and slowing candles are contextual clues;
- the Fade is typically considered during high-volume periods such as New York / NYSE open;
- unlike the other plays, the Fade does not require a normal confirmation candle;
- for a bearish fade after an upward move, if price fails to break the relevant high and then breaks the relevant low, a sell entry may be taken, with the inverse for bullish fades;
- Nick describes Fade entries as more aggressive / impulse entries and notes they often oppose the prevailing higher-timeframe direction.

### Entry and stop logic

The source describes two favored entry styles:

- break of the current candle high/low;
- break of the previous candle high/low.

If the previous-candle and current-candle trigger levels are very close, Nick prefers the previous-candle level for greater confirmation. If they are farther apart, he may use the current-candle level to avoid giving up too much of the move.

For a current-candle-high long entry, he describes the previous candle low as a possible stop. For a previous-candle-high long entry, he describes the current candle low as a possible stop. He also notes that a wider stop beyond all relevant wicks may be preferable when the tighter stop lacks breathing room. The inverse applies to shorts.

The source also describes moving to break-even, or sometimes taking partials, after a wick-fill move of roughly 10 to 20 pips in the example. This is not yet a deterministic exit rule.

## Unresolved mechanical fields

The following remain unresolved and therefore may not be silently parameterized:

- exact algorithm for Daily and 4-hour bullish/bearish bias;
- exact definition of a trend;
- exact definition and minimum age/width of a clean range;
- exact support/resistance construction;
- exact meaning of strong support/resistance;
- exact rule for deciding that a higher-timeframe target has been tapped;
- exact wick-fill target construction;
- exact volume metric and threshold, or whether session time itself is the intended volume proxy;
- exact handling of scheduled news releases;
- exact rule selecting current-candle versus previous-candle trigger when the levels are close or far;
- exact stop choice when multiple source-permitted stop locations exist;
- exact partial size;
- exact runner exit;
- exact break-even trigger;
- order expiry and re-entry rules;
- maximum trades per session/day/setup;
- whether multiple setup labels may describe the same event and how precedence is resolved;
- contract-roll handling and whether the source intends GC futures only or a cash-gold proxy for historical research.

These fields must be recovered from source material or frozen as separately labeled research operationalizations before any PnL scoring. An operationalization is not allowed to be described as an exact Nick Stewart rule unless a source supports it.

## Market scope

Primary claimed market: Gold futures / GC.

Secondary claimed market: NQ, because current public material shows Nick trading Gold and NQ and describes NQ entries as selective.

Predeclared transport market after the native-market development specification is frozen: ES. ES is a transfer/generalization test, not evidence that Time To Eat itself claims ES as a core market.

No market may receive symbol-specific rule tuning.

## Claim tests

The explicit win-rate claim to audit is 75 percent, with 75 percent-plus as the stronger historical phrasing. The research must report the observed win rate with uncertainty, trade count, dependence-aware resampling, payoff distribution, profit factor, net expectancy, drawdown, and cost sensitivity. Win rate alone cannot promote a strategy.

A third-party backtest of an inferred Playbook implementation is external context only. It is not accepted as reproduction evidence because its rule mapping, instruments, and execution model are not our frozen specification.

## State-before-PnL requirement

Each final deterministic setup must receive a state target before economics are examined.

Examples of permissible state questions, to be finalized only after rule mechanics are deterministic:

- Breakout / Celery: does the confirmed range break produce directional follow-through rather than immediate range re-entry?
- Onion: after the defined pullback and support/resistance confirmation, does price resume the higher-timeframe direction?
- Fade: after a defined higher-timeframe target is reached and trigger fails, does price reverse rather than continue?

State scoring must be based on forward price behavior, not trade PnL, and the state gate must be frozen before economic scoring.

## Economic controls

Once deterministic rules are frozen, every scored setup must include:

- source-direction strategy;
- direction-reversed control;
- equal-timing/session-matched directional benchmark;
- simple baseline appropriate to the setup family, such as an unconditioned range break for breakout-like plays;
- realistic commission, spread, tick, stop-order slippage, and adverse fill assumptions;
- higher-cost stress case;
- causal bar construction and no same-bar lookahead.

Engineering success is not trading-edge evidence.

## Current gate

`scoring_enabled = false`

Reason: the current public sources recover substantial playbook structure but still leave subjective chart concepts unresolved. No PnL run is authorized until the deterministic rule freeze is committed before results are inspected.
