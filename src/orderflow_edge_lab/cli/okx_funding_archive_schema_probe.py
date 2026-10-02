from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.okx_funding_archive_schema import (
    OkxFundingArchiveSchemaError,
    build_okx_funding_archive_schema_probe,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect fixed OKX funding archive samples without computing strategy PnL."
    )
    parser.add_argument(
        "--config",
        default="config/cross_sectional_okx_funding_archive_schema_probe_v1.json",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        result = build_okx_funding_archive_schema_probe(config)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "probe_id": result["probe_id"],
                    "sample_count": result["sample_count"],
                    "distinct_csv_headers": result["distinct_csv_headers"],
                    "evidence_use": result["evidence_use"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
        OkxFundingArchiveSchemaError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
