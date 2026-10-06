"""Explicit manual lock refresh; network use is limited to public PyPI artifacts.

Requires packaging==25.0 in the caller's dedicated maintenance environment.
No resolver upgrades baseline pins: review VERSIONS/BUILD and the emitted diff.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile
from email.parser import BytesParser

from packaging.requirements import Requirement
from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import parse_wheel_filename

VERSIONS = {
    "websockets": "15.0.1", "numpy": "2.4.6", "pandas": "2.3.3",
    "scikit-learn": "1.9.1", "scipy": "1.17.1", "joblib": "1.6.0",
    "threadpoolctl": "3.7.0", "python-dateutil": "2.9.0.post0", "pytz": "2026.4",
    "tzdata": "2026.4", "six": "1.17.0", "cloudpickle": "3.1.2",
}
BUILD = {"pip": "25.3", "setuptools": "80.9.0", "wheel": "0.45.1", "build": "1.3.0",
         "packaging": "25.0", "pyproject-hooks": "1.2.0"}
TARGETS = [(10, "linux"), (11, "linux"), (12, "linux"), (12, "win32")]


def retrieve(url: str) -> bytes:
    if not (url.startswith("https://pypi.org/") or url.startswith("https://files.pythonhosted.org/")):
        raise ValueError("non-PyPI URL refused")
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    lockdir = root / "requirements/locks"
    manifest = {"schema_version": 1, "source": "https://pypi.org/pypi/{name}/{version}/json",
                "refresh_policy": "manual_review_exact_artifact_bytes", "targets": {}}
    metadata_cache = {}
    for minor, platform in TARGETS:
        target = f"py3{minor}-{'manylinux-x86_64' if platform == 'linux' else 'win-amd64'}"
        directory = args.artifact_dir / target
        directory.mkdir(parents=True, exist_ok=True)
        runtime = dict(VERSIONS)
        if minor == 10:
            runtime.update(numpy="2.2.6", **{"scikit-learn": "1.7.2", "scipy": "1.15.3"})
        else:
            runtime["narwhals"] = "2.26.0"
        tools = dict(BUILD)
        if minor == 10:
            tools["tomli"] = "2.2.1"
        if platform == "win32":
            tools["colorama"] = "0.4.6"
        platforms = ([f"manylinux_2_{n}_x86_64" for n in range(28, 4, -1)] +
                     ["manylinux2014_x86_64", "manylinux2010_x86_64", "manylinux1_x86_64"]
                     if platform == "linux" else ["win_amd64"])
        tags = list(cpython_tags(python_version=(3, minor), platforms=platforms))
        tags += list(compatible_tags(python_version=(3, minor), interpreter=f"cp3{minor}", platforms=platforms))
        rank = {tag: index for index, tag in reversed(list(enumerate(tags)))}
        work = []
        for kind, versions in [("research", runtime), ("build", tools)]:
            for name, version in sorted(versions.items(), key=lambda pair: pair[0].lower()):
                key = (name, version)
                if key not in metadata_cache:
                    metadata_cache[key] = json.loads(retrieve(f"https://pypi.org/pypi/{name}/{version}/json"))
                metadata = metadata_cache[key]
                wheels = []
                for artifact in metadata["urls"]:
                    if artifact["yanked"] or artifact["packagetype"] != "bdist_wheel":
                        continue
                    wheel_tags = parse_wheel_filename(artifact["filename"])[3]
                    matches = [rank[tag] for tag in wheel_tags if tag in rank]
                    if matches:
                        wheels.append((min(matches), artifact["filename"], artifact))
                if wheels:
                    artifact = sorted(wheels, key=lambda item: item[:2])[0][2]
                else:
                    raise RuntimeError(f"no approved target wheel: {name} {version} {target}; "
                                       "a source-only successor needs separately reviewed native build inputs and proof")
                work.append((kind, name, version, artifact))
        def download(item):
            kind, name, version, artifact = item
            destination = directory / artifact["filename"]
            raw = destination.read_bytes() if destination.exists() else retrieve(artifact["url"])
            digest = hashlib.sha256(raw).hexdigest()
            if digest != artifact["digests"]["sha256"] or len(raw) != artifact["size"]:
                raise RuntimeError(f"PyPI byte identity mismatch: {artifact['filename']}")
            destination.write_bytes(raw)
            row = {"kind": kind, "name": name.lower(), "version": version, "filename": artifact["filename"],
                   "url": artifact["url"], "sha256": digest, "size_bytes": len(raw),
                   "packagetype": artifact["packagetype"], "requires_python": artifact["requires_python"]}
            if destination.suffix == ".whl":
                with zipfile.ZipFile(destination) as wheel:
                    meta = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
                    message = BytesParser().parsebytes(wheel.read(meta[0]))
                    row["requires_dist"] = message.get_all("Requires-Dist", [])
            return row
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(download, work))
        environment = {"python_version": f"3.{minor}", "python_full_version": f"3.{minor}.10",
                       "sys_platform": platform, "os_name": "nt" if platform == "win32" else "posix",
                       "platform_machine": "AMD64" if platform == "win32" else "x86_64",
                       "platform_python_implementation": "CPython", "extra": ""}
        installed = {row["name"]: row["version"] for row in rows}
        for row in rows:
            for spec in row.get("requires_dist", []):
                requirement = Requirement(spec)
                if requirement.marker and not requirement.marker.evaluate(environment):
                    continue
                name = requirement.name.lower().replace("_", "-")
                if name not in installed or installed[name] not in requirement.specifier:
                    raise RuntimeError(f"incomplete target closure: {target} {row['name']} requires {spec}")
        marker = f'python_version == "3.{minor}" and sys_platform == "{platform}" and platform_machine == "{"x86_64" if platform == "linux" else "AMD64"}" and platform_python_implementation == "CPython"'
        filenames = {}
        for kind in ("research", "build"):
            filename = f"{target}-{kind}.txt"
            filenames[kind] = filename
            content = ["# Authentic PyPI artifact bytes; reviewed exact pins. See artifacts.json.",
                       f"# Target: CPython 3.{minor} / {platform} / {'x86_64' if platform == 'linux' else 'AMD64'}.",
                       "# Source builds require the matching build lock and --no-build-isolation."]
            content += [f"{row['name']}=={row['version']}; {marker} --hash=sha256:{row['sha256']}"
                        for row in rows if row["kind"] == kind]
            (lockdir / filename).write_text("\n".join(content) + "\n", encoding="utf-8")
        manifest["targets"][target] = {"python": f"3.{minor}", "sys_platform": platform,
            "machine": "x86_64" if platform == "linux" else "AMD64", "implementation": "CPython",
            "locks": filenames, "artifacts": rows}
        print(target, "verified public PyPI bytes", len(rows), flush=True)
    (lockdir / "artifacts.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
