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

from research_dashboard.loader import ResearchArtifact, discover_artifacts

st.set_page_config(
    page_title="Orderflow Edge Lab — Research Dashboard",
    page_icon="📊",
    layout="wide",
)


def repo_root() -> Path:
    configured = os.environ.get("ORDERFLOW_REPO_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return DASHBOARD_DIR.parent


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
def load_artifacts(root_text: str) -> list[ResearchArtifact]:
    return discover_artifacts(Path(root_text))


def bool_label(value: bool | None) -> str:
    if value is True:
        return "YES"
    if value is False:
        return "NO"
    return "—"


def registry_rows(artifacts: list[ResearchArtifact]) -> list[dict[str, object]]:
    return [
        {
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
branch, commit = git_identity(root)

with st.sidebar:
    st.header("Research source")
    st.code(str(root))
    st.caption(f"git: {branch} @ {commit}")
    if st.button("Refresh files", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    st.markdown(
        "**Read-only boundary**\n\n"
        "This UI reads evidence/config files only. It does not retune strategies, "
        "change frozen protocols, transmit orders, or promote candidates."
    )

artifacts = load_artifacts(str(root))

st.title("Orderflow Edge Lab — Research Dashboard")
st.caption("Evidence observability for crypto, cross-market, candidate, and shadow research.")

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

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Artifacts", len(artifacts))
c2.metric("Falsified / rejected", len(falsified))
c3.metric("Blocked", len(blocked))
c4.metric("Shadow artifacts", len(shadows))
c5.metric("Explicit live-supported", len(explicit_live))

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

    left, right = st.columns(2)
    with left:
        stages = ["All"] + sorted(frame["stage"].dropna().unique().tolist())
        stage_filter = st.selectbox("Stage", stages)
    with right:
        status_query = st.text_input("Status/path contains", "")

    filtered = frame.copy()
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
        selected_path = st.selectbox(
            "Artifact",
            [a.path for a in metric_artifacts],
            key="metric_artifact",
        )
        item = next(a for a in metric_artifacts if a.path == selected_path)
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
        st.caption("No shadow/forward artifacts found in the current checkout.")
    else:
        st.dataframe(
            pd.DataFrame(registry_rows(shadows)),
            use_container_width=True,
            hide_index=True,
        )
        shadow_path = st.selectbox("Inspect shadow artifact", [a.path for a in shadows])
        shadow_item = next(a for a in shadows if a.path == shadow_path)
        st.json(shadow_item.raw, expanded=False)

with raw_tab:
    selected = st.selectbox("Artifact", [a.path for a in artifacts], key="raw_artifact")
    item = next(a for a in artifacts if a.path == selected)
    st.write(
        {
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
