# Gold RV Persistence HistData Replication v1

## Status

PENDING EXECUTION.

The protocol and scorer are frozen before result-bearing execution. No HistData state statistic or PnL result has been observed at the time of this report commit.

## Candidate

Exact frozen `rv_persistence` candidate from locked 2023 XAUUSD validation:

`pre_rv_ratio -> future_rv_ratio`, positive sign, 60-minute pre/future windows, trailing 20 valid same-clock observations, frozen weekday New York two-hour anchor grid.

## Source

Independent source, same instrument: HistData XAUUSD M1 from pinned public Git LFS archives at `blackmoon87/forex-histdata-m1@208e67d7bda5cd5536df27531704e07fe4d54641`.

The workflow must verify the frozen LFS SHA256 and byte size of both the 2022 warmup archive and 2023 replication archive before parsing.

HistData timestamps are treated as fixed EST UTC-05:00 without DST, then converted to UTC and New York civil time.

## Evidence classification

This is same-period independent-source historical replication. It cannot establish future OOS, direction, profitability, leverage suitability, or live readiness.

## Decision rule

The unchanged frozen replication gate in `config/gold_rv_persistence_histdata_replication_v1.json` decides pass/fail. No post-result retuning or threshold relaxation is permitted.
