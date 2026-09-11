from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from orderflow_edge_lab.mexc_orderflow import (
    AppendOnlyJsonl,
    FeatureEngine,
    MexcOrderFlowError,
    SequenceGapError,
    apply_recovery_commits,
    iter_jsonl,
)


def _verify_manifest(path: Path) -> None:
    manifest_path = path.with_name(path.name + ".manifest.json")
    if not manifest_path.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MexcOrderFlowError("raw manifest cannot be read") from exc
    if not isinstance(manifest, Mapping):
        raise MexcOrderFlowError("raw manifest must be an object")
    expected = manifest.get("sha256")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if not isinstance(expected, str) or expected != actual:
        raise MexcOrderFlowError("raw recording SHA-256 does not match its manifest")


def _resolve_pending(
    engine: FeatureEngine,
    pending: dict[str, tuple[Mapping[str, Any], int]],
    symbol: str,
    observed_at_ns: int,
) -> dict[str, Any] | None:
    item = pending.get(symbol)
    if item is None:
        return None
    data, _original_received_at_ns = item
    book = engine.books[symbol]
    target = int(data.get("version", 0))
    if book.version is None:
        return None
    if target > book.version + 1:
        return None
    pending.pop(symbol, None)
    feature = engine.on_depth(symbol, data)
    return {"received_at_ns": observed_at_ns, **feature, "replayed_after_recovery": True}


def replay(input_path: Path, output_path: Path, *, trade_window_seconds: float, imbalance_levels: int) -> int:
    _verify_manifest(input_path)
    records = iter_jsonl(input_path)
    try:
        first = next(records)
    except StopIteration as exc:
        raise MexcOrderFlowError("raw recording is empty") from exc
    if first.get("record_type") != "session":
        raise MexcOrderFlowError("raw recording must begin with a session record")
    symbols_raw = first.get("symbols")
    if not isinstance(symbols_raw, list) or not symbols_raw or any(not isinstance(s, str) or not s for s in symbols_raw):
        raise MexcOrderFlowError("session record contains invalid symbols")
    symbols = tuple(dict.fromkeys(symbols_raw))
    engine = FeatureEngine(
        symbols,
        trade_window_ms=int(trade_window_seconds * 1000),
        imbalance_levels=imbalance_levels,
    )
    pending: dict[str, tuple[Mapping[str, Any], int]] = {}
    emitted = 0

    with AppendOnlyJsonl(output_path) as writer:
        writer.write(
            {
                "record_type": "replay_session",
                "schema_version": 1,
                "source_file": input_path.name,
                "symbols": list(symbols),
                "trade_window_seconds": trade_window_seconds,
                "imbalance_levels": imbalance_levels,
                "live_order_transmission": False,
            }
        )
        for record in records:
            record_type = record.get("record_type")
            symbol = record.get("symbol")
            received_at_ns = record.get("received_at_ns")
            if type(received_at_ns) is not int or received_at_ns <= 0:
                if record_type in {"ws_connect", "ws_disconnect", "depth_gap"}:
                    continue
                raise MexcOrderFlowError("raw record is missing a valid received_at_ns")

            if record_type == "rest_snapshot":
                if symbol not in engine.books:
                    raise MexcOrderFlowError("snapshot symbol is outside the session")
                payload = record.get("payload")
                if not isinstance(payload, Mapping):
                    raise MexcOrderFlowError("snapshot payload must be an object")
                feature = engine.load_snapshot(str(symbol), payload)
                writer.write({"received_at_ns": received_at_ns, **feature})
                emitted += 1
                resolved = _resolve_pending(engine, pending, str(symbol), received_at_ns)
                if resolved is not None:
                    writer.write(resolved)
                    emitted += 1
                continue

            if record_type == "rest_depth_commits":
                if symbol not in engine.books:
                    raise MexcOrderFlowError("commit symbol is outside the session")
                payload = record.get("payload")
                if not isinstance(payload, Mapping):
                    raise MexcOrderFlowError("commit payload must be an object")
                apply_recovery_commits(engine.books[str(symbol)], payload)
                resolved = _resolve_pending(engine, pending, str(symbol), received_at_ns)
                if resolved is not None:
                    writer.write(resolved)
                    emitted += 1
                continue

            if record_type != "ws_message":
                continue
            payload = record.get("payload")
            if not isinstance(payload, Mapping):
                raise MexcOrderFlowError("websocket payload must be an object")
            channel = payload.get("channel")
            ws_symbol = payload.get("symbol")
            if ws_symbol not in engine.books:
                continue
            ws_symbol = str(ws_symbol)

            if channel == "push.depth":
                data = payload.get("data")
                if not isinstance(data, Mapping):
                    raise MexcOrderFlowError("push.depth data must be an object")
                try:
                    feature = engine.on_depth(ws_symbol, data)
                except SequenceGapError:
                    if ws_symbol in pending:
                        raise MexcOrderFlowError("second depth gap arrived before prior recovery completed")
                    pending[ws_symbol] = (data, received_at_ns)
                    continue
                writer.write({"received_at_ns": received_at_ns, **feature})
                emitted += 1
            elif channel == "push.deal":
                for feature in engine.on_deals(ws_symbol, payload.get("data")):
                    writer.write({"received_at_ns": received_at_ns, **feature})
                    emitted += 1

        if pending:
            raise MexcOrderFlowError(
                "raw recording ended with unresolved depth sequence gaps: " + ",".join(sorted(pending))
            )
    return emitted


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay an immutable MEXC raw recording into causal order-flow features.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--trade-window-seconds", type=float, default=10.0)
    parser.add_argument("--imbalance-levels", type=int, default=10)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.trade_window_seconds <= 0:
        parser.error("--trade-window-seconds must be positive")
    if args.imbalance_levels < 1:
        parser.error("--imbalance-levels must be >= 1")
    output = args.output or args.input.with_name(args.input.stem + "_replay_features.jsonl")
    try:
        emitted = replay(
            args.input,
            output,
            trade_window_seconds=args.trade_window_seconds,
            imbalance_levels=args.imbalance_levels,
        )
    except (OSError, ValueError, MexcOrderFlowError) as exc:
        parser.error(str(exc))
    print(json.dumps({"output": str(output), "features_emitted": emitted}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
