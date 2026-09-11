from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.research_freeze import audit_prospective_dataset, validate_research_freeze, verify_strategy_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that an audited DeepCharts/dxFeed dataset is prospective to a frozen strategy definition. "
            "A pass is a research-integrity check, not evidence of profitability."
        )
    )
    parser.add_argument("freeze", type=Path)
    parser.add_argument("export_audit", type=Path)
    parser.add_argument("--strategy-config", type=Path, help="Optionally verify that the current strategy file still matches the freeze")
    parser.add_argument("--require-ofi", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        freeze = json.loads(args.freeze.read_text(encoding="utf-8"))
        report = json.loads(args.export_audit.read_text(encoding="utf-8"))
        validate_research_freeze(freeze)
        result = audit_prospective_dataset(freeze, report, require_ofi=args.require_ofi)
        if args.strategy_config is not None:
            config_matches = verify_strategy_config(freeze, args.strategy_config)
            result["strategy_config_current_file_matches"] = config_matches
            if not config_matches:
                result["passed"] = False
                result["failures"] = [*result["failures"], "strategy_config_changed_since_freeze"]
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2

    payload = json.dumps(result, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
