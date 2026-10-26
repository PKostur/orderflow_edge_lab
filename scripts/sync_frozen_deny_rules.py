"""Keep the Edit deny rules in .claude/settings.json in step with the repository's frozen files.

Frozen = every path in config/frozen_manifest_v1.json, every config/*.json whose status starts with FROZEN, and the
canonical v2 accounting module. Deny rules are a second line of defence: they do not stop Bash writes, which
tests/test_freeze_manifest.py (hash manifest) still catches.
Usage: .venv/Scripts/python scripts/sync_frozen_deny_rules.py [--check]
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_V2 = ["src/orderflow_edge_lab/universal_backtest.py"]


def frozen_paths(root: Path = ROOT) -> list[str]:
    paths = set(CANONICAL_V2)
    manifest = json.loads((root / "config" / "frozen_manifest_v1.json").read_text(encoding="utf-8"))
    paths |= {f["path"] for f in manifest["files"]}
    for p in (root / "config").glob("*.json"):
        try:
            status = json.loads(p.read_text(encoding="utf-8")).get("status", "")
        except (ValueError, AttributeError):
            continue
        if isinstance(status, str) and status.upper().startswith("FROZEN"):
            paths.add(p.relative_to(root).as_posix())
    return sorted(paths)


def main(argv: list[str]) -> int:
    sp = ROOT / ".claude" / "settings.json"
    s = json.loads(sp.read_text(encoding="utf-8"))
    deny = s.setdefault("permissions", {}).setdefault("deny", [])
    want = [f"Edit(/{p})" for p in frozen_paths()]
    missing = [r for r in want if r not in deny]
    if "--check" in argv:
        print(json.dumps({"missing": missing}))
        return 1 if missing else 0
    s["permissions"]["deny"] = deny + missing
    sp.write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
    print(f"{len(want)} frozen paths denied for Edit ({len(missing)} added)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
