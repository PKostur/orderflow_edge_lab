"""Verify the built wheel's installed commands outside the source checkout."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel")
    args = parser.parse_args()
    wheel = Path(args.wheel).resolve()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        packages = root / "packages"
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps", "--target", str(packages), str(wheel)], check=True)
        env = {**os.environ, "PYTHONPATH": str(packages)}
        code = """import importlib.metadata, pathlib, sys
import orderflow_edge_lab
assert orderflow_edge_lab.__version__ == '1.0.0'
assert pathlib.Path(orderflow_edge_lab.__file__).is_relative_to(pathlib.Path(sys.path[1]))
entries = {e.name: e for e in importlib.metadata.distribution('orderflow-edge-lab').entry_points}
assert {'orderflow-paper', 'orderflow-probe', 'orderflow-validate', 'orderflow-readiness', 'orderflow-discover-endpoint', 'orderflow-analyze-endpoint', 'orderflow-dxfeed-login'} <= entries.keys()
assert callable(entries['orderflow-dxfeed-login'].load())
name = sys.argv.pop(1)
sys.argv[0] = name
raise SystemExit(entries[name].load()())
"""
        for command in (["orderflow-paper", "init"], ["orderflow-paper", "status"],
                        ["orderflow-paper", "kill"], ["orderflow-paper", "release"],
                        ["orderflow-paper", "expire"], ["orderflow-probe", "--help"],
                        ["orderflow-validate", "--help"], ["orderflow-readiness", "--help"],
                        ["orderflow-discover-endpoint", "--help"],
                        ["orderflow-analyze-endpoint", "--help"]):
            subprocess.run([sys.executable, "-c", code, *command], env=env, cwd=root, check=True, timeout=30)
    print("Installed wheel smoke checks passed; no network data or orders requested.")


if __name__ == "__main__":
    main()
