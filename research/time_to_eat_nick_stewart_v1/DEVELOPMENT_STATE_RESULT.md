# Time To Eat / Nick Stewart v1 — Development State Result

## Evidence boundary

This is a development-only state test on the frozen 2021-2022 period. It is not PnL, not locked validation, and not future OOS.

Frozen state protocol was committed before this successful scoring run. Engineering-only ingestion fixes after the freeze changed source parsing only and did not alter any setup definition, threshold, state target, statistical gate, or research period.

Canonical scored head: `a04faee8d7f818faf0f7cda894f4cba83475583a`

Canonical workflow run: `34980898595`

Artifact: `time-to-eat-nick-stewart-v1-state` (`10401691316`)

Artifact digest: `sha256:df2434a2b94867b7e6d3e175197858dab467197491158baa8e5774161573641c`

Locked 2023 validation opened: **false**

Economic scoring run: **false**

## Data actually scored

Only development rows strictly before 2023-01-01 UTC were materialized for the scorer.

- XAUUSD cash development proxy: 708,099 one-minute rows, 2021-01-04 through 2022-12-30.
- NQ futures: 707,451 one-minute rows, 2021-01-03 through 2022-12-30.
- ES transfer source: 233,329 one-minute rows, 2021-01-21 through 2022-12-28, with explicit contract-transition UTC dates removed.

Development dataset SHA256 values:

- XAUUSD: `8da1f240f6b267e2db5082eedf48304540ace1c8a48a2af1c7f45de43399b647`
- NQ: `fa6ba4ed219eb40aa146235b01efc0d098cdcf19149288b451ec3ce5c70342d3`
- ES: `0da6a8d77822f89f2ff44cbd14d964091fea4bddeacfa725e46297cc0c7e2fc6`

Important XAU limitation: the public source does not document timezone provenance for its naive timestamps. State v1 parsed them as UTC and records that assumption explicitly. This weakens any Gold-specific inference and would require an independently timestamp-verified Gold/GC source before promotion even if the state gate had passed.

## Frozen family size

The study scored 72 predeclared cells across:

- symbols: XAUUSD, NQ, ES;
- execution timeframes: 15m, 30m, 1H;
- Breakout and Celery range lookbacks: 4, 6, 8 bars;
- Onion and Fade single frozen operationalizations;
- forward state horizons: 1, 2, and 4 execution bars;
- 2-bar primary FDR horizon;
- New York date as the dependence cluster;
- matched same-date/session/bias state benchmark;
- reversed-direction controls.

## Result

- cells scored: **72**
- raw frozen state passes: **0**
- promotable state candidates: **0**
- economics authorized: **no**
- locked validation authorized: **no**

No cell met the complete frozen state gate.

## Gold / XAUUSD primary 30m findings

### Breakout, 4-bar range

- events: **59**
- active days: **54**
- 2-bar median daily excess state return: **-0.3811 ATR**
- 2-bar mean daily excess: **-0.6070 ATR**
- positive-day fraction: **31.5%**
- primary sign-flip p-value: **1.000**
- FDR q-value: **1.000**

The reversed-direction control has the opposite sign. Under this frozen proxy, Gold breakouts behaved more like failures/reversions than source-direction continuation.

### Celery / Booby Trap, 4-bar range

- events: **36**
- active days: **34**
- 2-bar median daily excess: **-0.6883 ATR**
- 2-bar mean daily excess: **-1.0438 ATR**
- positive-day fraction: **20.6%**
- p-value: **1.000**
- q-value: **1.000**

This was strongly inconsistent with a continuation state under the frozen proxy.

### Onion

This was the strongest-looking Gold cell and is therefore the most important anti-cherry-picking case.

- events: **37**
- active days: **35**
- 1-bar median excess: **+0.0407 ATR**
- 2-bar median excess: **+0.3789 ATR**
- 2-bar mean excess: **+0.4821 ATR**
- positive-day fraction: **62.9%**
- raw 2-bar sign-flip p-value: **0.01855**
- positive horizons: **2 of 3**
- BH FDR q-value across the frozen family: **0.44518**

It therefore **failed** the q <= 0.10 multiple-testing gate.

It also failed the predeclared adjacent-timeframe robustness requirement:

- 15m Onion 2-bar median excess: **-0.1606 ATR**
- 1H Onion 2-bar median excess: **-0.0058 ATR**

No post-hoc Onion-only economic study is authorized from this result.

### Fade

The 30m Gold Fade proxy produced only **5 events** across **5 days** and its 2-bar median excess was **-0.2521 ATR**. It failed breadth and directionality requirements.

## NQ primary 30m findings

No NQ setup passed.

The largest adequately sampled cells were not compelling:

- Breakout range 4: 61 events / 59 days, 2-bar median excess **0.0000 ATR**, q **1.000**.
- Breakout range 6: 26 events / 26 days, median **0.0000 ATR**, q **1.000**.
- Celery range 4: 45 events / 45 days, median **0.0000 ATR**, q **1.000**.
- Onion: 43 events / 42 days, median **-0.1552 ATR**, q **1.000**.

Several visually positive NQ cells were too sparse to satisfy the frozen event/day gates and were not promoted.

## ES transfer findings

No ES cell passed. ES is transfer evidence only in any case.

The 30m 4-bar Breakout had 27 events across 26 days but a primary median excess of **0.0000 ATR**, positive-day fraction **46.2%**, and q **1.000**.

Some Celery/Fade cells had positive point estimates but were sparse and failed the frozen breadth and/or multiplicity gates. They are not candidates.

## Decision

**Reject Time To Eat / Nick Stewart v1 mechanical state proxies as promotable development candidates.**

This does not establish that Nick Stewart's discretionary Playbook is ineffective. The source leaves important visual concepts discretionary, and this study deliberately labels its deterministic definitions as research operationalizations rather than exact Nick Stewart rules.

What the result does establish is narrower and important: the frozen, source-informed mechanical v1 proxy did not demonstrate robust cross-timeframe state information sufficient to justify PnL optimization.

Therefore:

- do not enable economic scoring;
- do not calculate or optimize stops/targets/partials around the attractive 30m Gold Onion observation;
- do not open the 2023 locked validation period;
- do not treat NQ or ES same-period tests as future OOS;
- do not claim the approximately 75% Playbook win-rate assertion is verified or falsified by this state-only study;
- no leverage testing;
- no live-trading authorization.

Any future Time To Eat iteration must be explicitly post-observation. If additional first-party source material resolves the discretionary mechanics, it must be frozen as a new version before any new validation period is inspected. The 2021-2022 results are already observed development evidence and cannot become confirmatory evidence for that later version.

## Claims after v1

- robust development state edge: **no**
- executable edge: **not tested / not authorized**
- claimed ~75% win rate verified: **no**
- claimed ~75% win rate falsified: **no**
- locked validation opened: **false**
- verified future OOS: **false**
- leverage authorized: **false**
- live enabled: **false**
