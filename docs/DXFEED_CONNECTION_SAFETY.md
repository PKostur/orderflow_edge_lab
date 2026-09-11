# dxFeed connection safety policy

This project prefers the already-paid DeepCharts/dxFeed path, but it must not turn
platform access into an unsupported second data connection.

## Default operating rule

Use local DeepCharts exports and the existing bridge observation tooling first.
Do not open an independent authenticated dxFeed connection from this project while
DeepCharts is using the same retail credentials unless the entitlement explicitly
states that concurrent external API sessions are supported.

Current DeepCharts support material says a dxFeed account may be rejected when the
same account is used on multiple platforms at the same time. Separate DeepCharts
material also says DeepCharts and DeepDom can share one bridge. Those statements
are compatible only if bridge sharing is treated as a platform-supported special
case, not general permission for arbitrary concurrent clients.

Therefore:

1. A discovered DeepCharts remote peer is identification evidence only.
2. It is never treated as authorization for an independent client connection.
3. Credentials are never sent to a host inferred only from process/network capture.
4. External REST/native connection details must come from the entitlement/provider.
5. If external connection rights are absent or unclear, local export remains the
   zero-additional-cost ingestion path.
6. Live broker/exchange transmission remains outside the supported project path.

## Why this matters

A second client can create account lockouts, ambiguous data provenance, or an
unsupported use of the subscription. It can also make research less reproducible
if the platform and research process consume materially different feeds.

The endpoint watcher and endpoint analyzer are intentionally credential-free and
fail closed. Their purpose is to identify the service path and guide a safe next
step, not to bypass provider access controls.

## Research implication

Data imported from DeepCharts must retain exact local-byte hashes, source labels,
and timestamp/order diagnostics. Passing ingestion checks is evidence of structural
quality only. It does not establish completeness, exchange sequence fidelity,
external API rights, executable fills, or a profitable out-of-sample edge.
