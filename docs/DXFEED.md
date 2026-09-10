# dxFeed / DeepCharts data path

The preferred path is to reuse already-paid-for market-data access without
assuming that a retail platform login automatically includes external API
rights.

## Path A: local export

If DeepCharts or another dxFeed-powered tool can export trades and BBO/quote
data, validate that file with:

```bash
python scripts/dxfeed_entitlement_probe.py --export path/to/file.csv --symbol NQ
```

The adapter accepts common timestamp, symbol, trade price/size, bid/ask, and
aggressor-side column aliases. It preserves input order for timestamp auditing.

Aggressor classification precedence is explicit side, then bid/ask matching,
then tick rule. The quality report states how much classification was explicit,
classified, or unknown.

## Path B: external dxFeed REST entitlement

If the existing subscription provides an external REST endpoint and bearer
token, keep them only in local environment variables:

```text
DXFEED_REST_ENDPOINT
DXFEED_TOKEN
DXFEED_SYMBOL
```

Then run:

```bash
python scripts/dxfeed_entitlement_probe.py
```

The script requests only a Quote event and prints a bounded response preview.
It never places an order and never prints the token.

## Important entitlement caveat

Do not infer external API or redistribution permission merely from being able
to view dxFeed data inside DeepCharts. The external endpoint/token must be
provided by the entitlement itself. If it is not available, the local export
path remains the zero-additional-cost research route.
