"""Zero-cost multi-agent trading-decision trial.

This module is intentionally isolated from production execution. Agents consume one
immutable point-in-time snapshot and may only return structured assessments. The
coordinator can emit PASS/REJECT/PENDING, but never transmits an order.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class MarketSnapshot:
    snapshot_id: str
    event_time: str
    symbol: str
    price: float
    spread_bps: float
    volume_z: float
    orderflow_imbalance: float
    htf_15m_bias: int
    htf_1h_bias: int
    btc_shock: float
    expected_r_after_costs: float
    stop_distance_pct: float
    equity: float
    risk_fraction: float = 0.005

    def validate(self) -> None:
        if not self.snapshot_id or not self.symbol:
            raise ValueError("snapshot_id and symbol are required")
        ts = datetime.fromisoformat(self.event_time.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            raise ValueError("event_time must be timezone-aware")
        if self.price <= 0 or self.equity <= 0:
            raise ValueError("price and equity must be positive")
        if self.spread_bps < 0 or self.stop_distance_pct <= 0:
            raise ValueError("spread_bps must be non-negative and stop_distance_pct positive")
        if not 0 < self.risk_fraction <= 0.02:
            raise ValueError("risk_fraction must be in (0, 0.02]")
        if self.htf_15m_bias not in (-1, 0, 1) or self.htf_1h_bias not in (-1, 0, 1):
            raise ValueError("HTF biases must be -1, 0, or 1")


@dataclass(frozen=True)
class AgentDecision:
    agent: str
    verdict: str  # PASS, VETO, ABSTAIN
    score: float
    reason: str
    hard_veto: bool = False
    metadata: dict | None = None


class Agent(Protocol):
    name: str

    def evaluate(self, snapshot: MarketSnapshot) -> AgentDecision: ...


class ProbeAgent:
    name = "PROBE"

    def evaluate(self, s: MarketSnapshot) -> AgentDecision:
        strength = 0.55 * min(max(s.volume_z / 3.0, -1.0), 1.0) + 0.45 * min(max(s.orderflow_imbalance, -1.0), 1.0)
        if strength < 0.15:
            return AgentDecision(self.name, "VETO", strength, "insufficient early volume/order-flow confirmation")
        return AgentDecision(self.name, "PASS", strength, "volume/order-flow confirmation present")


class RegimeAgent:
    name = "PRISM"

    def evaluate(self, s: MarketSnapshot) -> AgentDecision:
        if s.spread_bps > 20:
            return AgentDecision(self.name, "VETO", -1.0, "spread exceeds trial liquidity limit", hard_veto=True)
        alignment = (s.htf_15m_bias + s.htf_1h_bias) / 2.0
        if alignment <= 0:
            return AgentDecision(self.name, "VETO", alignment, "higher-timeframe regime is not bullish-aligned")
        return AgentDecision(self.name, "PASS", alignment, "higher-timeframe regime aligned")


class RiskAgent:
    name = "SCALE"

    def evaluate(self, s: MarketSnapshot) -> AgentDecision:
        risk_cash = s.equity * s.risk_fraction
        stop_cash_per_unit = s.price * s.stop_distance_pct
        units = risk_cash / stop_cash_per_unit
        if units <= 0:
            return AgentDecision(self.name, "VETO", -1.0, "position size is non-positive", hard_veto=True)
        return AgentDecision(
            self.name,
            "PASS",
            1.0,
            "deterministic risk size computed",
            metadata={"risk_cash": round(risk_cash, 8), "units": round(units, 8)},
        )


class LimitAgent:
    name = "LIMIT"

    def evaluate(self, s: MarketSnapshot) -> AgentDecision:
        if s.expected_r_after_costs <= 0:
            return AgentDecision(self.name, "VETO", s.expected_r_after_costs, "non-positive expected R after costs", hard_veto=True)
        if s.stop_distance_pct > 0.03:
            return AgentDecision(self.name, "VETO", -1.0, "stop distance exceeds trial limit", hard_veto=True)
        return AgentDecision(self.name, "PASS", min(s.expected_r_after_costs, 1.0), "risk/expectancy constraints satisfied")


class SkepticAgent:
    name = "EINSTEIN"

    def evaluate(self, s: MarketSnapshot) -> AgentDecision:
        if s.btc_shock <= -0.012:
            return AgentDecision(self.name, "VETO", -1.0, "adverse BTC shock", hard_veto=True)
        if abs(s.orderflow_imbalance) < 0.05:
            return AgentDecision(self.name, "VETO", -0.25, "weak order-flow evidence")
        return AgentDecision(self.name, "PASS", 0.5, "no independent veto condition triggered")


@dataclass(frozen=True)
class TrialResult:
    snapshot_id: str
    snapshot_sha256: str
    final_verdict: str
    decisions: tuple[AgentDecision, ...]
    created_at_utc: str


class TrialCoordinator:
    """Runs independent agents and applies fail-closed aggregation."""

    def __init__(self, agents: tuple[Agent, ...] | None = None):
        self.agents = agents or (ProbeAgent(), RegimeAgent(), RiskAgent(), LimitAgent(), SkepticAgent())

    @staticmethod
    def _fingerprint(snapshot: MarketSnapshot) -> str:
        payload = json.dumps(asdict(snapshot), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()

    def evaluate(self, snapshot: MarketSnapshot) -> TrialResult:
        snapshot.validate()
        decisions = tuple(agent.evaluate(snapshot) for agent in self.agents)
        if any(d.hard_veto and d.verdict == "VETO" for d in decisions):
            verdict = "REJECT"
        elif any(d.verdict == "VETO" for d in decisions):
            verdict = "REJECT"
        elif any(d.verdict == "ABSTAIN" for d in decisions):
            verdict = "PENDING"
        else:
            verdict = "PASS"
        return TrialResult(
            snapshot_id=snapshot.snapshot_id,
            snapshot_sha256=self._fingerprint(snapshot),
            final_verdict=verdict,
            decisions=decisions,
            created_at_utc=datetime.now(timezone.utc).isoformat(),
        )


def append_ledger(path: str | Path, snapshot: MarketSnapshot, result: TrialResult) -> None:
    """Append a reproducible decision record; does not contain credentials or order APIs."""
    record = {
        "snapshot": asdict(snapshot),
        "result": {
            "snapshot_id": result.snapshot_id,
            "snapshot_sha256": result.snapshot_sha256,
            "final_verdict": result.final_verdict,
            "decisions": [asdict(item) for item in result.decisions],
            "created_at_utc": result.created_at_utc,
        },
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
