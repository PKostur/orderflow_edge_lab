from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping


UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must be timezone aware")
    return dt.astimezone(UTC)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    tick_size: float
    tick_value: float
    max_contracts: int = 10

    def __post_init__(self) -> None:
        if self.tick_size <= 0 or self.tick_value <= 0 or self.max_contracts < 1:
            raise ValueError("invalid instrument specification")


DEFAULT_INSTRUMENTS: dict[str, InstrumentSpec] = {
    "NQ": InstrumentSpec("NQ", tick_size=0.25, tick_value=5.0, max_contracts=4),
    "MNQ": InstrumentSpec("MNQ", tick_size=0.25, tick_value=0.50, max_contracts=20),
}


@dataclass(frozen=True)
class RiskPolicy:
    risk_fraction: float = 0.005
    max_daily_loss_fraction: float = 0.02
    max_trades_per_day: int = 4
    max_open_positions: int = 1
    max_spread_ticks: float = 4.0
    min_reward_risk: float = 1.5
    max_signal_age_seconds: float = 10.0
    max_market_age_seconds: float = 3.0
    approval_ttl_seconds: float = 120.0
    slippage_ticks: float = 1.0
    commission_per_contract_per_side: float = 0.0

    def __post_init__(self) -> None:
        if not 0 < self.risk_fraction <= 0.05:
            raise ValueError("risk_fraction must be in (0, 0.05]")
        if not 0 < self.max_daily_loss_fraction <= 0.20:
            raise ValueError("max_daily_loss_fraction must be in (0, 0.20]")
        for name in ("max_trades_per_day", "max_open_positions"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
        for name in (
            "max_spread_ticks",
            "min_reward_risk",
            "max_signal_age_seconds",
            "max_market_age_seconds",
            "approval_ttl_seconds",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.slippage_ticks < 0 or self.commission_per_contract_per_side < 0:
            raise ValueError("cost assumptions cannot be negative")


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    bid: float
    ask: float
    timestamp: datetime

    def __post_init__(self) -> None:
        if self.bid <= 0 or self.ask <= 0 or self.bid > self.ask:
            raise ValueError("invalid market snapshot")
        if self.timestamp.tzinfo is None:
            raise ValueError("market timestamp must be timezone aware")


@dataclass(frozen=True)
class TradeIntent:
    strategy_id: str
    symbol: str
    side: str
    entry_reference: float
    stop: float
    target: float
    signal_time: datetime

    def __post_init__(self) -> None:
        side = self.side.upper()
        object.__setattr__(self, "side", side)
        if side not in {"LONG", "SHORT"}:
            raise ValueError("side must be LONG or SHORT")
        if self.signal_time.tzinfo is None:
            raise ValueError("signal_time must be timezone aware")
        if min(self.entry_reference, self.stop, self.target) <= 0:
            raise ValueError("prices must be positive")
        if side == "LONG" and not (self.stop < self.entry_reference < self.target):
            raise ValueError("LONG requires stop < entry < target")
        if side == "SHORT" and not (self.target < self.entry_reference < self.stop):
            raise ValueError("SHORT requires target < entry < stop")

    @property
    def intent_id(self) -> str:
        payload = {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "side": self.side,
            "entry_reference": round(self.entry_reference, 10),
            "stop": round(self.stop, 10),
            "target": round(self.target, 10),
            "signal_time": self.signal_time.astimezone(UTC).isoformat(),
        }
        return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:24]


class StateCorruptionError(RuntimeError):
    pass


class EngineLockError(RuntimeError):
    pass


class RejectedIntent(RuntimeError):
    pass


class HashChainJournal:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._last_hash = self.verify(self.path)

    @staticmethod
    def verify(path: str | Path) -> str:
        path = Path(path)
        if not path.exists():
            return "GENESIS"
        previous = "GENESIS"
        with path.open("r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, start=1):
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise StateCorruptionError(f"journal line {lineno} is invalid JSON") from exc
                supplied = item.pop("hash", None)
                if item.get("prev_hash") != previous:
                    raise StateCorruptionError(f"journal chain broken at line {lineno}")
                calculated = hashlib.sha256(_canonical(item).encode("utf-8")).hexdigest()
                if supplied != calculated:
                    raise StateCorruptionError(f"journal hash mismatch at line {lineno}")
                previous = supplied
        return previous

    def append(self, event_type: str, payload: Mapping[str, Any], when: datetime) -> str:
        item = {
            "event_type": event_type,
            "timestamp": when.astimezone(UTC).isoformat(),
            "payload": payload,
            "prev_hash": self._last_hash,
        }
        item["hash"] = hashlib.sha256(_canonical(item).encode("utf-8")).hexdigest()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical(item) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._last_hash = item["hash"]
        return item["hash"]


class _EngineLock:
    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise EngineLockError(f"execution state already owned: {self.path}") from exc
        os.write(self.fd, str(os.getpid()).encode("ascii"))
        os.fsync(self.fd)

    def release(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class PaperEngine:
    """Approval-gated paper execution.

    There is intentionally no broker/network order method in this class.
    """

    STATE_VERSION = 1

    def __init__(
        self,
        state_path: str | Path,
        journal_path: str | Path,
        *,
        starting_equity: float = 10_000.0,
        policy: RiskPolicy = RiskPolicy(),
        instruments: Mapping[str, InstrumentSpec] = DEFAULT_INSTRUMENTS,
    ):
        if starting_equity <= 0:
            raise ValueError("starting_equity must be positive")
        self.state_path = Path(state_path)
        self.lock = _EngineLock(self.state_path.with_suffix(self.state_path.suffix + ".lock"))
        self.lock.acquire()
        try:
            self.journal = HashChainJournal(journal_path)
            self.policy = policy
            self.instruments = dict(instruments)
            self.state = self._load_or_create(starting_equity)
        except Exception:
            self.lock.release()
            raise

    def close(self) -> None:
        self.lock.release()

    def __enter__(self) -> "PaperEngine":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _load_or_create(self, starting_equity: float) -> dict[str, Any]:
        if not self.state_path.exists():
            day = _now().date().isoformat()
            state = {
                "version": self.STATE_VERSION,
                "equity": float(starting_equity),
                "day_start_equity": float(starting_equity),
                "realized_pnl_today": 0.0,
                "trading_day": day,
                "trades_today": 0,
                "kill_switch": False,
                "pending": {},
                "positions": {},
                "seen_intents": [],
            }
            self._write_state(state)
            return state
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise StateCorruptionError("execution state cannot be parsed; refusing reset") from exc
        required = {
            "version", "equity", "day_start_equity", "realized_pnl_today",
            "trading_day", "trades_today", "kill_switch", "pending",
            "positions", "seen_intents",
        }
        if not required <= set(state):
            raise StateCorruptionError("execution state is missing required fields")
        if state["version"] != self.STATE_VERSION:
            raise StateCorruptionError("unsupported execution state version")
        return state

    def _write_state(self, state: Mapping[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".partial")
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(state, sort_keys=True, indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.state_path)
        if os.name == "posix":
            dir_fd = os.open(self.state_path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)

    def _roll_day(self, now: datetime) -> None:
        day = now.astimezone(UTC).date().isoformat()
        if day != self.state["trading_day"]:
            self.state["trading_day"] = day
            self.state["day_start_equity"] = self.state["equity"]
            self.state["realized_pnl_today"] = 0.0
            self.state["trades_today"] = 0
            self._write_state(self.state)

    def _validate(
        self,
        intent: TradeIntent,
        market: MarketSnapshot,
        now: datetime,
        *,
        allow_seen: bool = False,
    ) -> tuple[InstrumentSpec, int]:
        now = _parse_dt(now)
        self._roll_day(now)
        if self.state["kill_switch"]:
            raise RejectedIntent("kill_switch")
        if intent.symbol not in self.instruments:
            raise RejectedIntent("unknown_instrument")
        spec = self.instruments[intent.symbol]
        if market.symbol != intent.symbol:
            raise RejectedIntent("snapshot_symbol_mismatch")
        if not allow_seen and intent.intent_id in self.state["seen_intents"]:
            raise RejectedIntent("duplicate_intent")
        signal_age = (now - intent.signal_time.astimezone(UTC)).total_seconds()
        market_age = (now - market.timestamp.astimezone(UTC)).total_seconds()
        if signal_age < 0 or signal_age > self.policy.max_signal_age_seconds:
            raise RejectedIntent("stale_signal")
        if market_age < 0 or market_age > self.policy.max_market_age_seconds:
            raise RejectedIntent("stale_market")
        spread_ticks = (market.ask - market.bid) / spec.tick_size
        if spread_ticks > self.policy.max_spread_ticks:
            raise RejectedIntent("spread")
        risk_points = abs(intent.entry_reference - intent.stop)
        reward_points = abs(intent.target - intent.entry_reference)
        if risk_points < spec.tick_size:
            raise RejectedIntent("stop_too_close")
        if reward_points / risk_points < self.policy.min_reward_risk:
            raise RejectedIntent("reward_risk")
        if self.state["trades_today"] >= self.policy.max_trades_per_day:
            raise RejectedIntent("daily_trade_limit")
        if len(self.state["positions"]) >= self.policy.max_open_positions:
            raise RejectedIntent("position_limit")
        max_loss = self.state["day_start_equity"] * self.policy.max_daily_loss_fraction
        if self.state["realized_pnl_today"] <= -max_loss:
            raise RejectedIntent("daily_loss_limit")
        risk_per_contract = risk_points / spec.tick_size * spec.tick_value
        risk_budget = self.state["equity"] * self.policy.risk_fraction
        contracts = min(spec.max_contracts, int(math.floor(risk_budget / risk_per_contract)))
        if contracts < 1:
            raise RejectedIntent("risk_budget_too_small")
        return spec, contracts

    def submit(
        self,
        intent: TradeIntent,
        market: MarketSnapshot,
        *,
        now: datetime | None = None,
    ) -> str:
        now = _parse_dt(now or _now())
        _, contracts = self._validate(intent, market, now)
        intent_id = intent.intent_id
        expires = now.timestamp() + self.policy.approval_ttl_seconds
        pending = {
            "intent": {
                **asdict(intent),
                "signal_time": intent.signal_time.astimezone(UTC).isoformat(),
            },
            "submitted_at": now.isoformat(),
            "expires_at": expires,
            "contracts": contracts,
        }
        self.state["pending"][intent_id] = pending
        self.state["seen_intents"].append(intent_id)
        self.state["seen_intents"] = self.state["seen_intents"][-5000:]
        self._write_state(self.state)
        self.journal.append("intent_submitted", {"intent_id": intent_id, "contracts": contracts}, now)
        return intent_id

    def approve(
        self,
        intent_id: str,
        market: MarketSnapshot,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = _parse_dt(now or _now())
        pending = self.state["pending"].get(intent_id)
        if pending is None:
            raise RejectedIntent("unknown_pending_intent")
        if now.timestamp() > float(pending["expires_at"]):
            self.state["pending"].pop(intent_id, None)
            self._write_state(self.state)
            self.journal.append("intent_expired", {"intent_id": intent_id}, now)
            raise RejectedIntent("approval_expired")

        raw = pending["intent"]
        intent = TradeIntent(
            strategy_id=raw["strategy_id"],
            symbol=raw["symbol"],
            side=raw["side"],
            entry_reference=float(raw["entry_reference"]),
            stop=float(raw["stop"]),
            target=float(raw["target"]),
            signal_time=_parse_dt(raw["signal_time"]),
        )
        spec, contracts = self._validate(intent, market, now, allow_seen=True)
        if intent.side == "LONG":
            fill = market.ask + self.policy.slippage_ticks * spec.tick_size
        else:
            fill = market.bid - self.policy.slippage_ticks * spec.tick_size
        position = {
            "intent_id": intent_id,
            "strategy_id": intent.strategy_id,
            "symbol": intent.symbol,
            "side": intent.side,
            "contracts": contracts,
            "entry_fill": fill,
            "stop": intent.stop,
            "target": intent.target,
            "opened_at": now.isoformat(),
        }
        self.state["pending"].pop(intent_id, None)
        self.state["positions"][intent_id] = position
        self.state["trades_today"] += 1
        self._write_state(self.state)
        self.journal.append("paper_position_opened", position, now)
        return position

    def close_position(
        self,
        intent_id: str,
        market: MarketSnapshot,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = _parse_dt(now or _now())
        position = self.state["positions"].get(intent_id)
        if position is None:
            raise RejectedIntent("unknown_position")
        spec = self.instruments[position["symbol"]]
        if market.symbol != position["symbol"]:
            raise RejectedIntent("snapshot_symbol_mismatch")
        if position["side"] == "LONG":
            exit_fill = market.bid - self.policy.slippage_ticks * spec.tick_size
            signed_points = exit_fill - position["entry_fill"]
        else:
            exit_fill = market.ask + self.policy.slippage_ticks * spec.tick_size
            signed_points = position["entry_fill"] - exit_fill
        gross = signed_points / spec.tick_size * spec.tick_value * position["contracts"]
        commissions = 2 * self.policy.commission_per_contract_per_side * position["contracts"]
        pnl = gross - commissions
        result = {
            **position,
            "exit_fill": exit_fill,
            "closed_at": now.isoformat(),
            "reason": reason,
            "gross_pnl": gross,
            "commissions": commissions,
            "net_pnl": pnl,
        }
        self.state["positions"].pop(intent_id, None)
        self.state["equity"] += pnl
        self.state["realized_pnl_today"] += pnl
        self._write_state(self.state)
        self.journal.append("paper_position_closed", result, now)
        return result

    def engage_kill_switch(
        self,
        snapshots: Mapping[str, MarketSnapshot] | None = None,
        *,
        flatten: bool = False,
        now: datetime | None = None,
    ) -> None:
        now = _parse_dt(now or _now())
        self.state["kill_switch"] = True
        self._write_state(self.state)
        self.journal.append("kill_switch_engaged", {"flatten": flatten}, now)
        if flatten:
            snapshots = dict(snapshots or {})
            for intent_id, position in list(self.state["positions"].items()):
                snapshot = snapshots.get(position["symbol"])
                if snapshot is None:
                    raise RejectedIntent("missing_flatten_snapshot")
                self.close_position(intent_id, snapshot, reason="kill_switch", now=now)

    def release_kill_switch(self, *, now: datetime | None = None) -> None:
        now = _parse_dt(now or _now())
        self.state["kill_switch"] = False
        self._write_state(self.state)
        self.journal.append("kill_switch_released", {}, now)
