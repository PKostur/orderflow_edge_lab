"""Read-only integrity report over the forward-artifact archive (archive/forward-artifacts-v1).

The forward watches replay their whole history on every run, so a run that silently lacks a coin rewrites days that
were already reported (evidence audit 2026-10-16, C1/C2).  This module makes that visible without touching any frozen
watch: per watch it lists every revised stamp, every run whose coin coverage fell below the most seen for that report,
and the time of day the watch stamps its days.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

REVISION_TOL = 1e-9
REPORT_ARTIFACT_BY_FILE = {"near_miss_forward_report.json": "near-miss-forward-v1",
                           "fade24_forward_report.json": "fade24-forward-v1",
                           "tradfi_perps_forward_report.json": "tradfi-perps-forward-v1"}


def dashboard_watches(dashboard_snapshot: Path) -> list[tuple[str, str, str, str]]:
    """(display name, artifact name, report file, primary book) from scripts/dashboard_snapshot.py, without importing it."""
    tree = ast.parse(dashboard_snapshot.read_text(encoding="utf-8"))
    rows: list = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "WATCHES" for t in node.targets):
            rows = ast.literal_eval(node.value)
            break
    out = []
    for wf, report, name, _group, book, _h in rows:
        art = REPORT_ARTIFACT_BY_FILE.get(report) or wf.removesuffix(".yml")
        if book:
            out.append((name, art, report, book))
    return out


def _manifest(root: Path) -> list[dict[str, Any]]:
    path = root / "manifest.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
    return sorted(rows, key=lambda r: (r["created_at"], int(r["artifact_id"])))


def _load(root: Path, row: dict[str, Any], report: str) -> dict[str, Any] | None:
    f = root / row["path"] / report
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        return None


def build_integrity_report(root: Path, watches: Sequence[tuple[str, str, str, str]]) -> dict[str, Any]:
    rows = _manifest(root)
    out: dict[str, Any] = {}
    for name, art, report, book in watches:
        seen: dict[str, list[tuple[str, int, float]]] = {}
        coverage: list[tuple[dict[str, Any], int | None, list]] = []
        times: set[str] = set()
        n = 0
        for row in (r for r in rows if r["name"] == art):
            rep = _load(root, row, report)
            if rep is None:
                continue
            series = (rep.get("daily_returns") or {}).get(book) or {}
            if series:
                n += 1
            for stamp, v in series.items():
                seen.setdefault(stamp, []).append((row["created_at"], int(row["artifact_id"]), float(v)))
                times.add(stamp[11:16])
            coverage.append((row, rep.get("coins_with_data"), list(rep.get("missing_symbols") or [])))
        revisions = []
        for stamp, obs in sorted(seen.items()):
            vals = [v for _, _, v in obs]
            if max(vals) - min(vals) > REVISION_TOL:
                revisions.append({"stamp": stamp, "observations": len(obs), "range_bps": (max(vals) - min(vals)) * 1e4,
                                  "first": obs[0][2], "latest": obs[-1][2],
                                  "latest_equals_first": abs(obs[-1][2] - obs[0][2]) <= REVISION_TOL})
        expected = max((c for _, c, _ in coverage if isinstance(c, int)), default=None)
        drops = [{"artifact": int(row["artifact_id"]), "created_at": row["created_at"], "coins_with_data": c,
                  "expected": expected, "missing_symbols": miss}
                 for row, c, miss in coverage
                 if (isinstance(c, int) and expected is not None and c < expected) or miss]
        out[name] = {"artifact": art, "report": report, "book": book, "artifacts_with_series": n, "stamps": len(seen),
                     "revised_stamps": len(revisions), "max_revision_bps": max((r["range_bps"] for r in revisions), default=0.0),
                     "revisions": revisions, "coverage_drops": drops, "stamp_times_utc": sorted(times)}
    return {"descriptive_only": True, "artifacts_in_manifest": len(rows),
            "last_artifact": rows[-1]["created_at"] if rows else None, "watches": out,
            "summary": {"watches_with_revisions": sorted(k for k, v in out.items() if v["revised_stamps"]),
                        "runs_with_coverage_drops": sum(len(v["coverage_drops"]) for v in out.values()),
                        "stamp_times_utc": {k: v["stamp_times_utc"] for k, v in out.items() if v["stamp_times_utc"]}}}


def main(argv: Iterable[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive-root", required=True, type=Path)
    p.add_argument("--dashboard", type=Path, default=Path("scripts/dashboard_snapshot.py"))
    p.add_argument("--output", type=Path, default=None)
    a = p.parse_args(list(argv) if argv is not None else None)
    rep = build_integrity_report(a.archive_root, dashboard_watches(a.dashboard))
    out = a.output or (a.archive_root / "integrity_report.json")
    out.write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(rep["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
