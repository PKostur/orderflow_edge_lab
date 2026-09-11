#!/usr/bin/env python3
"""Local manual paper operations. No broker or network transmission exists."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import io
import csv
import json
from pathlib import Path

from orderflow_edge_lab.approval import ApprovalBoundPaperEngine
from orderflow_edge_lab.data import DataQualityPolicy, normalize_rows, quality_report
from orderflow_edge_lab.execution import (
    RiskPolicy, MarketSnapshot, TradeIntent, StateCorruptionError,
    EngineLockError, RejectedIntent,
)
from orderflow_edge_lab.reliability import deployment_readiness
from orderflow_edge_lab.research import parse_utc


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _market(path):
    values = _read(path)
    values["timestamp"] = parse_utc(values["timestamp"])
    return MarketSnapshot(**values)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default="runtime/paper-state.json")
    parser.add_argument("--journal", default="runtime/paper-journal.jsonl")
    parser.add_argument("--policy", help="RiskPolicy JSON; use the same assumptions across restarts")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--equity", type=float, default=10000)
    commands.add_parser("status")
    commands.add_parser("migrate", help="After operator reconciliation, back up and checkpoint version 1 state")
    submit = commands.add_parser("submit")
    submit.add_argument("--intent", required=True)
    submit.add_argument("--export", required=True, help="Fresh trade/BBO CSV; all rows must match intent symbol")
    approve = commands.add_parser("approve")
    approve.add_argument("intent_id")
    approve.add_argument("--token", required=True, help="Approval integrity token returned by submit")
    approve.add_argument("--market", required=True)
    reject = commands.add_parser("reject")
    reject.add_argument("intent_id")
    reject.add_argument("--reason", required=True)
    close = commands.add_parser("close")
    close.add_argument("intent_id")
    close.add_argument("--market", required=True)
    close.add_argument("--reason", required=True)
    commands.add_parser("kill", help="Block new entries; leaves positions for explicit paper close")
    commands.add_parser("release", help="Explicitly release the entry kill switch")
    commands.add_parser("expire", help="Remove expired pending intents and journal their identities")
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            report = deployment_readiness(args.state, args.journal)
            result = report.as_dict()
            # Read only: status never creates, migrates, or recovers execution state.
            if next(c.passed for c in report.checks if c.name == "state_journal_checkpoint"):
                state = _read(args.state)
                result.update(pending=state["pending"], positions=state["positions"], equity=state["equity"],
                              kill_switch=state["kill_switch"])
            print(json.dumps(result, indent=2, allow_nan=False))
            return 0 if report.ready_for_paper else 2
        if args.command != "init" and not Path(args.state).exists():
            raise ValueError("initialize or recover the paper engine before issuing commands")
        if args.policy:
            policy = RiskPolicy(**_read(args.policy))
        elif Path(args.state).exists():
            stored = _read(args.state)
            policy = RiskPolicy(**stored.get("engine_config", {}).get("policy", {}))
        else:
            policy = RiskPolicy()
        now = datetime.now(timezone.utc)
        intent = market = evidence = None
        if args.command == "submit":
            values = _read(args.intent)
            values["signal_time"] = parse_utc(values["signal_time"])
            intent = TradeIntent(**values)
            data = Path(args.export).read_bytes()
            events = normalize_rows(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))), default_symbol=intent.symbol)
            if any(event.symbol != intent.symbol for event in events):
                raise ValueError("export symbols do not match intent")
            report = quality_report(events, DataQualityPolicy(max_latest_age_seconds=policy.max_market_age_seconds),
                                    now_ns=int(now.timestamp() * 1_000_000_000))
            if not report.passed:
                print(json.dumps({"status": "rejected", "quality_failures": report.failures}))
                return 2
            quotes = [event for event in events if event.bid is not None and event.ask is not None]
            if not quotes:
                raise ValueError("a fresh BBO is required for paper execution")
            last = quotes[-1]
            market = MarketSnapshot(intent.symbol, last.bid, last.ask, last.timestamp)
            evidence = {"export_sha256": hashlib.sha256(data).hexdigest(), "quality": asdict(report)}
        elif args.command in {"approve", "close"}:
            market = _market(args.market)
        now = datetime.now(timezone.utc)
        with ApprovalBoundPaperEngine(args.state, args.journal, starting_equity=getattr(args, "equity", 10000),
                                      policy=policy, migrate_legacy=args.command == "migrate") as engine:
            if args.command == "submit":
                intent_id = engine.submit(intent, market, now=now, evidence=evidence)
                result = {"intent_id": intent_id, "approval_token": engine.approval_token_for(intent_id)}
            elif args.command == "approve":
                result = engine.approve(args.intent_id, market, approval_token=args.token, now=now)
            elif args.command == "reject":
                engine.reject(args.intent_id, reason=args.reason, now=now)
                result = {"intent_id": args.intent_id}
            elif args.command == "close":
                result = engine.close_position(args.intent_id, market, reason=args.reason, now=now)
            elif args.command == "kill":
                engine.engage_kill_switch(now=now)
                result = {"kill_switch": True, "positions_remaining": len(engine.state["positions"])}
            elif args.command == "release":
                engine.release_kill_switch(now=now)
                result = {"kill_switch": False}
            elif args.command == "expire":
                result = {"expired_intents": engine.expire_pending(now=now)}
            else:
                result = {"revision": engine.state["revision"], "equity": engine.state["equity"]}
        print(json.dumps({"mode": "paper", "command": args.command, "status": "ok", "result": result},
                         indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError, StateCorruptionError,
            EngineLockError, RejectedIntent) as exc:
        result = {"mode": "paper", "status": "failed", "error_type": type(exc).__name__}
        if isinstance(exc, (RejectedIntent, StateCorruptionError)):
            result["reason"] = str(exc)
        print(json.dumps(result))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
