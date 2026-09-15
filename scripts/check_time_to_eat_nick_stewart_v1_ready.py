from __future__ import annotations

import json
from pathlib import Path


CONFIG = Path("config/time_to_eat_nick_stewart_v1.json")


def main() -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    unresolved = {
        key: value
        for key, value in cfg["unresolved_required_fields"].items()
        if value is None
    }

    if cfg.get("scoring_enabled") is not True or unresolved:
        print("TIME_TO_EAT_V1_SCORING_BLOCKED")
        print("Reason: deterministic rule freeze is incomplete.")
        if unresolved:
            print("Unresolved required fields:")
            for key in unresolved:
                print(f"  - {key}")
        return 2

    print("TIME_TO_EAT_V1_SCORING_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
