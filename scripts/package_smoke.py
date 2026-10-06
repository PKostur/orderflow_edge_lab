"""Offline fresh-wheel smoke of metadata and actual installed console scripts.

No index, data collection, GUI launch, orders, watches or provider calls. Shared
interpreter dependencies are intentional; installed project imports are isolated
from the checkout. Every safe --help probe must produce help output, not a no-op.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def installed_smoke() -> None:
    """Probe an already fully installed clean venv, outside any checkout."""
    assert sys.prefix != sys.base_prefix, "installed mode requires a dedicated venv"
    config = (Path(sys.prefix) / "pyvenv.cfg").read_text(encoding="utf-8").lower()
    assert "include-system-site-packages = false" in config, "shared site-packages refused"
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.update(PYTHONDONTWRITEBYTECODE="1", PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    check = r'''
import importlib.metadata
import json
from pathlib import Path
import sys
import orderflow_edge_lab
from orderflow_edge_lab.command_registry_v2 import flat_entry_points, gui_entry_points, load_command_registry
registry = load_command_registry()
dist = importlib.metadata.distribution("orderflow-edge-lab")
entries = {entry.name: entry.value for entry in dist.entry_points}
assert entries == {**flat_entry_points(), **gui_entry_points()}, "installed entry-point metadata drift"
assert sorted(registry["commands"], key=lambda item: item["name"]) == registry["commands"], "registry ordering drift"
assert Path(orderflow_edge_lab.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), "checkout/host import leak"
assert Path(dist.locate_file("")).resolve().is_relative_to(Path(sys.prefix).resolve()), "host distribution leak"
print(json.dumps(registry, sort_keys=True))
'''
    with tempfile.TemporaryDirectory(prefix="orderflow-installed-smoke-") as temp:
        root = Path(temp)
        result = subprocess.run([sys.executable, "-I", "-c", check], env=env, cwd=root, check=True,
                                capture_output=True, text=True, timeout=30)
        registry = json.loads(result.stdout)
        scripts = Path(sys.executable).parent
        probes = []
        for item in registry["commands"]:
            if item["exposure"] != "flat" or item["safe_probe"] == "metadata_only_gui_exception":
                continue
            assert item["safe_probe"] == "--help", item
            script = scripts / (item["name"] + (".exe" if os.name == "nt" else ""))
            assert script.is_file(), f"missing installed console script: {item['name']}"
            probe = subprocess.run([str(script), "--help"], env=env, cwd=root, capture_output=True, text=True, timeout=30)
            text = probe.stdout + probe.stderr
            assert probe.returncode == 0 and "usage:" in text.lower(), (item["name"], probe.returncode, text[-2000:])
            probes.append(item["name"])
        modules = [item["module"] for item in registry["commands"]
                   if item["module"].endswith("_v2") and item["module"].startswith("orderflow_edge_lab.cli.")]
        for module in modules:
            probe = subprocess.run([sys.executable, "-I", "-m", module, "--help"], env=env, cwd=root,
                                   capture_output=True, text=True, timeout=30)
            assert probe.returncode == 0 and "usage:" in (probe.stdout + probe.stderr).lower(), (module, probe.returncode)
        print(json.dumps({"console_scripts_probed": len(probes), "module_help_probes": len(modules),
                          "checkout_import_isolated": True, "dependency_runtime": "clean_venv",
                          "system_site_packages": False, "pythonpath_fallback": False,
                          "no_provider_or_order_calls": True}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", nargs="?")
    parser.add_argument("--installed", action="store_true", help="probe this clean, fully installed venv; do not install")
    args = parser.parse_args()
    if args.installed:
        if args.wheel:
            parser.error("--installed does not accept a wheel")
        installed_smoke()
        return
    if not args.wheel:
        parser.error("wheel or --installed is required")
    wheel = Path(args.wheel).resolve()
    with tempfile.TemporaryDirectory(prefix="orderflow-smoke-") as temp:
        root = Path(temp)
        packages = root / "packages"
        env = {**os.environ, "PYTHONPATH": str(packages), "PYTHONDONTWRITEBYTECODE": "1",
               "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps", "--target", str(packages), str(wheel)],
                       check=True, cwd=root, env=env, capture_output=True, text=True, timeout=90)
        check = r'''
import importlib.metadata
import json
from pathlib import Path
import orderflow_edge_lab
from orderflow_edge_lab.command_registry_v2 import flat_entry_points, gui_entry_points, load_command_registry
registry = load_command_registry()
dist = importlib.metadata.distribution("orderflow-edge-lab")
entries = {entry.name: entry.value for entry in dist.entry_points}
assert {name: entries.get(name) for name in flat_entry_points()} == flat_entry_points(), "flat wheel metadata drift"
assert {name: entries.get(name) for name in gui_entry_points()} == gui_entry_points(), "GUI wheel metadata drift"
assert sorted(registry["commands"], key=lambda item: item["name"]) == registry["commands"], "registry ordering drift"
assert Path(orderflow_edge_lab.__file__).resolve().is_relative_to(Path("packages").resolve()), "source checkout import leak"
print(json.dumps(registry, sort_keys=True))
'''
        result = subprocess.run([sys.executable, "-c", check], env=env, cwd=root, check=True,
                                capture_output=True, text=True, timeout=30)
        registry = json.loads(result.stdout)
        probes = []
        for item in registry["commands"]:
            if item["exposure"] != "flat" or item["safe_probe"] == "metadata_only_gui_exception":
                continue
            assert item["safe_probe"] == "--help", item
            script = packages / "bin" / item["name"]
            assert script.is_file(), f"missing installed console script: {item['name']}"
            probe = subprocess.run([str(script), "--help"], env=env, cwd=root, capture_output=True, text=True, timeout=30)
            text = probe.stdout + probe.stderr
            assert probe.returncode == 0 and "usage:" in text.lower(), (item["name"], probe.returncode, text[-2000:])
            probes.append(item["name"])
        modules = [item["module"] for item in registry["commands"]
                   if item["module"].endswith("_v2") and item["module"].startswith("orderflow_edge_lab.cli.")]
        for module in modules:
            probe = subprocess.run([sys.executable, "-m", module, "--help"], env=env, cwd=root,
                                   capture_output=True, text=True, timeout=30)
            assert probe.returncode == 0 and "usage:" in (probe.stdout+probe.stderr).lower(), (module, probe.returncode)
        print(json.dumps({"console_scripts_probed": len(probes), "module_help_probes": len(modules),
                          "checkout_import_isolated": True, "dependency_runtime": "shared_interpreter",
                          "no_provider_or_order_calls": True}, sort_keys=True))
    print("Installed wheel command-registry smoke checks passed; no network data or orders requested.")


if __name__ == "__main__":
    main()
