from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.okx_market_data_history import (
    OkxMarketDataHistoryError,
    build_okx_historical_funding_source_probe,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe OKX historical funding archive metadata without computing strategy PnL."
    )
    parser.add_argument(
        "--config",
        default="config/cross_sectional_okx_historical_funding_source_probe_v1.json",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        result = build_okx_historical_funding_source_probe(config)
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
                    "source_available": result["source_available"],
                    "query_count": result["query_count"],
                    "unique_manifest_file_count": result[
                        "unique_manifest_file_count"
                    ],
                    "unique_download_url_count": result[
                        "unique_download_url_count"
                    ],
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
        OkxMarketDataHistoryError,
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
