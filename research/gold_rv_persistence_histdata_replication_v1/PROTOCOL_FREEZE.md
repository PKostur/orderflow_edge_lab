# Gold RV Persistence HistData Replication v1

## Status

Protocol frozen before any HistData state statistic is scored. Economic and directional PnL scoring are disabled.

Two engineering corrections occurred before the first valid state result. Neither changed the candidate, gate, statistic, window, anchor grid, baseline length, test direction, or promotion threshold.

1. Workflow run `34993556143` stopped at the checksum guard before parsing because the initially transcribed Git LFS OIDs were incorrect. The exact pointer text at the already frozen source commit was re-read and the archive hashes below were corrected.
2. Workflow run `34993995480` passed source verification but stopped before state computation because each HistData archive contains both a CSV data member and a TXT companion. The fail-closed archive selector was changed only to prefer a unique CSV member, with a single TXT member permitted only as fallback when no CSV exists.

The first valid result-bearing execution is workflow run `34994222100` at repository head `e90c3ff27372832ba7f8952201edabcce22edad6`.

## Frozen candidate

This is the exact `rv_persistence` state candidate that passed the locked 2023 Dukascopy XAUUSD validation at commit `549d8f5928b26bd6ea2de55779047875fb463448`.

- Feature: prior 60-minute realized volatility normalized by the trailing 20 valid observations at the same New York clock slot.
- Target: next 60-minute realized volatility normalized by the trailing 20 valid observations at the same New York clock slot.
- Frozen sign: positive.
- Secondary diagnostic: next 60-minute range normalized by the same-clock trailing 20-observation median.
- Frozen anchors: weekday New York hours 00, 02, 04, 06, 08, 10, 12, 14, 16, 18, 20, 22 at minute 00.
- Missing one-minute data: drop the affected anchor. No interpolation.

No candidate definition, anchor, baseline length, window length, statistic, or promotion threshold may be changed after observing the HistData result.

## Independent source

Repository pin: `blackmoon87/forex-histdata-m1@208e67d7bda5cd5536df27531704e07fe4d54641`.

Frozen archives, corrected directly from the Git LFS pointer text before scoring:

- 2022: `HISTDATA_COM_ASCII_XAUUSD_M12022.zip`, LFS SHA256 `e752b9d83a14b934099de372c1419ab476278e7cd949c313c3af06207960b1d8`, 4,364,035 bytes.
- 2023: `HISTDATA_COM_ASCII_XAUUSD_M12023.zip`, LFS SHA256 `89a4f3f7ec2a52b29fbce8d4ca2ab650971817ae371b332f5fe471a488bcffc2`, 3,629,564 bytes.

The workflow must verify both byte size and SHA256 before parsing.

## Timestamp rule

HistData Generic ASCII minute timestamps are interpreted as fixed EST, UTC-05:00, without daylight-saving adjustment. Raw timestamps are first localized to fixed UTC-05:00, converted to UTC, and only then converted to `America/New_York` for matching the frozen anchor grid.

Directly localizing raw timestamps as `America/New_York` is prohibited because it would introduce a one-hour daylight-saving error during EDT months.

## Evidence boundary

The annual 2022 archive is materialized only because the public source is packaged annually. The scorer discards anchor candidates before 2022-11-01 New York time. November and December 2022 are baseline warmup only. Inference is restricted to New York dates in calendar year 2023. No 2024+ archive is materialized.

This test is independent-source, same-instrument, same-period historical replication. It is not genuine future OOS.

## Frozen replication gate

The gate is copied unchanged from the already frozen MGC independent-replication protocol:

- at least 160 scorable New York dates;
- median daily Spearman at least +0.15;
- at least 58% positive daily effects;
- at least 8 positive clock slots, each with at least 80 observations;
- first-half median effect positive;
- second-half median effect positive;
- secondary range median effect positive;
- one-sided 20,000-epoch sign-flip p-value no greater than 0.05;
- all conditions required.

## Claims prohibited

A pass may establish independent-source robustness of the Gold intraday volatility-persistence state only. It does not establish price direction, executable expectancy, profitability, future OOS, leverage suitability, or live readiness. A failure may not be repaired by threshold relaxation or post-result retuning.
