from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.descriptive_regime_labels_v1 import run_from_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Run descriptive-only 8h regime label diagnostics v1.")
    parser.add_argument("--source-protocol", required=True)
    parser.add_argument("--regime-config", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = run_from_paths(
        source_protocol_path=args.source_protocol,
        regime_config_path=args.regime_config,
        data_dir=args.data_dir,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
