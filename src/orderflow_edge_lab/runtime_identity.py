from __future__ import annotations

import hashlib
from importlib import metadata
import platform
from pathlib import Path
import sys
from typing import Any


def _source_tree_sha256(root: Path | None = None) -> str:
    """Hash the executable Python source tree deterministically.

    The relative path is part of the digest so moving bytes between module names is
    detectable. Only Python source is included because that is the executable package
    surface shipped by this project.
    """
    package_root = (root or Path(__file__).resolve().parent).resolve()
    digest = hashlib.sha256()
    files = sorted(
        (path for path in package_root.rglob("*.py") if path.is_file()),
        key=lambda path: path.relative_to(package_root).as_posix(),
    )
    if not files:
        raise RuntimeError("runtime package source tree is empty")
    for path in files:
        relative = path.relative_to(package_root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _package_version() -> str:
    try:
        return metadata.version("orderflow-edge-lab")
    except metadata.PackageNotFoundError:
        return "uninstalled"


def runtime_identity() -> dict[str, Any]:
    """Return a stable identity for the code/runtime executing a paper session."""
    return {
        "package_version": _package_version(),
        "package_source_sha256": _source_tree_sha256(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "executable_name": Path(sys.executable).name,
    }
