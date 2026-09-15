from __future__ import annotations

import argparse
import json
from pathlib import Path


CONFIG = Path("config/time_to_eat_nick_stewart_v1.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["state", "economics"], default="state")
    args = parser.parse_args()

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))

    if args.stage == "state":
        if cfg.get("state_scoring_enabled") is not True:
            print("TIME_TO_EAT_V1_STATE_BLOCKED")
            return 2
        if cfg.get("historical_splits", {}).get("validation_opened") is not False:
            print("TIME_TO_EAT_V1_STATE_BLOCKED")
            print("Reason: validation-open flag is inconsistent with development-only state work.")
            return 2
        print("TIME_TO_EAT_V1_STATE_READY")
        return 0

    unresolved = {
        key: value
        for key, value in cfg["unresolved_economic_fields"].items()
        if value is None
    }
    if cfg.get("economic_scoring_enabled") is not True or unresolved:
        print("TIME_TO_EAT_V1_ECONOMICS_BLOCKED")
        print("Reason: source-faithful economic execution freeze is incomplete or not authorized by state evidence.")
        if unresolved:
            print("Unresolved economic fields:")
            for key in unresolved:
                print(f"  - {key}")
        return 2

    print("TIME_TO_EAT_V1_ECONOMICS_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
