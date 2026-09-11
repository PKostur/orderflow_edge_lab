from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


class CaptureAuditError(ValueError):
    """Raised when a capture or manifest cannot be validated safely."""


@dataclass(frozen=True)
class SymbolCaptureStats:
    symbol: str
    snapshots: int
    depth_messages: int
    depth_applied: int
    depth_stale: int
    depth_gaps: int
    recovery_commit_fetches: int
    trades: int
    crossed_books: int
    first_received_at_ns: int | None
    last_received_at_ns: int | None

    @property
    def duration_seconds(self) -> float:
        if self.first_received_at_ns is None or self.last_received_at_ns is None:
            return 0.0
        return max(0.0, (self.last_received_at_ns - self.first_received_at_ns) / 1_000_000_000)

    @property
    def depth_apply_fraction(self) -> float:
        return self.depth_applied / self.depth_messages if self.depth_messages else 0.0

    @property
    def gap_rate_per_minute(self) -> float:
        seconds = self.duration_seconds
        return self.depth_gaps / (seconds / 60.0) if seconds > 0 else 0.0


@dataclass(frozen=True)
class CaptureAuditPolicy:
    min_duration_seconds: float = 60.0
    min_trades_per_symbol: int = 1
    max_crossed_books: int = 0
    min_depth_apply_fraction: float = 0.95
    max_gap_rate_per_minute: float = 1.0


@dataclass(frozen=True)
class CaptureAuditReport:
    schema_version: int
    raw_sha256: str
    features_sha256: str
    raw_manifest_valid: bool
    features_manifest_valid: bool
    symbols: tuple[SymbolCaptureStats, ...]
    passed: bool
    failures: tuple[str, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for row in data["symbols"]:
            symbol = next(item for item in self.symbols if item.symbol == row["symbol"])
            row["duration_seconds"] = symbol.duration_seconds
            row["depth_apply_fraction"] = symbol.depth_apply_fraction
            row["gap_rate_per_minute"] = symbol.gap_rate_per_minute
        return data


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureAuditError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, Mapping):
        raise CaptureAuditError(f"JSON object required: {path}")
    return value


def validate_manifest(path: Path, manifest_path: Path) -> tuple[bool, str]:
    manifest = _load_json(manifest_path)
    digest = _sha256(path)
    size = path.stat().st_size
    valid = (
        manifest.get("schema_version") == 1
        and manifest.get("sha256") == digest
        and manifest.get("bytes") == size
        and manifest.get("path") == path.name
    )
    return valid, digest


def audit_capture(
    raw_path: str | Path,
    features_path: str | Path,
    *,
    policy: CaptureAuditPolicy | None = None,
) -> CaptureAuditReport:
    policy = policy or CaptureAuditPolicy()
    raw = Path(raw_path)
    features = Path(features_path)
    raw_manifest = raw.with_name(raw.name + ".manifest.json")
    features_manifest = features.with_name(features.name + ".manifest.json")
    for path in (raw, features, raw_manifest, features_manifest):
        if not path.is_file():
            raise CaptureAuditError(f"required capture file is missing: {path}")

    raw_manifest_valid, raw_sha = validate_manifest(raw, raw_manifest)
    features_manifest_valid, features_sha = validate_manifest(features, features_manifest)

    counters: dict[str, Counter[str]] = defaultdict(Counter)
    first_seen: dict[str, int] = {}
    last_seen: dict[str, int] = {}

    def observe(symbol: str, received: object) -> None:
        if not symbol or type(received) is not int:
            return
        first_seen[symbol] = min(first_seen.get(symbol, received), received)
        last_seen[symbol] = max(last_seen.get(symbol, received), received)

    try:
        with raw.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                obj = json.loads(line)
                if not isinstance(obj, Mapping):
                    raise CaptureAuditError(f"raw line {line_number} is not an object")
                symbol = str(obj.get("symbol") or "")
                record_type = obj.get("record_type")
                observe(symbol, obj.get("received_at_ns"))
                if symbol:
                    if record_type == "rest_snapshot":
                        counters[symbol]["snapshots"] += 1
                    elif record_type == "depth_gap":
                        counters[symbol]["depth_gaps"] += 1
                    elif record_type == "rest_depth_commits":
                        counters[symbol]["recovery_commit_fetches"] += 1
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureAuditError("raw capture is not valid JSONL") from exc

    try:
        with features.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                obj = json.loads(line)
                if not isinstance(obj, Mapping):
                    raise CaptureAuditError(f"feature line {line_number} is not an object")
                symbol = str(obj.get("symbol") or "")
                if not symbol:
                    continue
                observe(symbol, obj.get("received_at_ns"))
                event_type = obj.get("event_type")
                if event_type == "depth":
                    counters[symbol]["depth_messages"] += 1
                    if obj.get("depth_applied") is True:
                        counters[symbol]["depth_applied"] += 1
                    else:
                        counters[symbol]["depth_stale"] += 1
                elif event_type == "trade":
                    counters[symbol]["trades"] += 1
                bid = obj.get("best_bid")
                ask = obj.get("best_ask")
                if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and bid >= ask:
                    counters[symbol]["crossed_books"] += 1
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureAuditError("feature capture is not valid JSONL") from exc

    symbols = tuple(
        SymbolCaptureStats(
            symbol=symbol,
            snapshots=counters[symbol]["snapshots"],
            depth_messages=counters[symbol]["depth_messages"],
            depth_applied=counters[symbol]["depth_applied"],
            depth_stale=counters[symbol]["depth_stale"],
            depth_gaps=counters[symbol]["depth_gaps"],
            recovery_commit_fetches=counters[symbol]["recovery_commit_fetches"],
            trades=counters[symbol]["trades"],
            crossed_books=counters[symbol]["crossed_books"],
            first_received_at_ns=first_seen.get(symbol),
            last_received_at_ns=last_seen.get(symbol),
        )
        for symbol in sorted(counters)
    )

    failures: list[str] = []
    if not raw_manifest_valid:
        failures.append("raw_manifest_invalid")
    if not features_manifest_valid:
        failures.append("features_manifest_invalid")
    if not symbols:
        failures.append("no_symbols")
    for row in symbols:
        if row.duration_seconds < policy.min_duration_seconds:
            failures.append(f"{row.symbol}:capture_too_short")
        if row.trades < policy.min_trades_per_symbol:
            failures.append(f"{row.symbol}:insufficient_trades")
        if row.crossed_books > policy.max_crossed_books:
            failures.append(f"{row.symbol}:crossed_books")
        if row.depth_messages == 0 or row.depth_apply_fraction < policy.min_depth_apply_fraction:
            failures.append(f"{row.symbol}:low_depth_apply_fraction")
        if row.gap_rate_per_minute > policy.max_gap_rate_per_minute:
            failures.append(f"{row.symbol}:excessive_depth_gap_rate")
        if row.recovery_commit_fetches != row.depth_gaps:
            failures.append(f"{row.symbol}:gap_recovery_accounting_mismatch")

    return CaptureAuditReport(
        schema_version=1,
        raw_sha256=raw_sha,
        features_sha256=features_sha,
        raw_manifest_valid=raw_manifest_valid,
        features_manifest_valid=features_manifest_valid,
        symbols=symbols,
        passed=not failures,
        failures=tuple(failures),
        limitations=(
            "A passing capture audit establishes transport/data-integrity evidence only, not a trading edge.",
            "Price-level depth is aggregated L2/MBP-style data, not individual-order MBO.",
            "Short captures cannot establish stable distributional behavior or out-of-sample performance.",
        ),
    )
