from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.cross_market_futures_aggregate import aggregate_d0


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} is not a JSON object")
            rows.append(value)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate frozen cross-market futures v1 replay reports into D0 family gates."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("research_id") != "cross_market_futures_v1":
        raise SystemExit("manifest research_id must be cross_market_futures_v1")
    sessions = manifest.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise SystemExit("manifest sessions must be a non-empty list")

    base = manifest_path.parent
    records: list[dict[str, object]] = []
    feature_rows_by_capture: dict[str, list[dict[str, object]]] = {}

    for item in sessions:
        if not isinstance(item, dict):
            raise SystemExit("each manifest session must be an object")
        session_id = str(item.get("session_id", "")).strip()
        root = str(item.get("root", "")).strip().upper()
        native_contract = str(item.get("native_contract", "")).strip()
        report_value = item.get("report")
        feature_value = item.get("feature_rows")
        if not session_id or not root or not native_contract or not isinstance(report_value, str):
            raise SystemExit("each session requires session_id, root, native_contract, and report")
        report_path = (base / report_value).resolve()
        report = _read_json(report_path)
        if not isinstance(report, dict):
            raise SystemExit(f"report is not a JSON object: {report_path}")
        records.append(
            {
                "session_id": session_id,
                "root": root,
                "native_contract": native_contract,
                "report": report,
            }
        )
        if feature_value is not None:
            if not isinstance(feature_value, str):
                raise SystemExit("feature_rows must be a path string when provided")
            capture_key = f"{root}|{native_contract}|{session_id}"
            if capture_key in feature_rows_by_capture:
                raise SystemExit(f"duplicate feature-row capture key: {capture_key}")
            feature_rows_by_capture[capture_key] = _read_jsonl((base / feature_value).resolve())

    result = aggregate_d0(
        records,
        feature_rows_by_capture=feature_rows_by_capture if feature_rows_by_capture else None,
    )
    result["manifest_file"] = args.manifest.name
    result["placebo_feature_rows_supplied_for_all_records"] = (
        len(feature_rows_by_capture) == len(records)
    )
    if feature_rows_by_capture and len(feature_rows_by_capture) != len(records):
        result["placebo_warning"] = (
            "Feature rows were supplied for only a subset of captures; any placebo coverage "
            "shortfall remains fail-closed and cannot support candidate freeze."
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
