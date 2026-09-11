#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

from orderflow_edge_lab.approval import ApprovalBoundPaperEngine
from orderflow_edge_lab.economics import load_economics_policy
from orderflow_edge_lab.execution import (
    DEFAULT_INSTRUMENTS,
    HashChainJournal,
    MarketSnapshot,
    RejectedIntent,
    TradeIntent,
)
from orderflow_edge_lab.research import load_candidates
from orderflow_edge_lab.reliability import deployment_readiness


FORBIDDEN_LIVE_MARKERS = (
    "MetaTrader5.order_send(",
    ".create_order(",
    ".place_order(",
    "live_transmission_enabled = True",
    '"live_transmission_enabled": true',
)


def scan_no_live_transmission(repo_root: Path) -> list[str]:
    failures = []
    for path in (repo_root / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for marker in FORBIDDEN_LIVE_MARKERS:
            if marker in text:
                failures.append(f"{path}: contains forbidden live marker {marker!r}")
    return failures


def smoke_paper() -> list[str]:
    failures = []
    now = datetime(2026, 9, 10, 20, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "state.json"
        journal = Path(tmp) / "journal.jsonl"
        market = MarketSnapshot("MNQ", 20000.00, 20000.25, now)
        intent = TradeIntent(
            strategy_id="deployment-smoke",
            symbol="MNQ",
            side="LONG",
            entry_reference=20000.25,
            stop=19995.25,
            target=20010.25,
            signal_time=now,
        )
        with ApprovalBoundPaperEngine(state, journal, starting_equity=10_000) as engine:
            intent_id = engine.submit(intent, market, now=now, evidence={"smoke": True})
            token = engine.approval_token_for(intent_id)

            try:
                engine.approve(intent_id, market, now=now)
            except RejectedIntent as exc:
                if "approval_token_mismatch" not in str(exc):
                    failures.append("missing approval token rejected for an unexpected reason")
            else:
                failures.append("missing approval token was accepted")

            moved = MarketSnapshot("MNQ", 19999.00, 19999.25, now)
            try:
                engine.approve(intent_id, moved, approval_token=token, now=now)
            except RejectedIntent as exc:
                if "approval_terms_changed" not in str(exc):
                    failures.append("approval drift rejected for an unexpected reason")
            else:
                failures.append("approval size drift was silently accepted")
            if intent_id not in engine.state["pending"] or engine.state["positions"]:
                failures.append("approval drift did not preserve pending intent and flat state")

            records = HashChainJournal.records(journal)
            if not any(row["event_type"] == "approval_bound" for row in records):
                failures.append("approval binding was not durably journaled")
            if not any(row["event_type"] == "approval_token_rejected" for row in records):
                failures.append("missing approval token attempt was not durably journaled")
            if not any(row["event_type"] == "approval_terms_changed" for row in records):
                failures.append("approval drift was not durably journaled")

            engine.approve(intent_id, market, approval_token=token, now=now)
            close_market = MarketSnapshot("MNQ", 20002.00, 20002.25, now)
            engine.close_position(intent_id, close_market, reason="smoke", now=now)
        HashChainJournal.verify(journal)
        with ApprovalBoundPaperEngine(state, journal) as restarted:
            if restarted.state["positions"] or restarted.state["pending"]:
                failures.append("restart retained closed position or pending intent")
        report = deployment_readiness(state, journal)
        if not report.ready_for_paper or report.ready_for_live:
            failures.append("paper readiness or live prohibition failed")
    return failures


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    checks: dict[str, object] = {}
    failures: list[str] = []

    checks["python"] = sys.version.split()[0]
    if sys.version_info < (3, 10):
        failures.append("Python 3.10+ required")

    live_failures = scan_no_live_transmission(root)
    checks["live_transmission_scan"] = "pass" if not live_failures else live_failures
    failures.extend(live_failures)

    candidates = load_candidates(root / "config" / "candidates.json")
    checks["candidate_count"] = len(candidates)
    if not candidates:
        failures.append("candidate registry empty")

    try:
        economics_raw = json.loads((root / "config" / "economics.json").read_text(encoding="utf-8"))
        economics = load_economics_policy(economics_raw)
        checks["economics"] = economics.report()
    except Exception as exc:
        checks["economics"] = f"fail: {type(exc).__name__}: {exc}"
        failures.append("economics configuration invalid")

    try:
        smoke_failures = smoke_paper()
        failures.extend(smoke_failures)
        checks["paper_smoke"] = "fail" if smoke_failures else "pass"
    except Exception as exc:
        checks["paper_smoke"] = f"fail: {type(exc).__name__}: {exc}"
        failures.append("paper smoke failed")

    checks["instruments"] = {
        k: {"tick_size": v.tick_size, "tick_value": v.tick_value}
        for k, v in DEFAULT_INSTRUMENTS.items()
    }
    checks["status"] = "pass" if not failures else "fail"
    checks["failures"] = failures
    print(json.dumps(checks, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
