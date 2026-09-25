from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path

from orderflow_edge_lab.cross_sectional_forward_shadow import load_candidate
from orderflow_edge_lab.funding_coverage import build_funding_coverage_report
from orderflow_edge_lab.okx_funding_archive import (
    OkxFundingArchiveError,
    fetch_and_parse_okx_funding_archive,
    merge_okx_funding_archive_records,
    records_to_funding_frames,
)
from orderflow_edge_lab.okx_funding_archive_schema import ArchiveLimits
from orderflow_edge_lab.okx_history import (
    fetch_okx_swap_klines,
    okx_swap_instrument,
)
from orderflow_edge_lab.okx_market_data_history import (
    OkxMarketDataHistoryError,
    build_okx_historical_funding_source_probe,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit frozen-candidate held-interval funding coverage using official OKX historical archives without computing PnL."
    )
    parser.add_argument(
        "--candidate",
        default="config/cross_sectional_candidate_v1.json",
    )
    parser.add_argument(
        "--config",
        default="config/cross_sectional_okx_archive_funding_coverage_v1.json",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-workers", type=int, default=6)
    args = parser.parse_args(argv)

    try:
        candidate, candidate_file_sha = load_candidate(args.candidate)
        config_path = Path(args.config)
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config.get("audit_id") != "cross-sectional-okx-archive-funding-coverage-v1":
            raise SystemExit("unexpected archive funding coverage config")

        source_config = json.loads(
            Path(config["source_manifest_config"]).read_text(encoding="utf-8")
        )
        manifest = build_okx_historical_funding_source_probe(source_config)
        expected_manifest_count = int(config["expected_manifest_file_count"])
        if manifest["unique_manifest_file_count"] != expected_manifest_count:
            raise SystemExit(
                f"manifest count changed: {manifest['unique_manifest_file_count']} != {expected_manifest_count}"
            )

        manifest_rows = {}
        for query in manifest["queries"]:
            for row in query["manifests"]:
                key = row["url"] or row["filename"]
                if key:
                    manifest_rows[key] = row
        if len(manifest_rows) != expected_manifest_count:
            raise SystemExit("manifest deduplication count mismatch")

        symbols = [str(value) for value in config["symbols"]]
        symbol_to_instrument = {
            symbol: okx_swap_instrument(symbol)
            for symbol in symbols
        }
        target_instruments = list(symbol_to_instrument.values())
        archive_window = config["archive_record_window"]
        limits_raw = config["archive_limits"]
        limits = ArchiveLimits(
            max_download_bytes=int(limits_raw["max_download_bytes"]),
            max_uncompressed_bytes=int(limits_raw["max_uncompressed_bytes"]),
            max_members=int(limits_raw["max_members"]),
            max_sample_rows=0,
        )

        archive_reports = []
        workers = max(1, min(int(args.max_workers), 8))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    fetch_and_parse_okx_funding_archive,
                    url=str(row["url"]),
                    expected_archive_filename=str(row["filename"]),
                    target_instruments=target_instruments,
                    start=str(archive_window["start"]),
                    end=str(archive_window["end_exclusive"]),
                    limits=limits,
                ): str(row["filename"])
                for row in manifest_rows.values()
            }
            for future in as_completed(futures):
                expected_filename = futures[future]
                result = future.result()
                if result["expected_archive_filename"] != expected_filename:
                    raise SystemExit("archive filename identity mismatch")
                archive_reports.append(result)

        merged_records = merge_okx_funding_archive_records(archive_reports)
        funding_frames = records_to_funding_frames(
            merged_records,
            symbol_to_instrument,
        )

        price_window = config["price_window"]
        rest_base = str(config["okx_rest_base"])
        price_frames = {}
        with ThreadPoolExecutor(max_workers=min(workers, len(symbols))) as pool:
            futures = {
                pool.submit(
                    fetch_okx_swap_klines,
                    symbol,
                    "1d",
                    str(price_window["start"]),
                    str(price_window["end_exclusive"]),
                    rest_base=rest_base,
                ): symbol
                for symbol in symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                price_frames[symbol] = future.result()

        coverage_config = {
            "audit_id": config["audit_id"],
            "source": config["source"],
            "symbols": symbols,
            "window": dict(price_window),
        }
        report = build_funding_coverage_report(
            candidate,
            price_frames,
            funding_frames,
            coverage_config,
        )
        report["analysis"] = "cross_sectional_okx_archive_funding_coverage_v1"
        report["candidate_file_sha256"] = candidate_file_sha
        report["source_manifest"] = {
            "probe_id": manifest["probe_id"],
            "unique_manifest_file_count": manifest[
                "unique_manifest_file_count"
            ],
            "unique_download_url_count": manifest[
                "unique_download_url_count"
            ],
        }
        report["archive_parser_contract"] = {
            "expected_csv_header": [
                "instrument_name",
                "funding_rate",
                "funding_time",
            ],
            "funding_time_unit": "unix_milliseconds_utc",
            "funding_rate_rule": "finite_float",
            "duplicate_rule": "same instrument/time must have identical rate",
            "archive_count": len(archive_reports),
            "archive_record_window": dict(archive_window),
        }
        report["archive_source_summary"] = {
            "archive_count": len(archive_reports),
            "total_download_bytes": sum(
                int(row["download_bytes"]) for row in archive_reports
            ),
            "total_data_rows": sum(
                int(row["total_data_rows"]) for row in archive_reports
            ),
            "target_record_count_before_merge": sum(
                int(row["target_record_count"]) for row in archive_reports
            ),
            "merged_target_record_count": len(merged_records),
            "archives": [
                {
                    "filename": row["expected_archive_filename"],
                    "sha256": row["archive_sha256"],
                    "download_bytes": row["download_bytes"],
                    "target_record_count": row["target_record_count"],
                }
                for row in sorted(
                    archive_reports,
                    key=lambda value: str(value["expected_archive_filename"]),
                )
            ],
        }
        report["claims"]["archive_parser_frozen_before_coverage_result"] = True
        report["claims"]["candidate_pnl_computed"] = False
        report["claims"]["candidate_retested"] = False
        report["claims"]["historical_result_repaired"] = False

        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "coverage_fraction": report["coverage_fraction"],
                    "required_held_intervals": report[
                        "required_held_intervals"
                    ],
                    "covered_held_intervals": report[
                        "covered_held_intervals"
                    ],
                    "funding_economics_admissible": report[
                        "funding_economics_admissible"
                    ],
                    "archive_count": len(archive_reports),
                    "merged_target_record_count": len(merged_records),
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
        OkxFundingArchiveError,
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
