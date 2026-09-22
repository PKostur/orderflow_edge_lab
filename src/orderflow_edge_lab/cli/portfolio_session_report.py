from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.portfolio_session_report import (
    PortfolioSessionReportError,
    build_portfolio_session_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build observational 8h session-bucket economics from a portfolio shadow report.")
    parser.add_argument("report")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        source = json.loads(Path(args.report).read_text(encoding="utf-8"))
        result = build_portfolio_session_report(source)
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        print(out)
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, PortfolioSessionReportError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
