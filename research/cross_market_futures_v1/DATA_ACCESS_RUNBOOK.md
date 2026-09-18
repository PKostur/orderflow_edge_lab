# dxFeed / DeepCharts data-access runbook — cross-market futures v1

This runbook is for **read-only research data access**. It never places orders and it does not require credentials to be shared in chat or committed to Git.

## What the frozen protocol actually requires

- CMF-H1: trade events with causal aggressor classification **and executable BBO state**.
- CMF-H2: true displayed top-10 futures depth; Level-1 BBO is not a substitute.
- CMF-H3: Level-1 bid/ask **prices and sizes** for microprice, plus executable BBO.
- Historical replay requires actual event history. A current snapshot does not certify historical access.
- Cross-market futures v1 uses a **1.0-second** maximum prior-quote age.

Historical `TimeAndSale` alone can establish that historical trade events are available, but it does **not** by itself satisfy the frozen full replay because Quote/Order event history is still required.

## Local environment variables

Set these only on the local machine that already has legitimate dxFeed access.

PowerShell example:

```powershell
$env:DXFEED_REST_ENDPOINT = "https://YOUR-PROVIDER-ENDPOINT/webservice/rest/events.json"
$env:DXFEED_SYMBOL = "/NQ:XCME"

# Use one supported authentication mode only.
$env:DXFEED_TOKEN = "..."
# OR:
# $env:DXFEED_USERNAME = "..."
# $env:DXFEED_PASSWORD = "..."
```

Do not paste credentials into chat or commit them.

The public/documentation endpoint may not represent DeepCharts account entitlements. Use the endpoint legitimately supplied for external API access by the provider.

## 1. Current Level-1 Quote capability

```powershell
python scripts/dxfeed_entitlement_probe.py
```

Important output fields:

- `quote_received`
- `quote_sizes_received`
- `research_eligibility.CMF_H3_live_capture_component`
- `research_eligibility.historical_quote_stream_verified`

A current Quote with sizes is useful for future live capture engineering. It is **not** historical H3 evidence.

## 2. Historical TimeAndSale capability

The history probe is intentionally bounded to at most 10 minutes and never prints raw events.

```powershell
python scripts/dxfeed_entitlement_probe.py \
  --from-time 2026-09-18T13:30:00Z \
  --to-time   2026-09-18T13:31:00Z
```

Important fields:

- `historical_access_verified`
- `event_count`
- `events_with_size`
- `events_with_bid_ask`
- `events_with_aggressor_side`
- `events_with_sequence`
- `research_eligibility.CMF_H1_aggressor_component`

This verifies only the requested symbol/window. It does not certify historical Quote or Order streams.

## 3. Current futures top-10 depth capability

The probe requests the dxFeed futures `AGGREGATE` Order source and returns only coverage counts.

```powershell
python scripts/dxfeed_entitlement_probe.py --depth
```

Important fields:

- `current_depth_snapshot_verified`
- `bid_price_levels`
- `ask_price_levels`
- `top10_each_side_verified`
- `research_eligibility.CMF_H2_current_depth_component`
- `research_eligibility.CMF_H2_historical_replay`

This is a **current snapshot entitlement check**, not historical depth.

## 4. Export path when external REST is unavailable

A legitimate dxFeed/DeepCharts export remains supported.

```powershell
python scripts/dxfeed_entitlement_probe.py --export .\\sample.csv
```

For cross-market futures v1 the default causal prior-BBO age is 1.0 second.

Endpoint discovery can be run separately:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\\find_deepcharts_dxfeed.ps1
```

That script only inspects established network endpoints for likely DeepCharts/dxFeed processes. It does not read credentials, process memory, command lines, environment variables, or private configuration.

## 5. Run a native-contract replay

Example:

```powershell
python scripts/cross_market_futures_replay.py \
  --root NQ \
  --input .\\data\\NQZ26_session01.csv \
  --output-dir .\\artifacts\\NQZ26_session01
```

A single replay cannot pass D0. It creates:

- `feature_rows.jsonl`
- `report.json`

The input must contain one native contract only and pass the frozen data-integrity rules.

## 6. Aggregate multiple markets/sessions

Create a manifest such as:

```json
{
  "research_id": "cross_market_futures_v1",
  "sessions": [
    {
      "session_id": "2026-09-18-A",
      "root": "NQ",
      "native_contract": "NQZ26",
      "report": "artifacts/NQZ26_session01/report.json",
      "feature_rows": "artifacts/NQZ26_session01/feature_rows.jsonl"
    }
  ]
}
```

Then run:

```powershell
python scripts/cross_market_futures_aggregate.py \
  --manifest .\\manifest.json \
  --output .\\artifacts\\cross_market_futures_d0.json
```

The aggregator:

- rejects duplicate source hashes;
- validates root/native-contract/session bindings;
- does **not** select a winning horizon;
- requires complete 1s/5s/15s/30s outcomes and averages them into one signal-level composite;
- applies the frozen one-extra-round-trip-tick D0 gate;
- runs the deterministic -300s/-60s/+60s/+300s time-shift placebo when feature rows are supplied;
- runs the deterministic 10,000-resample session-cluster bootstrap diagnostic;
- never certifies persistent edge, live eligibility, or leverage.

## Research boundary

No futures order-flow edge has been established. The separate futures **bar-price transfer** experiment was falsified and does not change this lane. This order-flow lane remains blocked until eligible event data are supplied.
