# Gold RV Persistence HistData Temporal v2

## Status

PENDING RESULT-BEARING EXECUTION.

Protocol freeze commit: `7564d82f0af2c939499c209a2935b294b898b6db`.

No 2024 price archive had been downloaded, parsed, or scored before the protocol was frozen. Only the Git LFS pointer identity was inspected to pin the archive.

## Candidate

Exact unchanged `rv_persistence` state:

`pre_rv_ratio -> future_rv_ratio`, positive sign, 60-minute pre/future windows, trailing 20 valid same-clock observations, frozen weekday New York two-hour anchor grid.

## Period and source

2023 November/December HistData XAUUSD M1 are warmup only. 2024 is the only scored year. The 2024 archive is pinned before scoring to SHA256 `6d47f5cb269e0c4f35c63c7532713aae7dcf98901f605458b00dd6a69e7105de`, size 4,358,732 bytes, at source repository commit `208e67d7bda5cd5536df27531704e07fe4d54641`.

## Gate

The replication gate is unchanged from MGC and HistData 2023 v1, including the 160-scorable-date floor that caused v1 to fail formally.

No directional or economic scoring is enabled.
