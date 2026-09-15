# Gold RV Persistence HistData Temporal v2

## Status

Protocol frozen before any 2024 price archive is materialized, parsed, or scored. Only the Git LFS pointer identity of the 2024 archive was inspected before this freeze.

Economic, directional, leverage, and live scoring remain disabled.

## Why this follow-on exists

HistData 2023 v1 reproduced the exact frozen `rv_persistence` state strongly but formally failed the preregistered replication gate solely because 140 New York dates were scorable versus the required 160. The 160-date floor is not weakened.

This v2 is a post-observation temporal follow-on motivated only by that source-coverage shortfall. It does not retune the candidate or any gate. It extends the exact candidate to the next historical year, 2024.

## Frozen candidate

Unchanged from development, locked 2023 Dukascopy validation, MGC replication, and HistData 2023 v1:

- feature: prior 60-minute realized volatility normalized by the trailing 20 valid same-clock observations;
- target: next 60-minute realized volatility normalized the same way;
- frozen sign: positive;
- secondary target: next 60-minute range normalized by its trailing 20 valid same-clock observations;
- weekday New York anchor hours: 00, 02, 04, 06, 08, 10, 12, 14, 16, 18, 20, 22 at minute 00;
- missing one-minute data: drop the affected anchor, no interpolation;
- minimum eight valid anchors for a daily inference unit.

No parameter may change after 2024 data are touched.

## Source

Repository pin remains `blackmoon87/forex-histdata-m1@208e67d7bda5cd5536df27531704e07fe4d54641`.

Frozen archives:

- 2023 warmup: `HISTDATA_COM_ASCII_XAUUSD_M12023.zip`, SHA256 `89a4f3f7ec2a52b29fbce8d4ca2ab650971817ae371b332f5fe471a488bcffc2`, 3,629,564 bytes.
- 2024 replication: `HISTDATA_COM_ASCII_XAUUSD_M12024.zip`, SHA256 `6d47f5cb269e0c4f35c63c7532713aae7dcf98901f605458b00dd6a69e7105de`, 4,358,732 bytes.

The workflow must verify byte size and SHA256 before parsing.

HistData timestamps remain fixed EST UTC-05:00 without DST, converted first to UTC and then to `America/New_York` for anchor matching.

## Evidence boundary

- Anchors before 2023-11-01 New York time are excluded from baseline construction.
- November and December 2023 are warmup only.
- Only New York dates from 2024 are scored.
- No 2025+ archive may be downloaded or parsed by this workflow.

This is later historical out-of-sample evidence relative to the 2021-2023 research path and remains source-independent relative to the original Dukascopy development/validation source. It is not prospective future OOS and not a future shadow.

## Frozen gate

Unchanged from the prior replication protocols:

- at least 160 scorable New York dates;
- median daily Spearman at least +0.15;
- at least 58% positive daily effects;
- at least 8 positive clock slots, each with at least 80 observations;
- first-half median effect positive;
- second-half median effect positive;
- secondary future-range median effect positive;
- one-sided 20,000-epoch sign-flip p-value no greater than 0.05;
- all conditions required.

## Decision policy

If all frozen gates pass, classify the exact state as having passed later-historical independent-source temporal replication. That still does not authorize a directional or economic edge claim. The next step would be prospective state shadowing or a separately preregistered monetization mechanism.

If any gate fails, close this temporal replication without changing thresholds and retain only the existing robustness evidence.
