# Zero-additional-cost market-data path

The project should use data access the operator already pays for before adding a new vendor.

## Preferred order

1. DeepCharts/dxFeed local export or capture already available to the operator.
2. Existing DeepCharts/dxFeed endpoint access when the operator can supply the endpoint and token legitimately associated with the subscription.
3. MEXC public futures data for ENA/BTC venue-specific research.
4. A paid replacement only when a required field cannot be obtained reliably from the existing stack.

The repository must not attempt to extract credentials from DeepCharts, bypass vendor entitlement controls, or infer undocumented authentication tokens.

## Local export audit

Use the installed command on a CSV export before any research consumes it:

```bash
orderflow-export-audit path/to/export.csv --symbol NQ --output runtime/export-audit.json
```

For a quote-only export used exclusively for BBO research:

```bash
orderflow-export-audit path/to/export.csv --symbol NQ --allow-quote-only
```

To make a pipeline fail closed unless best-level OFI is structurally usable:

```bash
orderflow-export-audit path/to/export.csv --symbol NQ --require-ofi-eligible
```

The audit preserves source row order and reports:

- file SHA-256;
- event and symbol counts;
- trade-side classification coverage;
- causal prior-BBO enrichment statistics;
- duplicate and timestamp-order defects;
- BBO price/size coverage;
- locked or crossed quote rows;
- ambiguous equal-timestamp rows;
- best-level OFI sample counts.

The BBO parser recognizes common snake_case and camelCase field names including `bid`, `ask`, `bidPrice`, `askPrice`, `bidSize`, `askSize`, `eventTime`, `eventSymbol`, and `sequence`.

## Best-level OFI scope

The OFI implementation uses only causally ordered best-bid and best-ask price and size changes. It is useful when the export contains BBO sizes, but it is not a replacement for full market-by-order data.

It must not be described as executed volume. It measures displayed queue changes at the best prices. A quote size decrease can represent cancellation, execution, repricing, or a mixture of causes.

Equal-timestamp BBO updates are accepted only when the source provides a strictly increasing sequence for the symbol. Otherwise the later update is omitted as causally ambiguous.

## dxFeed direct connectivity

dxFeed currently documents dxLink as a WebSocket access layer that uses a customer-specific endpoint and token-based access control. The project already contains endpoint discovery and login safety tooling, but direct streaming should only be enabled after the operator can provide the legitimate endpoint/access material exposed by the existing subscription.

Official references:

- https://kb.dxfeed.com/en/market-data-api/dxlink.html
- https://kb.dxfeed.com/en/market-data-api/data-access-solutions/javascript-api.html
- https://dxfeed.com/dxfeed-apis/dxfeed-javascript-api/

Until that access is confirmed, local DeepCharts/dxFeed exports remain the preferred zero-additional-cost route.

## Paper runtime audit

Before an approval session, run:

```bash
orderflow-paper-audit --state runtime/paper-state.json --journal runtime/paper-journal.jsonl --output runtime/paper-audit.json
```

The audit is read-only. It verifies the existing deployment-readiness checks, records state and journal hashes, audits journal semantics, identifies expired pending proposals, reports the kill switch and open-position counts, and continues to declare live transmission unsupported.

A structurally valid export or operationally ready paper engine is not evidence of a profitable strategy. Promotion still requires frozen rules and genuinely future out-of-sample validation.
