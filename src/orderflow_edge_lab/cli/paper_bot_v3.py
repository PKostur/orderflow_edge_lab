"""CLI for the finite, offline-only v3 paper-bot simulator."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from orderflow_edge_lab.paper_bot_v3 import (
    POLICY_SCHEMA,
    PaperBotV3Error,
    run_paper_bot_v3,
    verify_paper_bot_artifact_file_v3,
    write_paper_bot_artifact_v3,
)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-JSON numeric constant is rejected: {value}")


def _load_json_object(path: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=_reject_json_constant)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise PaperBotV3Error(f"cannot read JSON object from {path}") from exc
    if not isinstance(value, dict):
        raise PaperBotV3Error(f"JSON at {path} must be an object")
    return value


def _load_jsonl(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise PaperBotV3Error(f"cannot read JSONL recording from {path}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            raise PaperBotV3Error(f"invalid JSONL row {line_number} in {path}") from exc
        if not isinstance(value, dict):
            raise PaperBotV3Error(f"JSONL row {line_number} in {path} must be an object")
        rows.append(value)
    if not rows:
        raise PaperBotV3Error("recording must contain at least one JSON object")
    return rows


def _flat(_: tuple[Mapping[str, Any], ...]) -> float:
    return 0.0


def _close_momentum(history: tuple[Mapping[str, Any], ...]) -> float:
    if len(history) < 2:
        return 0.0
    return 0.25 if float(history[-1]["close"]) > float(history[-2]["close"]) else -0.25


def _signal_definition(name: str) -> tuple[Callable[[tuple[Mapping[str, Any], ...]], float], dict[str, Any]]:
    """Return a built-in signal and its explicit, non-secret parameter map."""

    return {
        "flat": (_flat, {}),
        "close-momentum": (_close_momentum, {}),
    }[name]


def _signal(name: str) -> Callable[[tuple[Mapping[str, Any], ...]], float]:
    return _signal_definition(name)[0]


def _signal_fingerprint(name: str) -> str:
    """Hash the selected built-in implementation and its declared parameters."""

    signal, parameters = _signal_definition(name)
    source = inspect.getsource(signal).encode("utf-8")
    definition = {
        "schema": "orderflow_edge_lab.paper_bot_cli_signal_definition.v1",
        "signal_name": name,
        "parameters": parameters,
        "source_sha256": hashlib.sha256(source).hexdigest(),
    }
    return hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _demo(signal_name: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    base = 1_700_000_000_000_000_000
    frames = [
        {
            "ts_ns": base + offset * 1_000_000_000,
            "received_ns": base + offset * 1_000_000_000,
            "symbol": "SYNTH-USD",
            "bid": bid,
            "ask": ask,
            "close": close,
            "source_id": "synthetic-demo-v3",
            "batch_id": "demo-0001",
        }
        for offset, (bid, ask, close) in enumerate(((99.9, 100.1, 100.0), (100.9, 101.1, 101.0), (100.4, 100.6, 100.5)))
    ]
    policy = {
        "schema": POLICY_SCHEMA,
        "signal_id": f"synthetic-demo-{signal_name}-v1",
        "signal_fingerprint": _signal_fingerprint(signal_name),
        "instrument": {
            "symbol": "SYNTH-USD",
            "contract_multiplier": 1.0,
            "instrument_type": "synthetic_linear",
            "funding_treatment": "not_modeled",
        },
        "initial_cash": 10_000.0,
        "fee_rate": 0.0005,
        "slippage_bps": 2.0,
        "max_quote_age_ns": 2_000_000_000,
        "max_position_fraction": 0.50,
        "max_gross_exposure_fraction": 0.50,
        "max_loss_fraction": 0.20,
        "max_drawdown_fraction": 0.20,
    }
    return frames, policy


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Finite offline v3 paper simulation; no live or network capability.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--recording", help="pre-acquired finite JSONL quote recording")
    source.add_argument("--synthetic-demo", action="store_true", help="run only the clearly marked synthetic demo")
    parser.add_argument("--policy", help="caller-declared v3 policy JSON; required with --recording")
    parser.add_argument(
        "--signal",
        choices=("flat", "close-momentum"),
        default="close-momentum",
        help="built-in signal; policy.signal_fingerprint must match its source and declared parameters",
    )
    parser.add_argument("--checkpoint", help="saved checkpoint JSON from a prior partial local replay")
    parser.add_argument("--max-events", type=int, help="stop after this many events and emit a restart checkpoint")
    parser.add_argument("--mode", default="offline", help="only 'offline' is accepted; live is rejected")
    parser.add_argument("--run-id", default="paper-bot-v3-cli")
    parser.add_argument("--output", required=True, help="new artifact path; existing paths are never overwritten")
    parser.add_argument("--verify", action="store_true", help="read-only verify --output instead of running a replay")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            result = verify_paper_bot_artifact_file_v3(args.output)
            print(json.dumps(result, sort_keys=True, allow_nan=False))
            return 0 if result["status"] == "VERIFIED_SIMULATED_LOCAL_REPLAY" else 2
        if not args.synthetic_demo and not args.recording:
            raise PaperBotV3Error("choose exactly one of --recording or --synthetic-demo")
        if args.synthetic_demo:
            frames, policy = _demo(args.signal)
            if args.policy:
                policy = _load_json_object(args.policy)
            synthetic_demo = True
        else:
            if not args.policy:
                raise PaperBotV3Error("--policy is required with --recording")
            frames, policy, synthetic_demo = _load_jsonl(args.recording), _load_json_object(args.policy), False
        expected_fingerprint = _signal_fingerprint(args.signal)
        if not isinstance(policy.get("signal_fingerprint"), str) or policy["signal_fingerprint"].lower() != expected_fingerprint:
            raise PaperBotV3Error("policy.signal_fingerprint does not match selected --signal source and parameters")
        checkpoint = _load_json_object(args.checkpoint) if args.checkpoint else None
        artifact = run_paper_bot_v3(
            frames,
            _signal(args.signal),
            policy,
            checkpoint=checkpoint,
            run_id=args.run_id,
            mode=args.mode,
            max_events=args.max_events,
            synthetic_demo=synthetic_demo,
        )
        written = write_paper_bot_artifact_v3(args.output, artifact)
        print(json.dumps({"status": artifact["status"], "mode": artifact["mode"], **written}, sort_keys=True, allow_nan=False))
        return 0 if artifact["status"] in {"COMPLETE", "PARTIAL"} else 2
    except (PaperBotV3Error, OSError, ValueError) as exc:
        print(json.dumps({"status": "INVALID", "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
