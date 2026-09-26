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
    FEATURE_SCHEMA_VERSION,
    FeatureEngine,
    MexcOrderFlowError,
    SequenceGapError,
    apply_recovery_commits,
    decode_ws_message,
    depth_version_range,
)


DEFAULT_REST_BASE = "https://api.mexc.com"
DEFAULT_WS_URL = "wss://contract.mexc.com/edge"


def _fetch_json(url: str, *, timeout: float = 8.0) -> Mapping[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "orderflow-edge-lab/1.0",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise MexcOrderFlowError(
                f"MEXC public REST request returned HTTP {response.status}"
            )
        raw = response.read(8_000_000)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MexcOrderFlowError(
            "MEXC public REST response is not valid JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise MexcOrderFlowError(
            "MEXC public REST response must be an object"
        )
    return payload


def _depth_url(rest_base: str, symbol: str, limit: int) -> str:
    return (
        f"{rest_base.rstrip('/')}/api/v1/contract/depth/"
        f"{quote(symbol, safe='')}?limit={limit}"
    )


def _commits_url(
    rest_base: str,
    symbol: str,
    limit: int = 1000,
) -> str:
    return (
        f"{rest_base.rstrip('/')}/api/v1/contract/depth_commits/"
        f"{quote(symbol, safe='')}/{limit}"
    )


def _parse_symbol_aliases(
    values: list[str],
    symbols: tuple[str, ...],
) -> dict[str, str]:
    aliases = {symbol: symbol for symbol in symbols}
    for raw in values:
        if "=" not in raw:
            raise ValueError("--symbol-alias must use LOGICAL=NATIVE")
        logical, native = (part.strip().upper() for part in raw.split("=", 1))
        if not logical or not native:
            raise ValueError("--symbol-alias must use non-empty LOGICAL=NATIVE")
        if logical not in aliases:
            raise ValueError(
                f"--symbol-alias logical symbol is not in --symbol panel: {logical}"
            )
        aliases[logical] = native
    native_values = list(aliases.values())
    if len(set(native_values)) != len(native_values):
        raise ValueError("venue-native symbol aliases must be one-to-one")
    return aliases


async def _snapshot_symbol(
    engine: FeatureEngine,
    raw_writer: AppendOnlyJsonl,
    feature_writer: AppendOnlyJsonl,
    *,
    rest_base: str,
    symbol: str,
    snapshot_limit: int,
    venue_symbol: str | None = None,
    reason: str | None = None,
    max_attempts: int = 3,
) -> None:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    last_error: MexcOrderFlowError | None = None
    for attempt in range(1, max_attempts + 1):
        payload = await asyncio.to_thread(
            _fetch_json,
            _depth_url(rest_base, venue_symbol or symbol, snapshot_limit),
        )
        received_at_ns = time.time_ns()
        try:
            feature = engine.load_snapshot(symbol, payload)
        except MexcOrderFlowError as exc:
            last_error = exc
            raw_writer.write(
                {
                    "record_type": "rest_snapshot_rejected",
                    "source": "mexc_futures_public_rest",
                    "symbol": symbol,
                    "venue_symbol": venue_symbol or symbol,
                    "received_at_ns": received_at_ns,
                    "attempt": attempt,
                    "reason": str(exc),
                    "payload": payload,
                }
            )
            if attempt >= max_attempts:
                break
            await asyncio.sleep(0.25 * attempt)
            continue

        raw_record: dict[str, Any] = {
            "record_type": "rest_snapshot",
            "source": "mexc_futures_public_rest",
            "symbol": symbol,
            "venue_symbol": venue_symbol or symbol,
            "received_at_ns": received_at_ns,
            "attempt": attempt,
            "payload": payload,
        }
        if reason is not None:
            raw_record["reason"] = reason
        raw_writer.write(raw_record)
        feature_writer.write(
            {
                **feature,
                "received_at_ns": received_at_ns,
                "snapshot_attempt": attempt,
                **({"snapshot_reason": reason} if reason else {}),
            }
        )
        return

    raise MexcOrderFlowError(
        f"{symbol}: unable to obtain a valid depth snapshot after {max_attempts} attempts: "
        f"{last_error}"
    )


async def _bootstrap_snapshots(
    engine: FeatureEngine,
    raw_writer: AppendOnlyJsonl,
    feature_writer: AppendOnlyJsonl,
    *,
    rest_base: str,
    symbols: tuple[str, ...],
    venue_symbols: Mapping[str, str],
    snapshot_limit: int,
    snapshot_max_attempts: int,
    failure_policy: str,
) -> set[str]:
    if failure_policy not in {"fail", "continue"}:
        raise ValueError("failure_policy must be fail or continue")
    unavailable: set[str] = set()
    for symbol in symbols:
        try:
            await _snapshot_symbol(
                engine,
                raw_writer,
                feature_writer,
                rest_base=rest_base,
                symbol=symbol,
                snapshot_limit=snapshot_limit,
                venue_symbol=venue_symbols[symbol],
                reason="post_subscription_initial_snapshot",
                max_attempts=snapshot_max_attempts,
            )
        except MexcOrderFlowError as exc:
            if failure_policy == "fail":
                raise
            unavailable.add(symbol)
            received_at_ns = time.time_ns()
            raw_writer.write(
                {
                    "record_type": "snapshot_unavailable",
                    "source": "mexc_futures_public_rest",
                    "symbol": symbol,
                    "venue_symbol": venue_symbols[symbol],
                    "received_at_ns": received_at_ns,
                    "snapshot_max_attempts": snapshot_max_attempts,
                    "failure_policy": failure_policy,
                    "reason": str(exc),
                }
            )
            feature_writer.write(
                {
                    "record_type": "symbol_unavailable",
                    "feature_schema_version": FEATURE_SCHEMA_VERSION,
                    "source": "mexc_futures_public_rest",
                    "symbol": symbol,
                    "venue_symbol": venue_symbols[symbol],
                    "received_at_ns": received_at_ns,
                    "snapshot_max_attempts": snapshot_max_attempts,
                    "reason": str(exc),
                }
            )
    return unavailable


async def _recover_depth(
    engine: FeatureEngine,
    raw_writer: AppendOnlyJsonl,
    feature_writer: AppendOnlyJsonl,
    *,
    rest_base: str,
    symbol: str,
    venue_symbol: str,
    pending: Mapping[str, Any],
    snapshot_limit: int,
    snapshot_max_attempts: int,
) -> dict[str, Any]:
    book = engine.books[symbol]
    begin, end, version = depth_version_range(pending)
    expected = None if book.version is None else book.version + 1
    raw_writer.write(
        {
            "record_type": "depth_gap",
            "source": "mexc_futures_public_ws",
            "symbol": symbol,
            "received_at_ns": time.time_ns(),
            "expected_version": expected,
            "received_begin_version": begin,
            "received_end_version": end,
            "received_version": version,
        }
    )

    commits = await asyncio.to_thread(
        _fetch_json,
        _commits_url(rest_base, venue_symbol),
    )
    raw_writer.write(
        {
            "record_type": "rest_depth_commits",
            "source": "mexc_futures_public_rest",
            "symbol": symbol,
            "venue_symbol": venue_symbol,
            "received_at_ns": time.time_ns(),
            "stop_version": end,
            "payload": commits,
        }
    )
    apply_recovery_commits(
        book,
        commits,
        stop_version=end,
    )

    try:
        return {
            **engine.on_depth(symbol, pending, observed=False),
            "received_at_ns": time.time_ns(),
            "recovered_after_gap": True,
        }
    except SequenceGapError:
        pass

    await _snapshot_symbol(
        engine,
        raw_writer,
        feature_writer,
        rest_base=rest_base,
        symbol=symbol,
        snapshot_limit=snapshot_limit,
        venue_symbol=venue_symbol,
        reason="depth_gap_fallback",
        max_attempts=snapshot_max_attempts,
    )

    try:
        return {
            **engine.on_depth(symbol, pending, observed=False),
            "received_at_ns": time.time_ns(),
            "recovered_after_gap": True,
        }
    except SequenceGapError as exc:
        raise MexcOrderFlowError(
            f"unable to recover {symbol} order book contiguously; "
            f"local={book.version}, pending={begin}..{end}"
        ) from exc


async def _ping_loop(ws: Any) -> None:
    while True:
        await asyncio.sleep(15)
        await ws.send(
            json.dumps({"method": "ping"}, separators=(",", ":"))
        )


async def _run_connection(
    engine: FeatureEngine,
    raw_writer: AppendOnlyJsonl,
    feature_writer: AppendOnlyJsonl,
    *,
    ws_url: str,
    rest_base: str,
    symbols: tuple[str, ...],
    venue_symbols: Mapping[str, str],
    snapshot_limit: int,
    snapshot_max_attempts: int,
    snapshot_failure_policy: str,
    deadline: float | None,
) -> set[str]:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "websockets package is required; reinstall the project"
        ) from exc

    native_to_logical = {native: logical for logical, native in venue_symbols.items()}
    try:
        async with websockets.connect(
            ws_url,
            ping_interval=None,
            max_size=8_000_000,
            close_timeout=5,
        ) as ws:
            raw_writer.write(
                {
                    "record_type": "ws_connect",
                    "source": "mexc_futures_public_ws",
                    "received_at_ns": time.time_ns(),
                    "ws_url": ws_url,
                }
            )

            # Subscribe before fetching snapshots. WebSocket updates are then
            # buffered while REST snapshots are obtained, eliminating the
            # snapshot-before-subscription blind window.
            for symbol in symbols:
                venue_symbol = venue_symbols[symbol]
                await ws.send(
                    json.dumps(
                        {
                            "method": "sub.deal",
                            "param": {"symbol": venue_symbol},
                            "gzip": False,
                            "compress": False,
                        },
                        separators=(",", ":"),
                    )
                )
                await ws.send(
                    json.dumps(
                        {
                            "method": "sub.depth",
                            "param": {
                                "symbol": venue_symbol,
                                "compress": False,
                            },
                            "gzip": False,
                        },
                        separators=(",", ":"),
                    )
                )

            unavailable_symbols = await _bootstrap_snapshots(
                engine,
                raw_writer,
                feature_writer,
                rest_base=rest_base,
                symbols=symbols,
                venue_symbols=venue_symbols,
                snapshot_limit=snapshot_limit,
                snapshot_max_attempts=snapshot_max_attempts,
                failure_policy=snapshot_failure_policy,
            )

            pinger = asyncio.create_task(_ping_loop(ws))
            try:
                while deadline is None or time.monotonic() < deadline:
                    timeout = (
                        None
                        if deadline is None
                        else max(
                            0.05,
                            min(1.0, deadline - time.monotonic()),
                        )
                    )
                    try:
                        raw = (
                            await asyncio.wait_for(
                                ws.recv(),
                                timeout=timeout,
                            )
                            if timeout is not None
                            else await ws.recv()
                        )
                    except asyncio.TimeoutError:
                        continue

                    received_at_ns = time.time_ns()
                    payload = decode_ws_message(raw)
                    channel = str(payload.get("channel", ""))
                    venue_symbol = str(payload.get("symbol", ""))
                    symbol = native_to_logical.get(venue_symbol, venue_symbol)

                    raw_writer.write(
                        {
                            "record_type": "ws_message",
                            "source": "mexc_futures_public_ws",
                            "received_at_ns": received_at_ns,
                            "channel": channel,
                            "symbol": symbol or None,
                            "venue_symbol": venue_symbol or None,
                            "payload": payload,
                        }
                    )

                    if channel == "push.depth":
                        if symbol not in engine.books or symbol in unavailable_symbols:
                            continue
                        data = payload.get("data")
                        if not isinstance(data, Mapping):
                            raise MexcOrderFlowError(
                                "push.depth data must be an object"
                            )
                        try:
                            feature = engine.on_depth(symbol, data)
                        except SequenceGapError:
                            feature = await _recover_depth(
                                engine,
                                raw_writer,
                                feature_writer,
                                rest_base=rest_base,
                                symbol=symbol,
                                venue_symbol=venue_symbol,
                                pending=data,
                                snapshot_limit=snapshot_limit,
                                snapshot_max_attempts=snapshot_max_attempts,
                            )
                        feature_writer.write(
                            {
                                "received_at_ns": received_at_ns,
                                **feature,
                            }
                        )
                    elif channel == "push.deal":
                        if symbol not in engine.books or symbol in unavailable_symbols:
                            continue
                        for feature in engine.on_deals(
                            symbol,
                            payload.get("data"),
                        ):
                            feature_writer.write(
                                {
                                    **feature,
                                    "received_at_ns": received_at_ns,
                                }
                            )
            finally:
                pinger.cancel()
                await asyncio.gather(
                    pinger,
                    return_exceptions=True,
                )
            return unavailable_symbols
    except websockets.exceptions.ConnectionClosed as exc:
        raise ConnectionError(
            "MEXC websocket connection closed"
        ) from exc


async def run(args: argparse.Namespace) -> tuple[Path, Path]:
    symbols = tuple(
        dict.fromkeys(
            s.strip().upper()
            for s in args.symbol
            if s.strip()
        )
    )
    if not symbols:
        raise ValueError("at least one --symbol is required")
    venue_symbols = _parse_symbol_aliases(args.symbol_alias, symbols)
    if args.duration_seconds < 0:
        raise ValueError(
            "--duration-seconds cannot be negative"
        )
    if not 1 <= args.snapshot_limit <= 1000:
        raise ValueError(
            "--snapshot-limit must be in [1, 1000]"
        )
    if args.snapshot_max_attempts < 1:
        raise ValueError(
            "--snapshot-max-attempts must be >= 1"
        )
    if args.snapshot_failure_policy not in {"fail", "continue"}:
        raise ValueError(
            "--snapshot-failure-policy must be fail or continue"
        )
    if args.trade_window_seconds <= 0:
        raise ValueError(
            "--trade-window-seconds must be positive"
        )
    if args.max_reconnects < 0:
        raise ValueError(
            "--max-reconnects cannot be negative"
        )

    out_dir = Path(args.output_dir)
    stamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    raw_path = out_dir / f"{stamp}_mexc_raw.jsonl"
    feature_path = (
        out_dir / f"{stamp}_mexc_features.jsonl"
    )
    deadline = (
        None
        if args.duration_seconds == 0
        else time.monotonic() + args.duration_seconds
    )

    engine = FeatureEngine(
        symbols,
        trade_window_ms=int(
            args.trade_window_seconds * 1000
        ),
        imbalance_levels=args.imbalance_levels,
    )

    with (
        AppendOnlyJsonl(raw_path) as raw_writer,
        AppendOnlyJsonl(feature_path) as feature_writer,
    ):
        raw_writer.write(
            {
                "record_type": "session",
                "schema_version": 2,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "source": "mexc_futures_public",
                "started_at_ns": time.time_ns(),
                "symbols": list(symbols),
                "venue_symbol_aliases": {
                    logical: native
                    for logical, native in venue_symbols.items()
                    if logical != native
                },
                "rest_base": args.rest_base,
                "ws_url": args.ws_url,
                "snapshot_limit": args.snapshot_limit,
                "snapshot_max_attempts": args.snapshot_max_attempts,
                "snapshot_failure_policy": args.snapshot_failure_policy,
                "depth_subscription_compress": False,
                "depth_level_schema": (
                    "price_contract_volume_order_count"
                ),
                "trade_m_field": (
                    "preserved_as_exchange_m_flag"
                ),
                "credentials_used": False,
                "live_order_transmission": False,
            }
        )

        reconnects = 0
        unavailable_symbols: set[str] = set()
        while (
            deadline is None
            or time.monotonic() < deadline
        ):
            try:
                unavailable_symbols = await _run_connection(
                    engine,
                    raw_writer,
                    feature_writer,
                    ws_url=args.ws_url,
                    rest_base=args.rest_base,
                    symbols=symbols,
                    venue_symbols=venue_symbols,
                    snapshot_limit=args.snapshot_limit,
                    snapshot_max_attempts=args.snapshot_max_attempts,
                    snapshot_failure_policy=args.snapshot_failure_policy,
                    deadline=deadline,
                )
                break
            except MexcOrderFlowError:
                raise
            except (
                ConnectionError,
                OSError,
                TimeoutError,
            ) as exc:
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
                    raise RuntimeError(
                        "MEXC websocket reconnect limit exceeded"
                    ) from exc
                await asyncio.sleep(
                    min(
                        2 ** min(reconnects, 4),
                        15,
                    )
                )

        raw_writer.write(
            {
                "record_type": "session_summary",
                "schema_version": 2,
                "ended_at_ns": time.time_ns(),
                "depth_stats": engine.depth_stats_snapshot(),
                "reconnects": reconnects,
                "snapshot_unavailable_symbols": sorted(unavailable_symbols),
            }
        )
        feature_writer.write(
            {
                "record_type": "session_summary",
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "ended_at_ns": time.time_ns(),
                "depth_stats": engine.depth_stats_snapshot(),
                "reconnects": reconnects,
            }
        )
    return raw_path, feature_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Record public MEXC Futures trades and incremental "
            "L2 depth without trading credentials."
        )
    )
    parser.add_argument(
        "--symbol",
        action="append",
        default=[],
        help="Futures symbol; repeat for multiple symbols",
    )
    parser.add_argument(
        "--symbol-alias",
        action="append",
        default=[],
        help="Venue transport alias in LOGICAL=NATIVE form; repeat as needed",
    )
    parser.add_argument(
        "--output-dir",
        default="data/mexc_orderflow",
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=0,
        help="0 records until interrupted",
    )
    parser.add_argument(
        "--rest-base",
        default=DEFAULT_REST_BASE,
    )
    parser.add_argument(
        "--ws-url",
        default=DEFAULT_WS_URL,
    )
    parser.add_argument(
        "--snapshot-limit",
        type=int,
        default=1000,
    )
    parser.add_argument(
        "--snapshot-max-attempts",
        type=int,
        default=3,
        help="Strict REST depth snapshot retry budget per bootstrap/recovery",
    )
    parser.add_argument(
        "--snapshot-failure-policy",
        choices=("fail", "continue"),
        default="fail",
        help=(
            "fail aborts after exhausted strict snapshot validation; continue "
            "marks that symbol unavailable while preserving strict validation"
        ),
    )
    parser.add_argument(
        "--trade-window-seconds",
        type=float,
        default=10.0,
    )
    parser.add_argument(
        "--imbalance-levels",
        type=int,
        default=10,
    )
    parser.add_argument(
        "--max-reconnects",
        type=int,
        default=20,
    )
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
    except (
        ValueError,
        RuntimeError,
        MexcOrderFlowError,
    ) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "raw": str(raw_path),
                "features": str(feature_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
