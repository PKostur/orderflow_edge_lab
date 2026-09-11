from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
from typing import Any, Mapping

from orderflow_edge_lab.execution import (
    MarketSnapshot,
    PaperEngine,
    RejectedIntent,
    TradeIntent,
    _canonical,
    _parse_dt,
)


def _market_payload(market: MarketSnapshot) -> dict[str, Any]:
    return {
        "symbol": market.symbol,
        "bid": market.bid,
        "ask": market.ask,
        "timestamp": market.timestamp.isoformat(),
    }


def _sha256_payload(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


class ApprovalBoundPaperEngine(PaperEngine):
    """Paper engine with human approval bound to the submitted proposal.

    The base engine revalidates market and risk conditions at approval. This wrapper
    additionally binds the operator-visible proposal to the exact intent, submitted
    contract count, expiry, source-evidence digest, persisted engine configuration,
    and submission market snapshot. Approval requires the resulting integrity token.

    The token is not a secret or authentication credential. It is an audit/integrity
    handle that prevents an approval command from silently referring to a different
    proposal than the one created at submission.

    Market movement may still occur between submission and approval. Revalidation is
    therefore performed at approval and fails closed whenever the currently allowable
    contract count differs from the submitted count.

    There is still no broker or network order transmission in this class.
    """

    def submit(
        self,
        intent: TradeIntent,
        market: MarketSnapshot,
        *,
        now: datetime | None = None,
        evidence: Mapping[str, Any] | None = None,
    ) -> str:
        # Canonicalize before changing durable state so invalid/non-JSON evidence
        # cannot create a half-bound approval proposal.
        evidence_payload = dict(evidence) if evidence is not None else None
        evidence_sha256 = _sha256_payload(evidence_payload)
        intent_id = super().submit(intent, market, now=now, evidence=evidence_payload)
        pending = self.state["pending"][intent_id]
        binding = {
            "intent_id": intent_id,
            "intent": deepcopy(pending["intent"]),
            "contracts": int(pending["contracts"]),
            "submitted_at": pending["submitted_at"],
            "expires_at": float(pending["expires_at"]),
            "submitted_market": _market_payload(market),
            "evidence_sha256": evidence_sha256,
            "engine_config_sha256": _sha256_payload(self.state["engine_config"]),
        }
        token = _sha256_payload(binding)
        pending["approval_binding"] = binding
        pending["approval_token"] = token
        operation_time = _parse_dt(pending["submitted_at"])
        self._commit(
            "approval_bound",
            {
                "intent_id": intent_id,
                "approval_token": token,
                "evidence_sha256": evidence_sha256,
                "engine_config_sha256": binding["engine_config_sha256"],
            },
            operation_time,
        )
        return intent_id

    def _validated_binding(self, intent_id: str) -> tuple[dict[str, Any], str]:
        """Return a binding only when every field still matches the active proposal.

        Hashing the binding alone is not sufficient because approval execution reads
        fields from ``pending``. A corrupted pending proposal could otherwise diverge
        from an internally self-consistent binding. This check makes that divergence
        fail closed before sizing or execution is considered.
        """
        self._ensure_open()
        pending = self.state["pending"].get(intent_id)
        if pending is None:
            raise RejectedIntent("unknown_pending_intent")
        token = pending.get("approval_token")
        binding = pending.get("approval_binding")
        if not _is_sha256(token) or not isinstance(binding, dict):
            raise RejectedIntent("approval_binding_missing")
        if _sha256_payload(binding) != token:
            raise RejectedIntent("approval_binding_corrupt")

        try:
            if binding.get("intent_id") != intent_id:
                raise ValueError("intent_id")
            if binding.get("intent") != pending["intent"]:
                raise ValueError("intent")
            if binding.get("contracts") != pending["contracts"]:
                raise ValueError("contracts")
            if binding.get("submitted_at") != pending["submitted_at"]:
                raise ValueError("submitted_at")
            if binding.get("expires_at") != pending["expires_at"]:
                raise ValueError("expires_at")
            if not _is_sha256(binding.get("evidence_sha256")):
                raise ValueError("evidence_sha256")
            expected_config_sha = _sha256_payload(self.state["engine_config"])
            if binding.get("engine_config_sha256") != expected_config_sha:
                raise ValueError("engine_config_sha256")

            market = binding.get("submitted_market")
            if not isinstance(market, dict) or set(market) != {"symbol", "bid", "ask", "timestamp"}:
                raise ValueError("submitted_market")
            submitted_market = MarketSnapshot(
                symbol=market["symbol"],
                bid=market["bid"],
                ask=market["ask"],
                timestamp=_parse_dt(market["timestamp"]),
            )
            if submitted_market.symbol != pending["intent"]["symbol"]:
                raise ValueError("submitted_market_symbol")
            if _parse_dt(binding["submitted_at"]).timestamp() >= float(binding["expires_at"]):
                raise ValueError("nonpositive_approval_ttl")
        except (KeyError, TypeError, ValueError) as exc:
            raise RejectedIntent("approval_binding_terms_mismatch") from exc

        return binding, token

    def approval_token_for(self, intent_id: str) -> str:
        _, token = self._validated_binding(intent_id)
        return token

    def approve(
        self,
        intent_id: str,
        market: MarketSnapshot,
        *,
        approval_token: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self._ensure_open()
        operation_time = self._operation_time(now)
        pending = self.state["pending"].get(intent_id)
        if pending is None:
            raise RejectedIntent("unknown_pending_intent")

        # Preserve durable expiry behavior before token or sizing checks. An expired
        # proposal cannot be revived by presenting a previously valid token.
        if operation_time.timestamp() >= float(pending["expires_at"]):
            return super().approve(intent_id, market, now=operation_time)

        _, expected_token = self._validated_binding(intent_id)
        if not isinstance(approval_token, str) or approval_token != expected_token:
            self._commit(
                "approval_token_rejected",
                {
                    "intent_id": intent_id,
                    "token_supplied": isinstance(approval_token, str),
                },
                operation_time,
            )
            raise RejectedIntent("approval_token_mismatch")

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
        _, currently_allowed = self._validate(intent, market, operation_time, allow_seen=True)
        submitted_contracts = int(pending["contracts"])
        if currently_allowed != submitted_contracts:
            self._commit(
                "approval_terms_changed",
                {
                    "intent_id": intent_id,
                    "submitted_contracts": submitted_contracts,
                    "currently_allowed": currently_allowed,
                    "approval_token": expected_token,
                    "market": _market_payload(market),
                },
                operation_time,
            )
            raise RejectedIntent(
                f"approval_terms_changed:submitted_contracts={submitted_contracts},"
                f"currently_allowed={currently_allowed}"
            )

        return super().approve(intent_id, market, now=operation_time)
