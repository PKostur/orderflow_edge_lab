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

Exports often store quotes and trades on separate rows. The export adapter now
carries forward the most recent eligible BBO for the same symbol so a later
trade can be classified against actual prior quote context. The cache is causal:
it never uses a quote timestamped after the trade, never carries crossed quotes,
and ignores prior quotes older than two seconds by default. The threshold can be
changed explicitly:

```bash
python scripts/dxfeed_entitlement_probe.py \
  --export path/to/file.csv \
  --symbol NQ \
  --max-quote-age-seconds 1.0
```

The JSON output separates adapter diagnostics from the data-quality report. In
particular, inspect `trades_enriched_from_prior_bbo`,
`trades_quote_classified`, `stale_prior_quotes_ignored`,
`future_prior_quotes_ignored`, and `trade_bbo_fraction` before using an export
for research.

Aggressor classification precedence is explicit side, then bid/ask matching,
then tick rule. Explicit feed-side labels are never overwritten by quote
inference. The quality report states how much classification was explicit,
classified, or unknown.

The entitlement probe intentionally uses relaxed side-coverage thresholds. It
only answers whether the file can be safely ingested. A passing probe is not a
claim that the dataset is sufficient for strategy research or out-of-sample
validation.

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

## Important entitlement caveat

Do not infer external API or redistribution permission merely from being able
to view dxFeed data inside DeepCharts. The external endpoint/token must be
provided by the entitlement itself. If it is not available, the local export
path remains the zero-additional-cost research route.
