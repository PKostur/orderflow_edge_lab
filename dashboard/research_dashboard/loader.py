from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

MAX_JSON_BYTES = 5_000_000
MAX_JSONL_LINES = 500
DEFAULT_SCAN_DIRS = ("research", "config")

_METRIC_TOKENS = (
    "bps",
    "expectancy",
    "profit_factor",
    "sharpe",
    "signals",
    "trades",
    "pnl",
    "drawdown",
    "win_rate",
    "hit_rate",
    "accuracy",
)

_EXPLICIT_FLAG_SUFFIXES = {
    "persistent_edge": (
        "persistent_edge_established",
        "profitable_edge_established",
        "edge_established",
    ),
    "candidate": (
        "candidate_created",
        "candidate_promoted",
        "candidate_promotion_supported",
    ),
    "live": (
        "live_execution_supported",
        "live_order_transmission_supported",
        "live_supported",
    ),
    "leverage": (
        "leverage_supported",
        "leverage_eligible",
    ),
}


@dataclass(frozen=True)
class ResearchArtifact:
    path: str
    kind: str
    project_id: str
    status: str
    stage: str
    persistent_edge: bool | None
    candidate: bool | None
    live_supported: bool | None
    leverage_supported: bool | None
    is_shadow: bool
    is_candidate_artifact: bool
    metrics: dict[str, float | int]
    raw: Any
    parse_error: str | None = None


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            child_key = f"{prefix}.{key}" if prefix else str(key)
            out.update(_flatten(child, child_key))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            child_key = f"{prefix}[{idx}]"
            out.update(_flatten(child, child_key))
    else:
        out[prefix] = value
    return out


def _first_scalar(data: dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in data and not isinstance(data[name], (dict, list)):
            return data[name]
    flat = _flatten(data)
    for name in names:
        for key, value in flat.items():
            if key.split(".")[-1] == name and not isinstance(value, (dict, list)):
                return value
    return None


def _explicit_bool(flat: dict[str, Any], suffixes: Iterable[str]) -> bool | None:
    matches: list[bool] = []
    for key, value in flat.items():
        leaf = key.split(".")[-1]
        if leaf not in suffixes or not isinstance(value, bool):
            continue
        matches.append(value)
    if not matches:
        return None
    return any(matches)


def _extract_metrics(flat: dict[str, Any]) -> dict[str, float | int]:
    metrics: dict[str, float | int] = {}
    for key, value in flat.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        leaf = key.lower()
        if any(token in leaf for token in _METRIC_TOKENS):
            metrics[key] = value
    return metrics


def _infer_project_id(data: dict[str, Any], path: Path) -> str:
    value = _first_scalar(
        data,
        (
            "research_id",
            "candidate_id",
            "strategy_id",
            "protocol_name",
            "experiment_id",
            "shadow_id",
        ),
    )
    if value is not None:
        return str(value)
    return path.parent.name if path.parent.name else path.stem


def _infer_status(data: dict[str, Any], path: Path) -> str:
    top = data.get("status")
    if isinstance(top, (str, int, float)):
        return str(top)

    state = data.get("research_state")
    if isinstance(state, dict):
        preferred = ("D4", "D3_holdout", "D3", "D2", "D0", "status")
        for key in preferred:
            if key in state and not isinstance(state[key], (dict, list)):
                return f"{key}={state[key]}"

    name = path.name.lower()
    if "freeze" in name:
        return "FROZEN_SPEC"
    if "candidate" in name:
        return "CANDIDATE_SPEC"
    if "shadow" in name:
        return "SHADOW_ARTIFACT"
    return "UNSPECIFIED"


def _infer_stage(status: str, path: Path) -> str:
    text = f"{status} {path.as_posix()}".upper()
    if "SHADOW" in text or "FORWARD" in text:
        return "SHADOW"
    if "D4" in text:
        return "D4"
    if "D3" in text or "HOLDOUT" in text:
        return "D3/HOLDOUT"
    if "D2" in text or "REPLICATION" in text:
        return "D2/REPLICATION"
    if "D0" in text or "DISCOVERY" in text:
        return "D0/DISCOVERY"
    if "CANDIDATE" in text:
        return "CANDIDATE"
    if "FREEZE" in text or "FROZEN" in text:
        return "FROZEN"
    return "RESEARCH"


def _parse_markdown(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    title = path.stem
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break

    status_match = re.search(
        r"(?im)^\s*(?:status|research state)\s*[:=-]\s*([^\n]+)",
        text,
    )
    status = status_match.group(1).strip() if status_match else "MARKDOWN_RECORD"
    return {
        "research_id": title,
        "status": status,
        "_markdown": text,
    }


def _parse_jsonl(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    parsed: list[Any] = []
    for line in lines[-MAX_JSONL_LINES:]:
        if not line.strip():
            continue
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {
        "research_id": path.stem,
        "status": "JSONL_RECORD",
        "record_count_loaded": len(parsed),
        "records": parsed,
    }


def _load_path(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        if path.stat().st_size > MAX_JSON_BYTES and path.suffix.lower() != ".jsonl":
            return {}, f"file exceeds {MAX_JSON_BYTES} byte dashboard parse limit"
        if path.suffix.lower() == ".json":
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw, None
            return {"research_id": path.stem, "status": "JSON_RECORD", "value": raw}, None
        if path.suffix.lower() == ".jsonl":
            return _parse_jsonl(path), None
        if path.suffix.lower() == ".md":
            return _parse_markdown(path), None
        return {}, "unsupported file type"
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, f"{type(exc).__name__}: {exc}"


def artifact_from_path(path: Path, repo_root: Path) -> ResearchArtifact:
    data, error = _load_path(path)
    rel = path.relative_to(repo_root)
    flat = _flatten(data)
    status = "PARSE_ERROR" if error else _infer_status(data, rel)
    lower_path = rel.as_posix().lower()
    is_shadow = "shadow" in lower_path or "forward" in lower_path or "shadow" in status.lower()
    is_candidate_artifact = "candidate" in lower_path or "candidate" in status.lower()

    return ResearchArtifact(
        path=rel.as_posix(),
        kind=path.suffix.lower().lstrip("."),
        project_id=_infer_project_id(data, rel) if not error else rel.stem,
        status=status,
        stage=_infer_stage(status, rel),
        persistent_edge=_explicit_bool(flat, _EXPLICIT_FLAG_SUFFIXES["persistent_edge"]),
        candidate=_explicit_bool(flat, _EXPLICIT_FLAG_SUFFIXES["candidate"]),
        live_supported=_explicit_bool(flat, _EXPLICIT_FLAG_SUFFIXES["live"]),
        leverage_supported=_explicit_bool(flat, _EXPLICIT_FLAG_SUFFIXES["leverage"]),
        is_shadow=is_shadow,
        is_candidate_artifact=is_candidate_artifact,
        metrics=_extract_metrics(flat),
        raw=data,
        parse_error=error,
    )


def discover_artifacts(
    repo_root: str | Path,
    scan_dirs: Iterable[str] = DEFAULT_SCAN_DIRS,
) -> list[ResearchArtifact]:
    """Discover read-only evidence/config artifacts.

    No synthetic rows are generated. An empty repository returns an empty list.
    Parse failures are surfaced as explicit PARSE_ERROR artifacts.
    """

    root = Path(repo_root).resolve()
    files: set[Path] = set()
    for dirname in scan_dirs:
        base = root / dirname
        if not base.exists():
            continue
        for pattern in ("*.json", "*.jsonl", "*.md"):
            files.update(base.rglob(pattern))

    return [
        artifact_from_path(path, root)
        for path in sorted(files, key=lambda p: p.as_posix().lower())
        if path.is_file()
    ]
