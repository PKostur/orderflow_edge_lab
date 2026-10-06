"""Clean wheel AND sdist dependency proof for one supported native CI target.

Uses only public PyPI artifact retrieval (unless --artifact-dir is supplied).
All installation/build/probe subprocesses are offline. No market/vendor calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import urllib.request
import venv

ROOT = Path(__file__).resolve().parents[1]


def target_identity() -> dict[str, str]:
    return {"python": f"{sys.version_info.major}.{sys.version_info.minor}", "sys_platform": sys.platform,
            "machine": platform.machine(), "implementation": platform.python_implementation()}


def select_target(manifest: dict, identity: dict) -> tuple[str, dict]:
    matches = [(name, target) for name, target in manifest["targets"].items()
               if all(target[key] == value for key, value in identity.items())]
    if len(matches) != 1:
        raise ValueError(f"unsupported or ambiguous target (fail closed): {identity}")
    return matches[0]


def isolated_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(key, None)
    env.update(PYTHONDONTWRITEBYTECODE="1", PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1",
               PIP_NO_CACHE_DIR="1", SOURCE_DATE_EPOCH="1791276329",
               OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    return env


def artifact_identity(path: Path) -> dict:
    raw = path.read_bytes()
    return {"filename": path.name, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True, help="new dedicated evidence directory")
    parser.add_argument("--artifact-dir", type=Path, help="directory containing authentic target artifacts; no download")
    args = parser.parse_args()
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((ROOT / "requirements/locks/artifacts.json").read_text(encoding="utf-8"))
    name, target = select_target(manifest, target_identity())
    report = {"schema_version": 1, "target": name, "interpreter": sys.version,
              "target_identity": target_identity(), "status": "failed", "commands": [],
              "proofs": [], "dependency_artifacts": target["artifacts"],
              "scope": "clean_native_wheel_and_sdist_full_research_dependency_install",
              "no_provider_or_order_calls": True, "activation_eligible": False}
    env = isolated_env()
    logs = work / "logs"
    logs.mkdir()
    outside = work / "outside-checkout"
    outside.mkdir()
    def run(label: str, command: list[str], cwd: Path = outside) -> None:
        log = logs / f"{len(report['commands']) + 1:02d}-{label}.log"
        with log.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps({"command": command, "cwd": str(cwd)}) + "\n")
            stream.flush()
            result = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                    text=True, timeout=1200)
        report["commands"].append({"label": label, "command": command, "cwd": str(cwd),
                                   "exit_code": result.returncode, "log": str(log),
                                   "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()})
        if result.returncode:
            raise RuntimeError(f"{label} failed: see {log}")
    house = work / "wheelhouse"
    house.mkdir()
    locks = {kind: ROOT / "requirements/locks" / filename for kind, filename in target["locks"].items()}
    report["lock_identities"] = {kind: artifact_identity(path) for kind, path in locks.items()}
    def new_environment(label: str) -> Path:
        directory = work / label
        # No pip, setuptools, wheel or host site-packages copied in implicitly.
        venv.EnvBuilder(with_pip=False, system_site_packages=False).create(directory)
        python = directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run(label + "-locked-build-tools", [sys.executable, "-m", "pip", "--isolated", "--python", str(python),
            "install", "--no-index", "--find-links", str(house), "--no-cache-dir", "--require-hashes",
            "-r", str(locks["build"])])
        return python
    try:
        for row in target["artifacts"]:
            if args.artifact_dir:
                raw = (args.artifact_dir.resolve() / row["filename"]).read_bytes()
            else:
                if not row["url"].startswith("https://files.pythonhosted.org/"):
                    raise ValueError("non-PyPI artifact URL refused")
                with urllib.request.urlopen(row["url"], timeout=120) as response:
                    raw = response.read()
            if hashlib.sha256(raw).hexdigest() != row["sha256"] or len(raw) != row["size_bytes"]:
                raise ValueError(f"authentic artifact identity mismatch: {row['filename']}")
            (house / row["filename"]).write_bytes(raw)
        # Copy package source only, never research/data/holdouts. Match the offline
        # release gate source scope and reject source symlinks before copy.
        source = ROOT / "src/orderflow_edge_lab"
        if any(path.is_symlink() for path in source.rglob("*")):
            raise ValueError("package source symlink refused")
        stage = work / "source"
        stage.mkdir()
        shutil.copy2(ROOT / "pyproject.toml", stage / "pyproject.toml")
        shutil.copytree(source, stage / "src/orderflow_edge_lab", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        builder = new_environment("builder")
        dist = work / "dist"
        run("build-wheel-and-sdist", [str(builder), "-I", "-m", "build", "--no-isolation", "--wheel", "--sdist",
                                      "--outdir", str(dist), str(stage)])
        wheels = list(dist.glob("*.whl"))
        sources = list(dist.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sources) != 1:
            raise ValueError("build must produce exactly one wheel and one sdist")
        for kind, artifact in [("wheel", wheels[0]), ("sdist", sources[0])]:
            python = new_environment(kind)
            identity = artifact_identity(artifact)
            req = work / f"{kind}-artifact.txt"
            # The project's hash is calculated AFTER its actual build; full
            # dependency resolution remains enabled, including research extras.
            req.write_text(f"orderflow-edge-lab[research] @ {artifact.as_uri()} --hash=sha256:{identity['sha256']}\n",
                           encoding="utf-8")
            run(kind + "-full-hash-locked-install", [str(python), "-I", "-m", "pip", "--isolated", "install",
                "--no-index", "--find-links", str(house), "--no-cache-dir", "--require-hashes", "--no-build-isolation",
                "-r", str(locks["research"]), "-r", str(req)])
            run(kind + "-pip-check", [str(python), "-I", "-m", "pip", "check"])
            run(kind + "-installed-command-smoke", [str(python), "-I", str(ROOT / "scripts/package_smoke.py"), "--installed"])
            run(kind + "-installed-research-imports", [str(python), "-I", "-c",
                "import numpy,pandas,scipy,sklearn,joblib,websockets; print('installed research imports passed')"])
            report["proofs"].append({"kind": kind, "artifact": identity, "environment": str(python.parent.parent),
                                      "require_hashes": True, "dependency_resolution_enabled": True,
                                      "pip_check": "passed", "installed_command_smoke": "passed",
                                      "research_imports": "passed", "system_site_packages": False,
                                      "pythonpath_fallback": False})
        report["status"] = "passed"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        path = work / "packaging-proof.json"
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Packaging evidence: {path}", flush=True)


if __name__ == "__main__":
    main()
