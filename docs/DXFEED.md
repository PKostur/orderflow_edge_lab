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

Integer and decimal timestamp strings preserve nanoseconds; supply strings or
integers rather than already-rounded floating-point epochs. The adapter accepts
Trade, TimeAndSale, and Quote rows and rejects unsupported event kinds.
Separate quotes can supply a BBO only for the same symbol, strictly before the
trade and within the configured age limit (one second for `normalize_rows`,
two seconds for the export probe). Invalid quote updates invalidate
older BBOs. Equal-timestamp quotes are not assumed to precede a trade. Same-row
BBO fields are treated as contemporaneous export data; their provenance must be
checked against the export format. Tick-rule inference never uses a later trade.

Research quality checks require trades and reject locked or incomplete quotes.
When freshness is enabled, a reference clock is required and future events fail.
Passing these checks is data-quality evidence only, not evidence of an edge.
The entitlement probe intentionally uses relaxed side-coverage thresholds. It
only answers whether the file can be safely ingested. A passing probe is not a
claim that the dataset is sufficient for strategy research or out-of-sample
validation.

## Path B: external dxFeed REST entitlement

### Interactive login window

After installation, run `orderflow-dxfeed-login` (or
`python scripts/dxfeed_login.py` from this checkout). Enter the username and
password locally, select Basic or bearer authentication, and click **Test
connection**. The password field is masked and cleared on submission. Credentials
are not written to disk, returned in diagnostics, or placed in command arguments.
The window sends one bounded HTTPS Quote request and refuses redirects.

The initial endpoint is the [documented REST example](https://kb.dxfeed.com/en/market-data-api/data-access-solutions/rest.html),
`https://tools.dxfeed.com/webservice/rest/events.json`, and the initial symbol is
dxFeed's [published NQ symbol](https://dxfeed.com/market-data/futures/cme/), `/NQ:XCME`.
These are exploratory defaults, not confirmed partner-account connection details.
In the September 2026 local test, this address returned HTTP 302 to
`demo.dxfeed.com`; credentials were not forwarded. The redirect does not establish
password validity or API rights. Obtain the actual partner endpoint before an
account-specific test. Do not send your credentials to a guessed alternate host.

A service response and a structurally valid quote are reported separately.
Neither certifies account entitlement, real-time freshness, or historical
TimeAndSale access. HTTP 200 service-error responses are failures, and diagnostic
output omits server-provided text. The optional `--result-file` stores only a
sanitized result and timestamp. Tk support is required for the window; it is
included in the standard Windows Python installer. Console probes remain usable
without Tk.

If the existing subscription provides an external REST endpoint and bearer
token, keep them only in local environment variables:

```text
DXFEED_REST_ENDPOINT
DXFEED_TOKEN
DXFEED_SYMBOL
```

If the supplied endpoint uses HTTP Basic authentication instead, set
`DXFEED_USERNAME` and `DXFEED_PASSWORD` locally and leave `DXFEED_TOKEN` unset.
Do not combine the authentication modes. A platform-issued username or email
domain does not establish whether external API access is included.
Use only the connection method and endpoint supplied for the existing entitlement.
dxFeed documents both [Basic REST authentication](https://kb.dxfeed.com/en/market-data-api/data-access-solutions/rest.html)
and [bearer headers](https://kb.dxfeed.com/en/data-services/real-time-and-delayed-services/token-based-authorization/establishing-connection.html).
Subscription-specific credentials and coverage are described in its
[getting-started guide](https://kb.dxfeed.com/en/getting-started.html).

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
