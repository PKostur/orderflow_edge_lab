# Gold RV Persistence HistData Replication v1

## Status

COMPLETED: strong independent-source robustness, formal frozen-gate FAIL on breadth only.

Valid result-bearing workflow: `34994222100`

Repository head: `e90c3ff27372832ba7f8952201edabcce22edad6`

Artifact: `gold-rv-persistence-histdata-replication-v1` (`10407345019`)

Artifact digest: `sha256:2de3bffc59d7eeccaa8334de276d6b5f64c7fe6e6076bb4e3be4112647078630`

## Candidate

Exact frozen `rv_persistence` candidate from locked 2023 XAUUSD validation:

`pre_rv_ratio -> future_rv_ratio`, positive sign, 60-minute pre/future windows, trailing 20 valid same-clock observations, frozen weekday New York two-hour anchor grid.

No PnL, price-direction, leverage, or live scoring was run.

## Source and engineering audit

Independent source, same instrument: HistData XAUUSD M1 from pinned Git LFS archives at `blackmoon87/forex-histdata-m1@208e67d7bda5cd5536df27531704e07fe4d54641`.

Verified archives:

- 2022 warmup source: SHA256 `e752b9d83a14b934099de372c1419ab476278e7cd949c313c3af06207960b1d8`, 4,364,035 bytes.
- 2023 replication source: SHA256 `89a4f3f7ec2a52b29fbce8d4ca2ab650971817ae371b332f5fe471a488bcffc2`, 3,629,564 bytes.

Two pre-result engineering failures are part of the audit trail:

- Run `34993556143` stopped at the checksum guard before parsing because the initially transcribed LFS hashes were wrong. Exact hashes were corrected from the already pinned Git LFS pointer text.
- Run `34993995480` verified both archives but stopped before state computation because the ZIP contains a CSV data file plus a TXT companion. The parser was changed only to prefer the unique CSV member.

Neither correction changed any research parameter or promotion gate. The first valid result was run `34994222100`.

HistData timestamps were treated as fixed EST UTC-05:00 without DST, then converted to UTC and New York civil time before anchor matching.

## Data coverage

- Combined valid minute rows: 663,320.
- 2022 valid rows: 354,568.
- 2023 valid rows: 308,752.
- Raw anchor observations including warmup: 2,340.
- 2023 replication observations after causal baseline warmup: 1,909.
- Scorable New York dates with at least eight frozen anchors: 140.

## State result

Primary frozen state relationship reproduced strongly:

- median daily Spearman: `+0.3575757576`;
- positive daily fraction: `85.0%`;
- one-sided 20,000-epoch sign-flip p-value: `0.0000499975`;
- first-half median daily Spearman: `+0.2560606061` across 34 scorable dates;
- second-half median daily Spearman: `+0.3681818182` across 106 scorable dates;
- secondary future-range median daily Spearman: `+0.2121212121`;
- positive eligible clock slots: `10`.

Eligible clock-slot Spearman effects were positive at 00, 02, 04, 06, 08, 10, 12, 14, 16, and 22 New York time. The 20:00 slot had only 71 observations and therefore remained ineligible under the frozen 80-observation floor. The 18:00 slot did not produce an eligible scored row from this source.

## Frozen gate result

`replication_pass = false`.

Every frozen condition passed except the minimum number of scorable dates:

- minimum scorable dates: **FAIL**, 140 observed versus 160 required;
- median daily effect at least +0.15: PASS;
- positive daily fraction at least 58%: PASS;
- at least eight positive eligible anchor slots: PASS;
- first-half effect positive: PASS;
- second-half effect positive: PASS;
- secondary range effect positive: PASS;
- one-sided p-value no greater than 0.05: PASS.

The 160-date floor is not relaxed after seeing the result. HistData v1 is therefore not promoted as a formal independent-replication pass.

## Interpretation

The exact volatility-persistence state has now shown similar positive behavior in the locked 2023 Dukascopy XAUUSD validation, the Databento-backed CME MGC robustness test, and this independent HistData XAUUSD replication. HistData is stronger than the locked Dukascopy result on median daily effect and positive-day share, but that does not override the preregistered breadth failure.

This materially strengthens evidence that the intraday Gold volatility-persistence state is real and not specific to the original data feed. It still does not establish price direction, executable expectancy, profitability, genuine prospective future OOS, leverage suitability, or live readiness.

## Decision

FORMAL REPLICATION FAIL ON BREADTH. RETAIN AS STRONG INDEPENDENT-SOURCE ROBUSTNESS EVIDENCE.

No gate weakening, no combination of MGC and HistData samples to manufacture a pass, and no economic or live promotion. The next legitimate test must be frozen separately before observing a later period or another source.
