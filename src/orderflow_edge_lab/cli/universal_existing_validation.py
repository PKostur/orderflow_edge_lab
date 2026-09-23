from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.universal_existing_validation import (
    UniversalExistingValidationError,
    build_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the universal engine against frozen existing strategies.")
    parser.add_argument("--config", default="config/universal_existing_strategy_backtests_v1.json")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        report = build_report(args.config, args.data_dir)
    except (UniversalExistingValidationError, OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(output)}, sort_keys=True))
    return 0 if report["compatibility_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
