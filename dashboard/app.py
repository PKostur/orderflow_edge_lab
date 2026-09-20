from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

from research_dashboard.loader import (
    ResearchArtifact,
    discover_artifacts,
    discover_git_ref_artifacts,
)

st.set_page_config(
    page_title="Orderflow Edge Lab — Research Dashboard",
    page_icon="📊",
    layout="wide",
)

DEFAULT_EXTRA_REFS = (
    "research/cross-market-futures-v1",
    "research/cross-market-etf-v1",
)


def repo_root() -> Path:
    configured = os.environ.get("ORDERFLOW_REPO_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return DASHBOARD_DIR.parent


def configured_refs() -> list[str]:
    value = os.environ.get("ORDERFLOW_DASHBOARD_REFS")
    if value is None:
        return list(DEFAULT_EXTRA_REFS)
    return [item.strip() for item in value.split(",") if item.strip()]


def git_identity(root: Path) -> tuple[str, str]:
    def run(*args: str) -> str:
        try:
            return subprocess.check_output(
                ["git", "-C", str(root), *args],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return "unknown"

    return run("rev-parse", "--abbrev-ref", "HEAD"), run("rev-parse", "--short", "HEAD")


@st.cache_data(show_spinner=False)
def load_artifacts(root_text: str, refs_text: str) -> list[ResearchArtifact]:
    root = Path(root_text)
    worktree = discover_artifacts(root)
    refs = [item for item in refs_text.split(",") if item]
    branch_evidence = discover_git_ref_artifacts(root, refs)
    return worktree + branch_evidence


def bool_label(value: bool | None) -> str:
    if value is True:
        return "YES"
    if value is False:
        return "NO"
    return "—"


def artifact_key(item: ResearchArtifact) -> str:
    return f"{item.source_ref} :: {item.path}"


def registry_rows(artifacts: list[ResearchArtifact]) -> list[dict[str, object]]:
    return [
        {
            "source": item.source_ref,
            "project": item.project_id,
            "stage": item.stage,
            "status": item.status,
            "persistent_edge": bool_label(item.persistent_edge),
            "candidate": bool_label(item.candidate),
            "live": bool_label(item.live_supported),
            "leverage": bool_label(item.leverage_supported),
            "shadow": item.is_shadow,
            "path": item.path,
        }
        for item in artifacts
    ]


root = repo_root()
refs = configured_refs()
branch, commit = git_identity(root)

with st.sidebar:
    st.header("Research source")
    st.code(str(root))
    st.caption(f"git: {branch} @ {commit}")
    st.markdown("**Additional read-only refs**")
    if refs:
        st.code("\n".join(refs))
    else:
        st.caption("None configured.")
    if st.button("Refresh files", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.markdown(
        "**Read-only boundary**\n\n"
        "This UI reads evidence/config files only. It does not retune strategies, "
        "change frozen protocols, transmit orders, or promote candidates."
    )

artifacts = load_artifacts(str(root), ",".join(refs))

st.title("Orderflow Edge Lab — Research Dashboard")
st.caption(
    "Evidence observability across the current worktree and already-fetched research refs."
)

if not artifacts:
    st.warning(
        "No research/config artifacts were found. The dashboard does not generate "
        "synthetic fallback data."
    )
    st.stop()

parse_errors = [a for a in artifacts if a.parse_error]
falsified = [a for a in artifacts if any(x in a.status.upper() for x in ("FALSIFIED", "REJECTED"))]
blocked = [a for a in artifacts if "BLOCKED" in a.status.upper()]
shadows = [a for a in artifacts if a.is_shadow]
explicit_live = [a for a in artifacts if a.live_supported is True]
source_count = len({a.source_ref for a in artifacts})

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Evidence records", len(artifacts))
c2.metric("Sources", source_count)
c3.metric("Falsified / rejected", len(falsified))
c4.metric("Blocked", len(blocked))
c5.metric("Shadow records", len(shadows))
c6.metric("Explicit live-supported", len(explicit_live))

if explicit_live:
    st.error(
        "At least one artifact explicitly reports live execution support. Review it "
        "against the repository live-execution boundary before taking any action."
    )
else:
    st.info("No loaded artifact explicitly establishes live execution support.")

if parse_errors:
    st.warning(f"{len(parse_errors)} artifact(s) could not be parsed; they remain visible in the registry.")

overview_tab, registry_tab, metrics_tab, shadow_tab, raw_tab = st.tabs(
    ["Overview", "Evidence registry", "Metrics", "Shadow / forward", "Artifact viewer"]
)

with overview_tab:
    st.subheader("Research-state distribution")
    stage_counts = (
        pd.DataFrame(registry_rows(artifacts))
        .groupby("stage", dropna=False)
        .size()
        .sort_values(ascending=False)
    )
    st.bar_chart(stage_counts)

    st.subheader("Explicit safety / promotion flags")
    flag_rows = []
    for item in artifacts:
        if any(
            value is not None
            for value in (
                item.persistent_edge,
                item.candidate,
                item.live_supported,
                item.leverage_supported,
            )
        ):
            flag_rows.append(
                {
                    "source": item.source_ref,
                    "project": item.project_id,
                    "status": item.status,
                    "edge": bool_label(item.persistent_edge),
                    "candidate": bool_label(item.candidate),
                    "live": bool_label(item.live_supported),
                    "leverage": bool_label(item.leverage_supported),
                    "path": item.path,
                }
            )
    if flag_rows:
        st.dataframe(pd.DataFrame(flag_rows), use_container_width=True, hide_index=True)
    else:
        st.caption("No explicit promotion/safety flags were found in loaded artifacts.")

with registry_tab:
    rows = registry_rows(artifacts)
    frame = pd.DataFrame(rows)

    c_left, c_mid, c_right = st.columns(3)
    with c_left:
        sources = ["All"] + sorted(frame["source"].dropna().unique().tolist())
        source_filter = st.selectbox("Source", sources)
    with c_mid:
        stages = ["All"] + sorted(frame["stage"].dropna().unique().tolist())
        stage_filter = st.selectbox("Stage", stages)
    with c_right:
        status_query = st.text_input("Status/path contains", "")

    filtered = frame.copy()
    if source_filter != "All":
        filtered = filtered[filtered["source"] == source_filter]
    if stage_filter != "All":
        filtered = filtered[filtered["stage"] == stage_filter]
    if status_query.strip():
        q = status_query.strip().lower()
        filtered = filtered[
            filtered["status"].str.lower().str.contains(q, na=False)
            | filtered["path"].str.lower().str.contains(q, na=False)
            | filtered["project"].str.lower().str.contains(q, na=False)
        ]

    st.dataframe(filtered, use_container_width=True, hide_index=True)

with metrics_tab:
    metric_artifacts = [a for a in artifacts if a.metrics]
    if not metric_artifacts:
        st.caption("No numeric research metrics detected.")
    else:
        options = {artifact_key(a): a for a in metric_artifacts}
        selected_key = st.selectbox("Artifact", list(options), key="metric_artifact")
        item = options[selected_key]
        metric_frame = pd.DataFrame(
            [{"metric": key, "value": value} for key, value in sorted(item.metrics.items())]
        )
        st.dataframe(metric_frame, use_container_width=True, hide_index=True)

        bps = metric_frame[metric_frame["metric"].str.contains("bps", case=False, na=False)].copy()
        if not bps.empty:
            st.subheader("Basis-point metrics")
            st.bar_chart(bps.set_index("metric")["value"])

with shadow_tab:
    if not shadows:
        st.caption("No shadow/forward artifacts found in the loaded sources.")
    else:
        st.dataframe(
            pd.DataFrame(registry_rows(shadows)),
            use_container_width=True,
            hide_index=True,
        )
        options = {artifact_key(a): a for a in shadows}
        shadow_key = st.selectbox("Inspect shadow artifact", list(options))
        st.json(options[shadow_key].raw, expanded=False)

with raw_tab:
    options = {artifact_key(a): a for a in artifacts}
    selected_key = st.selectbox("Artifact", list(options), key="raw_artifact")
    item = options[selected_key]
    st.write(
        {
            "source": item.source_ref,
            "project": item.project_id,
            "stage": item.stage,
            "status": item.status,
            "persistent_edge": item.persistent_edge,
            "candidate": item.candidate,
            "live_supported": item.live_supported,
            "leverage_supported": item.leverage_supported,
            "parse_error": item.parse_error,
        }
    )
    if item.kind in {"json", "jsonl"}:
        st.json(item.raw, expanded=False)
    else:
        markdown = item.raw.get("_markdown") if isinstance(item.raw, dict) else None
        if markdown:
            st.markdown(markdown)
        else:
            st.code(json.dumps(item.raw, indent=2, default=str))
