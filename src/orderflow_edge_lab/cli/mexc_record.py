from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Mapping
from urllib.parse import quote
from urllib.request import Request, urlopen

from orderflow_edge_lab.mexc_orderflow import (
    AppendOnlyJsonl,
    FeatureEngine,
    MexcOrderFlowError,
    SequenceGapError,
    apply_recovery_commits,
    decode_ws_message,
)


DEFAULT_REST_BASE = "https://api.mexc.com"
# MEXC's current Futures WebSocket documentation publishes this separately from
# the REST base URL. Keep it configurable in case the vendor changes it.
DEFAULT_WS_URL = "wss://contract.mexc.com/edge"


def _fetch_json(url: str, *, timeout: float = 8.0) -> Mapping[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "orderflow-edge-lab/1.0"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise MexcOrderFlowError(f"MEXC public REST request returned HTTP {response.status}")
        raw = response.read(8_000_000)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MexcOrderFlowError("MEXC public REST response is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise MexcOrderFlowError("MEXC public REST response must be an object")
    return payload


def _depth_url(rest_base: str, symbol: str, limit: int) -> str:
    return f"{rest_base.rstrip('/')}/api/v1/contract/depth/{quote(symbol, safe='')}?limit={limit}"


def _commits_url(rest_base: str, symbol: str, limit: int = 1000) -> str:
    return f"{rest_base.rstrip('/')}/api/v1/contract/depth_commits/{quote(symbol, safe='')}/{limit}"


async def _snapshot_symbol(
    engine: FeatureEngine,
    raw_writer: AppendOnlyJsonl,
    feature_writer: AppendOnlyJsonl,
    *,
    rest_base: str,
    symbol: str,
    snapshot_limit: int,
) -> None:
    payload = await asyncio.to_thread(_fetch_json, _depth_url(rest_base, symbol, snapshot_limit))
    received_at_ns = time.time_ns()
    raw_writer.write(
        {
            "record_type": "rest_snapshot",
            "source": "mexc_futures_public_rest",
            "symbol": symbol,
            "received_at_ns": received_at_ns,
            "payload": payload,
        }
    )
    feature_writer.write({**engine.load_snapshot(symbol, payload), "received_at_ns": received_at_ns})


async def _recover_depth(
    engine: FeatureEngine,
    raw_writer: AppendOnlyJsonl,
    *,
    rest_base: str,
    symbol: str,
    pending: Mapping[str, Any],
    snapshot_limit: int,
) -> dict[str, Any]:
    book = engine.books[symbol]
    target = int(pending.get("version", 0))
    raw_writer.write(
        {
            "record_type": "depth_gap",
            "source": "mexc_futures_public_ws",
            "symbol": symbol,
            "received_at_ns": time.time_ns(),
            "expected_version": None if book.version is None else book.version + 1,
            "received_version": target,
        }
    )

    commits = await asyncio.to_thread(_fetch_json, _commits_url(rest_base, symbol))
    raw_writer.write(
        {
            "record_type": "rest_depth_commits",
            "source": "mexc_futures_public_rest",
            "symbol": symbol,
            "received_at_ns": time.time_ns(),
            "payload": commits,
        }
    )
    apply_recovery_commits(book, commits)

    if book.version is not None and target <= book.version:
        return {**engine.on_depth(symbol, pending), "received_at_ns": time.time_ns()}
    if book.version is not None and target == book.version + 1:
        return {**engine.on_depth(symbol, pending), "received_at_ns": time.time_ns()}

    snapshot = await asyncio.to_thread(_fetch_json, _depth_url(rest_base, symbol, snapshot_limit))
    raw_writer.write(
        {
            "record_type": "rest_snapshot",
            "source": "mexc_futures_public_rest",
            "symbol": symbol,
            "received_at_ns": time.time_ns(),
            "reason": "depth_gap_fallback",
            "payload": snapshot,
        }
    )
    engine.load_snapshot(symbol, snapshot)
    if book.version is not None and target <= book.version:
        return {**engine.on_depth(symbol, pending), "received_at_ns": time.time_ns()}
    if book.version is not None and target == book.version + 1:
        return {**engine.on_depth(symbol, pending), "received_at_ns": time.time_ns()}
    raise MexcOrderFlowError(
        f"unable to recover {symbol} order book contiguously; local={book.version}, pending={target}"
    )


async def _ping_loop(ws: Any) -> None:
    while True:
        await asyncio.sleep(15)
        await ws.send(json.dumps({"method": "ping"}, separators=(",", ":")))


async def _run_connection(
    engine: FeatureEngine,
    raw_writer: AppendOnlyJsonl,
    feature_writer: AppendOnlyJsonl,
    *,
    ws_url: str,
    rest_base: str,
    symbols: tuple[str, ...],
    snapshot_limit: int,
    deadline: float | None,
) -> None:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError("websockets package is required; reinstall the project") from exc

    for symbol in symbols:
        await _snapshot_symbol(
            engine,
            raw_writer,
            feature_writer,
            rest_base=rest_base,
            symbol=symbol,
            snapshot_limit=snapshot_limit,
        )

    raw_writer.write(
        {
            "record_type": "ws_connect",
            "source": "mexc_futures_public_ws",
            "received_at_ns": time.time_ns(),
            "ws_url": ws_url,
        }
    )

    try:
        async with websockets.connect(
            ws_url,
            ping_interval=None,
            max_size=8_000_000,
            close_timeout=5,
        ) as ws:
            for symbol in symbols:
                await ws.send(
                    json.dumps(
                        {
                            "method": "sub.deal",
                            "param": {"symbol": symbol},
                            "gzip": False,
                            "compress": False,
                        },
                        separators=(",", ":"),
                    )
                )
                await ws.send(
                    json.dumps(
                        {"method": "sub.depth", "param": {"symbol": symbol}, "gzip": False},
                        separators=(",", ":"),
                    )
                )

            pinger = asyncio.create_task(_ping_loop(ws))
            try:
                while deadline is None or time.monotonic() < deadline:
                    timeout = None if deadline is None else max(0.05, min(1.0, deadline - time.monotonic()))
                    try:
                        raw = (
                            await asyncio.wait_for(ws.recv(), timeout=timeout)
                            if timeout is not None
                            else await ws.recv()
                        )
                    except asyncio.TimeoutError:
                        continue

                    received_at_ns = time.time_ns()
                    payload = decode_ws_message(raw)
                    channel = str(payload.get("channel", ""))
                    symbol = str(payload.get("symbol", ""))

                    raw_writer.write(
                        {
                            "record_type": "ws_message",
                            "source": "mexc_futures_public_ws",
                            "received_at_ns": received_at_ns,
                            "channel": channel,
                            "symbol": symbol or None,
                            "payload": payload,
                        }
                    )

                    if channel == "push.depth":
                        if symbol not in engine.books:
                            continue
                        data = payload.get("data")
                        if not isinstance(data, Mapping):
                            raise MexcOrderFlowError("push.depth data must be an object")
                        try:
                            feature = engine.on_depth(symbol, data)
                        except SequenceGapError:
                            feature = await _recover_depth(
                                engine,
                                raw_writer,
                                rest_base=rest_base,
                                symbol=symbol,
                                pending=data,
                                snapshot_limit=snapshot_limit,
                            )
                        feature_writer.write({"received_at_ns": received_at_ns, **feature})
                    elif channel == "push.deal":
                        if symbol not in engine.books:
                            continue
                        for feature in engine.on_deals(symbol, payload.get("data")):
                            feature_writer.write({**feature, "received_at_ns": received_at_ns})
            finally:
                pinger.cancel()
                await asyncio.gather(pinger, return_exceptions=True)
    except websockets.exceptions.ConnectionClosed as exc:
        raise ConnectionError("MEXC websocket connection closed") from exc


async def run(args: argparse.Namespace) -> tuple[Path, Path]:
    symbols = tuple(dict.fromkeys(s.strip().upper() for s in args.symbol if s.strip()))
    if not symbols:
        raise ValueError("at least one --symbol is required")
    if args.duration_seconds < 0:
        raise ValueError("--duration-seconds cannot be negative")
    if not 1 <= args.snapshot_limit <= 1000:
        raise ValueError("--snapshot-limit must be in [1, 1000]")
    if args.trade_window_seconds <= 0:
        raise ValueError("--trade-window-seconds must be positive")
    if args.max_reconnects < 0:
        raise ValueError("--max-reconnects cannot be negative")

    out_dir = Path(args.output_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_path = out_dir / f"{stamp}_mexc_raw.jsonl"
    feature_path = out_dir / f"{stamp}_mexc_features.jsonl"
    deadline = None if args.duration_seconds == 0 else time.monotonic() + args.duration_seconds

    engine = FeatureEngine(
        symbols,
        trade_window_ms=int(args.trade_window_seconds * 1000),
        imbalance_levels=args.imbalance_levels,
    )

    with AppendOnlyJsonl(raw_path) as raw_writer, AppendOnlyJsonl(feature_path) as feature_writer:
        raw_writer.write(
            {
                "record_type": "session",
                "schema_version": 1,
                "source": "mexc_futures_public",
                "started_at_ns": time.time_ns(),
                "symbols": list(symbols),
                "rest_base": args.rest_base,
                "ws_url": args.ws_url,
                "snapshot_limit": args.snapshot_limit,
                "credentials_used": False,
                "live_order_transmission": False,
            }
        )

        reconnects = 0
        while deadline is None or time.monotonic() < deadline:
            try:
                await _run_connection(
                    engine,
                    raw_writer,
                    feature_writer,
                    ws_url=args.ws_url,
                    rest_base=args.rest_base,
                    symbols=symbols,
                    snapshot_limit=args.snapshot_limit,
                    deadline=deadline,
                )
                break
            except MexcOrderFlowError:
                raise
            except (ConnectionError, OSError, TimeoutError) as exc:
                reconnects += 1
                raw_writer.write(
                    {
                        "record_type": "ws_disconnect",
                        "source": "mexc_futures_public_ws",
                        "received_at_ns": time.time_ns(),
                        "reconnect_attempt": reconnects,
                        "error_type": type(exc).__name__,
                    }
                )
                if reconnects > args.max_reconnects:
                    raise RuntimeError("MEXC websocket reconnect limit exceeded") from exc
                await asyncio.sleep(min(2 ** min(reconnects, 4), 15))
    return raw_path, feature_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record public MEXC Futures trades and incremental L2 depth without trading credentials."
    )
    parser.add_argument("--symbol", action="append", default=[], help="Futures symbol; repeat for multiple symbols")
    parser.add_argument("--output-dir", default="data/mexc_orderflow")
    parser.add_argument("--duration-seconds", type=float, default=0, help="0 records until interrupted")
    parser.add_argument("--rest-base", default=DEFAULT_REST_BASE)
    parser.add_argument("--ws-url", default=DEFAULT_WS_URL)
    parser.add_argument("--snapshot-limit", type=int, default=1000)
    parser.add_argument("--trade-window-seconds", type=float, default=10.0)
    parser.add_argument("--imbalance-levels", type=int, default=10)
    parser.add_argument("--max-reconnects", type=int, default=20)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.symbol:
        args.symbol = ["ENA_USDT", "BTC_USDT"]
    try:
        raw_path, feature_path = asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except (ValueError, RuntimeError, MexcOrderFlowError) as exc:
        parser.error(str(exc))
    print(json.dumps({"raw": str(raw_path), "features": str(feature_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
