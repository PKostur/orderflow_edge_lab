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

Integer and decimal timestamp strings preserve nanoseconds; supply strings or
integers rather than already-rounded floating-point epochs. The adapter accepts
Trade, TimeAndSale, and Quote rows and rejects unsupported event kinds.
Separate quotes can supply a BBO only for the same symbol, strictly before the
trade and at most one second old by default. Invalid quote updates invalidate
older BBOs. Equal-timestamp quotes are not assumed to precede a trade. Same-row
BBO fields are treated as contemporaneous export data; their provenance must be
checked against the export format. Tick-rule inference never uses a later trade.

Research quality checks require trades and reject locked or incomplete quotes.
When freshness is enabled, a reference clock is required and future events fail.
Passing these checks is data-quality evidence only, not evidence of an edge.

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

The script requests only a Quote event. It requires an HTTPS endpoint without
embedded credentials, query parameters, or fragments and refuses redirects.
It reports HTTP status and a bounded byte count; response bodies and exception
messages are omitted to avoid exposing credentials echoed by a server.
HTTP success does not prove historical TimeAndSale access or research validity.
The export probe returns a nonzero exit code when its quality checks fail.
Its relaxed side-coverage thresholds test ingestion only, not research readiness.

## Important entitlement caveat

Do not infer external API or redistribution permission merely from being able
to view dxFeed data inside DeepCharts. The external endpoint/token must be
provided by the entitlement itself. If it is not available, the local export
path remains the zero-additional-cost research route.
