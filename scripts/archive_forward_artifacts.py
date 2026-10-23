"""Copy forward-watch report artifacts out of GitHub Actions storage before they expire (90 days).

Runs inside GitHub Actions (``forward-artifact-archive-v1.yml``) with the workflow token.  Writes every not yet
archived report artifact, extracted, under ``<archive_root>/<artifact name>/<created date>/<run id>-<artifact id>/``
and appends one line per artifact to ``<archive_root>/manifest.jsonl`` (artifact id, run id, head SHA, created
time, GitHub's zip digest and the sha256 of every extracted file).  Chained ledger artifacts, which carry their
whole history in every run, keep only the newest artifact of each completed ISO week.

Read-only towards the watches: it never changes a report, a config or a workflow.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Iterable, Mapping

REPORT_ARTIFACTS = (
    "multi-premia-blend-v1",
    "fade24-forward-v1",
    "near-miss-forward-v1",
    "tradfi-perps-forward-v1",
    "carry-forward-v1",
    "crypto-trend-core-v1",
    "crypto-trend-core-voltarget-v1",
    "trend-portfolio-forward-v1",
    "cross-asset-trend-forward-v1",
    "cross-asset-trend-invvol-forward-v1",
    "canonical-v3-forward-companion-v1",
)
LEDGER_ARTIFACTS = ("liquidation-flow-ledger-v1", "news-sentiment-ledger-v1", "hyperliquid-vaults-panel-v1")
API = "https://api.github.com"


def _iso_week(created_at: str) -> tuple[int, int]:
    y, w, _ = datetime.date.fromisoformat(str(created_at)[:10]).isocalendar()
    return int(y), int(w)


def select(artifacts: Iterable[Mapping[str, Any]], archived_ids: set[int],
           today: datetime.date | None = None) -> list[Mapping[str, Any]]:
    """Artifacts to download: unexpired, allow-listed, not archived yet.

    Ledger artifacts carry their whole history, so only the newest one of each completed ISO week is kept (one
    download per ledger per week); the running week is left to GitHub's 90-day artifacts until it is complete.
    """
    cur = (today or datetime.datetime.now(datetime.timezone.utc).date()).isocalendar()[:2]
    out: list[Mapping[str, Any]] = []
    newest_ledger: dict[tuple[str, str], Mapping[str, Any]] = {}
    seen: set[int] = set()
    for a in artifacts:
        if a.get("expired") or int(a["id"]) in seen:
            continue
        seen.add(int(a["id"]))
        name = a["name"]
        if name in REPORT_ARTIFACTS:
            if int(a["id"]) not in archived_ids:
                out.append(a)
        elif name in LEDGER_ARTIFACTS:
            week = _iso_week(a["created_at"])
            if week >= tuple(cur):
                continue                               # running week: wait until it is complete
            key = (name, "%d-W%02d" % week)            # newest of the week over all unexpired, then skip if archived
            if key not in newest_ledger or str(a["created_at"]) > str(newest_ledger[key]["created_at"]):
                newest_ledger[key] = a
    out.extend(a for a in newest_ledger.values() if int(a["id"]) not in archived_ids)
    return sorted(out, key=lambda a: (str(a["created_at"]), int(a["id"])))


def archived_ids_from(manifest: Path) -> set[int]:
    if not manifest.exists():
        return set()
    return {int(json.loads(line)["artifact_id"]) for line in manifest.read_text(encoding="utf-8").splitlines() if line}


def target_dir(root: Path, a: Mapping[str, Any]) -> Path:
    day = str(a["created_at"])[:10]
    if a["name"] in LEDGER_ARTIFACTS:
        return root / a["name"] / ("%d-W%02d" % _iso_week(a["created_at"]))
    return root / a["name"] / day / f"{a['workflow_run']['id']}-{a['id']}"


def extract(zip_bytes: bytes, dest: Path) -> dict[str, str]:
    if dest.exists():
        shutil.rmtree(dest)      # a newer same-day ledger replaces the folder, so manifest hashes match the files
    dest.mkdir(parents=True, exist_ok=True)
    hashes = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError(f"unsafe path in artifact: {info.filename}")
            data = z.read(info)
            (dest / name).parent.mkdir(parents=True, exist_ok=True)
            (dest / name).write_bytes(data)
            hashes[str(name)] = hashlib.sha256(data).hexdigest()
    return hashes


def _get(url: str, token: str) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    # unredirected: the token goes to api.github.com only, never to the blob host an artifact download redirects to
    req.add_unredirected_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def list_artifacts(repo: str, token: str) -> list[dict[str, Any]]:
    out, page = [], 1
    while True:
        batch = json.loads(_get(f"{API}/repos/{repo}/actions/artifacts?per_page=100&page={page}", token))["artifacts"]
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive-root", required=True, type=Path)
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = p.parse_args(argv)
    token = os.environ["GH_TOKEN"]
    manifest = args.archive_root / "manifest.jsonl"
    todo = select(list_artifacts(args.repo, token), archived_ids_from(manifest))
    args.archive_root.mkdir(parents=True, exist_ok=True)
    with manifest.open("a", encoding="utf-8") as m:
        for a in todo:
            dest = target_dir(args.archive_root, a)
            files = extract(_get(a["archive_download_url"], token), dest)
            m.write(json.dumps({"artifact_id": a["id"], "name": a["name"], "run_id": a["workflow_run"]["id"],
                                "head_sha": a["workflow_run"].get("head_sha"), "created_at": a["created_at"],
                                "zip_digest": a.get("digest"), "path": str(dest.relative_to(args.archive_root)),
                                "files_sha256": files}, sort_keys=True) + "\n")
    print(json.dumps({"archived": len(todo)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
