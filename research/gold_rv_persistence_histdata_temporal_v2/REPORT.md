# Gold RV Persistence HistData Temporal v2

## Status

COMPLETED: later-historical independent-source temporal replication PASS.

Protocol freeze commit: `7564d82f0af2c939499c209a2935b294b898b6db`.

Valid result-bearing workflow: `34994864760`

Canonical scored head: `58579468856d2c2c1d60d2c7c832147f2560e2dc`

Artifact: `gold-rv-persistence-histdata-temporal-v2` (`10407545740`)

Artifact digest: `sha256:b8ed14b974f72677a30b1ffbb6ec38e7d1f5ae2ff949bbe0aca3c534cb811d0a`

No 2024 price archive had been downloaded, parsed, or scored before the protocol was frozen. Only the Git LFS pointer identity was inspected to pin the archive.

## Candidate

Exact unchanged `rv_persistence` state:

`pre_rv_ratio -> future_rv_ratio`, positive sign, 60-minute pre/future windows, trailing 20 valid same-clock observations, frozen weekday New York two-hour anchor grid.

No directional, economic, leverage, or live scoring was run.

## Period and source

2023 November/December HistData XAUUSD M1 are warmup only. 2024 is the only scored year.

The 2024 archive was pinned before scoring to SHA256 `6d47f5cb269e0c4f35c63c7532713aae7dcf98901f605458b00dd6a69e7105de`, size 4,358,732 bytes, at source repository commit `208e67d7bda5cd5536df27531704e07fe4d54641`.

Verified 2024 source:

- member: `DAT_ASCII_XAUUSD_M1_2024.csv`;
- raw rows: 355,652;
- valid rows after frozen quality filters: 355,592;
- first UTC row: 2024-01-01T23:00:00Z;
- last UTC row: 2024-12-31T21:57:00Z.

## State result

The exact frozen volatility-persistence relationship reproduced strongly in the later year:

- replication observations: `2,591`;
- scorable New York dates: `256`;
- median daily Spearman: `+0.3871212121`;
- positive daily fraction: `84.375%`;
- one-sided 20,000-epoch sign-flip p-value: `0.0000499975`;
- first-half dates: `127`;
- first-half median daily Spearman: `+0.3909090909`;
- second-half dates: `129`;
- second-half median daily Spearman: `+0.3833333333`;
- secondary future-range median daily Spearman: `+0.2181818182`;
- positive eligible anchor slots: `11`.

Eligible anchor-slot effects were positive at every scored slot: 00, 02, 04, 06, 08, 10, 12, 14, 16, 20, and 22 New York time. The 18:00 slot again did not produce an eligible scored row from this source.

## Frozen gate result

`replication_pass = true`.

Every preregistered gate passed without modification:

- at least 160 scorable dates: PASS, 256 observed;
- median daily effect at least +0.15: PASS, +0.3871;
- at least 58% positive daily effects: PASS, 84.38%;
- at least eight positive eligible anchor slots: PASS, 11;
- first-half median positive: PASS;
- second-half median positive: PASS;
- secondary range effect positive: PASS;
- one-sided p-value no greater than 0.05: PASS.

## Evidence interpretation

This is the first formal independent-source temporal replication pass for the exact Gold intraday `rv_persistence` state. It is temporally later than the 2021-2022 development period and locked 2023 validation period, and the data source is independent from the original Dukascopy development/validation source.

It remains historical data viewed after the fact in September 2026, so it is not a prospective future shadow and must not be described as genuine prospective OOS.

Across the evidence chain, the primary median daily Spearman has remained positive and similar or stronger:

- 2021-2022 development: approximately `+0.2871`;
- locked 2023 Dukascopy validation: `+0.2818`;
- 2023 HistData source robustness: `+0.3576`, formal breadth fail only;
- 2024 HistData temporal replication: `+0.3871`, all gates pass;
- MGC/Databento robustness: approximately `+0.381`, formal breadth fail only.

This materially supports the existence of a persistent intraday Gold volatility state. It does not establish price direction or an executable trading edge.

## Decision

PROMOTE THE STATE PAST THE LATER-HISTORICAL REPLICATION GATE.

Do not promote a trading strategy, leverage, or live execution. The next work must be separately preregistered and may either:

1. prospectively shadow the state on future data; or
2. test a mechanically frozen monetization mechanism while keeping untouched directional/economic holdouts and realistic execution controls.

No live order transmission is authorized.
