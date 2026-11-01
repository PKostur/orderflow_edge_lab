"""Record sha256 digests of the stored 1m arrays and the stale-tail start dates in the cache manifest (no download).

Usage: PYTHONPATH=src .venv/Scripts/python scripts/leverage_bracket_update_manifest.py [--dir DIR]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from orderflow_edge_lab import leverage_bracket_data as bdata

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "leverage_bracket_cache"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=str(DEFAULT_DIR))
    args = parser.parse_args(argv)
    manifest = bdata.update_manifest_digests(Path(args.dir))
    print({s: d for s, d in manifest["stale_tail_start"].items() if d})
    print(f"digests recorded for {len(manifest['array_digests'])} symbols")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
