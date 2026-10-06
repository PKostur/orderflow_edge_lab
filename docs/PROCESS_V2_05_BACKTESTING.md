# Process Integrity v2 — Backtesting and economic accounting

## Scope and non-activation boundary

This document describes **additive, opt-in** functionality in
`orderflow_edge_lab.economics_v2`. It does not alter a frozen configuration,
research artifact, open-watch start, historical return, candidate ID, legacy
accounting result, or legacy funding-coverage verdict. It does not collect
market data, run a service or schedule, use a secret, buy data, or transmit an
order.

All v2 output keeps the shared `non_authority_claims` object false. In
particular, a matching local source hash is **not** evidence of durable external
retention, provider completeness/authenticity, independent-engine calibration,
profitability, promotion, or live capability.

## Offline execution surface

The development CLI is executable without network activity:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /home/ubuntu/orderflow-implementation/venv/bin/python \
  -m orderflow_edge_lab.economics_v2 --help
```

| Subcommand | JSON request | Output |
|---|---|---|
| `validate-envelope` | An execution-envelope policy | Normalized latency/freshness/impact scenario |
| `evaluate-envelope` | `signals`, quote **receipt** events, envelope, canonical source set | Per-signal fill/exclusion records and disposition counts |
| `qualify-economics` | Bound price and funding datasets plus a caller-declared qualification-policy hash | Venue/contract/coverage qualification result |
| `settlement-coverage` | Held `OPEN_CLOSED` intervals and expected settlement observations | Cash-flow settlement list and coverage generated from the same observations |
| `availability` | Frozen universe, per-symbol/date/leg evidence, source set, caller policy | Append-only universe-availability sidecar |
| `calibrate` | Frozen fixture, pinned external engine spec, optionally externally produced ledger | Match/mismatch report, or explicit `NOT_CALIBRATED_ENGINE_UNAVAILABLE` |

The CLI reads JSON files and emits JSON to stdout or a caller-selected new
output path. It does not access a provider. Stage 10/integration must register
an installed `orderflow-economics-v2` console script (or a `cli/economics_v2.py`
delegator) and verify it through the main `orderflow` dispatcher. This stage
intentionally does not change `pyproject.toml`, the dispatcher, CI, or README.

## Finding implementation map

| Finding | v2 execution path | Fail-closed behavior | Legacy handling |
|---|---|---|---|
| **F1 — execution validation** | `validate_execution_inputs_v2`, `build_execution_policy_v2`, `run_validated_accounting_v2` | Rejects negative/nonfinite cost or slippage and nonpositive/nonfinite size before any wrapped `legacy_compatible`, `canonical_v2`, `canonical_v3`, or `audit` call | The legacy runners are untouched. Valid legacy numerical output is embedded unchanged under a separately named wrapper result. |
| **F2 — fill envelope** | `validate_execution_envelope_v2`, `evaluate_execution_envelope_v2` | Entry is after declared latency and before entry timeout; it and later exit must have fresh receipt/source timestamps. Stale/late quotes become `ENTRY_STALE`, `ENTRY_TIMEOUT`, `EXIT_STALE`, or `EXIT_TIMEOUT`. Depth impact requires an explicit supported depth field; it is never inferred. | The old same-row calculation is not changed. `zero_latency_displayed_bbo` can only be a zero-cost `diagnostic_only` scenario. |
| **F3 — funding provenance** | `build_price_dataset_v2`, `build_funding_dataset_v2`, `build_economics_qualification_v2` | Only exact leg/symbol, venue, contract ID, and complete price/funding coverage produce `venue_consistent_complete`. A missing funding rate is an explicit missing observation; observed `0.0` is complete. | Historical price/funding caveats and reports remain unchanged. |
| **F4 — settlement endpoint consistency** | `build_settlement_coverage_v2` | `OPEN_CLOSED` means `(start, end]`: the end settlement is both covered and applied to cash flow; a start settlement is not. Missing scheduled settlements and intervals with no declared expected settlement are incomplete. | `read_funding_coverage_v1_v2` labels the existing strict-inside v1 report as preserved, not reclassified. |
| **F5 — external calibration** | `build_economic_calibration_fixture_v2`, `compare_external_engine_calibration_v2`, `run_pinned_external_engine_calibration_v2` | Fixture binds bid/ask, fee, slippage, funding, resize/reversal/terminal ledger assumptions and tolerance. A pinned adapter must write an independent engine ledger; fee/funding/event-order differences are detected. Missing/failed runners produce `NOT_CALIBRATED_ENGINE_UNAVAILABLE`. | Existing frictionless calibration artifacts and caveats remain untouched. No two copies of this repository’s formula create a parity result. |
| **F6 — frozen-universe availability** | `build_universe_availability_v2`, `attach_universe_availability_v2` | Requires a unique per-symbol/date/leg record for every frozen member. `delisted`, `fetch_error`, `insufficient_warmup`, `missing_funding`, and `invalid_prices` are distinct. Sidecar reports frozen denominator, long/short breadth, subset flag, and caller-declared minimum-name status. | It neither changes the v1 universe nor reweights/recalculates v1 returns; the link is a newly named descriptive successor report. |

## Required caller-declared policies and activation blockers

The following must be supplied and frozen by a future caller **before** later
relevant evidence is viewed. This code does not invent a threshold or activate
a policy:

1. **Execution/fill policy**: policy hash and scenario ID, decision latency,
   entry/exit quote-age bounds, entry/exit delays, fee, adverse slippage, size,
   and supported-depth impact policy. A source must expose trustworthy receipt,
   quote-source, and (if selected) depth fields.
2. **Funding/price policy**: a bound price and realized-funding manifest with
   venue, contract ID, rate convention, settlement schedule, UTC interval,
   exact source set, and expected settlement coverage. A named zero sensitivity
   may be reported only outside the qualified complete-economics path.
3. **Universe policy**: a caller-declared frozen universe and any
   minimum-name condition. The v2 sidecar only reports a declared condition;
   it does not create a watch pass/fail rule.
4. **Calibration protocol**: a frozen fixture/source identity and an operator
   maintained, pinned **independent** event-driven engine distribution and
   offline adapter. The shared venv used for this implementation has no
   `NautilusTrader`, Freqtrade, Backtesting.py, Zipline, VectorBT, or `bt`
   distribution. Therefore no independent-engine calibration is asserted.
5. **External durable storage**: operator-approved durable retention,
   immutable-copy and retrieval/rehearsal evidence for the required horizon.
   Local byte identities only are implemented here; they do not satisfy this
   blocker.

## Independent-engine adapter contract

`run_pinned_external_engine_calibration_v2` expects an offline runner command.
It writes a frozen fixture JSON and appends:

```text
--fixture <fixture.json> --output <engine-output.json>
```

The adapter output must be:

```json
{
  "engine_identity": {
    "engine_name": "caller-pinned-engine",
    "engine_version": "caller-pinned-version",
    "distribution_sha256": "<64 lowercase hex>",
    "runner_protocol_version": "orderflow-external-ledger-v1"
  },
  "ledger": {
    "event_order": ["..."],
    "fills": [],
    "cash_flows": [],
    "trades": [],
    "turnover_units": 0.0,
    "terminal_equity": 1.0
  }
}
```

The runner receives `ORDERFLOW_CALIBRATION_OFFLINE=1`; it must be maintained in
a separately pinned third-party-engine environment. A ledger match is
engineering comparison evidence only and deliberately leaves
`independent_engine_calibration_verified: false` until the broader evidence
process verifies the external environment.

## Test evidence

`tests/test_v2_05_backtesting.py` proves adversarial invalid costs, latency and
stale/timeout quote exclusions, adverse-assumption monotonicity on a fixed
accepted set, venue mismatch and explicit missing funding rejection, exact-zero
funding preservation, endpoint settlement accounting, legacy v1 reader
preservation, calibration mismatch detection/unavailable engine status, and
universe attrition reconstruction. It also calls the module CLI through a real
`evaluate-envelope` JSON request.
