# DeepCharts endpoint capture safety boundary

The project can observe remote TCP peers used by DeepCharts and Volumetrica without reading credentials, process memory, command lines, environment variables, or configuration files.

This is a connection-mapping aid only. A peer observed on the wire is not automatically an externally supported API endpoint.

## Capture

Run on the Windows machine while DeepCharts is connected:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\find_deepcharts_dxfeed.ps1
```

For better isolation, disconnect only the dxFeed feed during the watch window, wait a few seconds, then reconnect it. The script writes `deepcharts_dxfeed_endpoints.json`.

## Analyze

After installing the package:

```bash
orderflow-analyze-endpoint deepcharts_dxfeed_endpoints.json --output endpoint_analysis.json
```

The analysis validates the watcher schema, safety flags, capture time bounds, endpoint count, IP and port fields, DNS evidence consistency, and observation ordering. It also records the SHA-256 of the exact capture bytes so later decisions can be tied to the same file.

The analyzer ranks evidence conservatively:

* Reverse DNS containing `dxfeed` is strong network-peer evidence.
* Port 7300 is an indicator because it is associated with dxFeed native connectivity, but it is not proof of account-specific API access.
* Port 443 alone is generic TLS and is not promoted to an endpoint candidate.
* Tied high-signal candidates fail closed as ambiguous.

## Non-negotiable authorization gate

Even when a single likely dxFeed peer is identified, the analyzer always reports:

```json
{
  "external_api_authorized": false,
  "safe_for_independent_connection": false
}
```

Those fields cannot become true from network observation. Independent REST, WebSocket, or native API connectivity requires connection details and rights explicitly supplied by the existing entitlement. Do not send account credentials to a hostname merely because DeepCharts was observed talking to it.

If external API rights are unavailable, local DeepCharts or dxFeed exports remain the preferred zero-additional-cost research path.
