"""Verify installed-wheel command metadata against the versioned command registry.

This is a read-only safe-probe test: every flat entry point is invoked with its
registry-declared help probe, except the explicit GUI metadata-only exception.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel")
    args = parser.parse_args()
    wheel = Path(args.wheel).resolve()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        packages = root / "packages"
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps", "--target", str(packages), str(wheel)], check=True)
        env = {**os.environ, "PYTHONPATH": str(packages)}
        check = r'''
import importlib.metadata
import json
from pathlib import Path
from orderflow_edge_lab.command_registry_v2 import flat_entry_points, gui_entry_points, load_command_registry

registry = load_command_registry()
dist = importlib.metadata.distribution("orderflow-edge-lab")
entries = {entry.name: entry.value for entry in dist.entry_points}
assert {name: entries.get(name) for name in flat_entry_points()} == flat_entry_points(), "flat wheel metadata drift"
assert {name: entries.get(name) for name in gui_entry_points()} == gui_entry_points(), "GUI wheel metadata drift"
assert sorted(registry["commands"], key=lambda item: item["name"]) == registry["commands"], "registry ordering drift"
print(json.dumps({"flat": len(flat_entry_points()), "gui": len(gui_entry_points())}, sort_keys=True))
'''
        subprocess.run([sys.executable, "-c", check], env=env, cwd=root, check=True, timeout=30)
        probes = r'''
import importlib.metadata
import sys
from orderflow_edge_lab.command_registry_v2 import load_command_registry
entries = {entry.name: entry for entry in importlib.metadata.distribution("orderflow-edge-lab").entry_points}
for item in load_command_registry()["commands"]:
    if item["exposure"] != "flat":
        continue
    entry = entries[item["name"]]
    if item["safe_probe"] == "metadata_only_gui_exception":
        continue
    assert item["safe_probe"] == "--help", item
    sys.argv = [item["name"], "--help"]
    try:
        entry.load()()
    except SystemExit as exc:
        assert exc.code in (0, None), (item["name"], exc.code)
'''
        subprocess.run([sys.executable, "-c", probes], env=env, cwd=root, check=True, timeout=120)
    print("Installed wheel command-registry smoke checks passed; no network data or orders requested.")


if __name__ == "__main__":
    main()
