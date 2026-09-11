# DeepCharts/dxFeed export lineage

Use the existing DeepCharts/dxFeed export path as the raw research source whenever it provides the required fields. The lineage profiler adds no paid infrastructure and does not modify the source file.

Create a manifest before transforming an export:

```bash
python scripts/profile_export.py deepcharts_export.csv --output deepcharts_export.manifest.json
```

If automatic column detection does not match the export schema, provide the exact names:

```bash
python scripts/profile_export.py deepcharts_export.csv \
  --timestamp-column eventTime \
  --symbol-column symbol \
  --output deepcharts_export.manifest.json
```

The manifest records the SHA-256 of the exact byte stream consumed by the CSV parser, byte size, schema fingerprint, row count, normalized row-chain hash, timestamp parse coverage, timestamp regressions, and a bounded symbol sample. ISO-8601 timestamps and numeric Unix timestamps in seconds, milliseconds, microseconds, or nanoseconds are supported.

Duplicate or blank headers and inconsistent row widths fail closed. Timestamp parse errors remain visible instead of being silently coerced. Timestamp regressions are diagnostics rather than automatic proof of bad data because a mixed-event export can legitimately contain different event clocks or ordering semantics.

The file hash can be used as `source_provenance.dataset_sha256` in the future-validation workflow. This strengthens local reproducibility by tying derived observations to exact local bytes. It does not prove that an export is complete, authentic to dxFeed, entitled for every event type, or representative of executable fills.

Keep the raw export immutable after manifest creation. If the bytes change, create a new manifest and treat the result as a new source dataset rather than overwriting the previous lineage record.
