from __future__ import annotations

from datetime import datetime
from typing import Any

from orderflow_edge_lab.execution import (
    MarketSnapshot,
    PaperEngine,
    RejectedIntent,
    TradeIntent,
    _parse_dt,
)


class ApprovalBoundPaperEngine(PaperEngine):
    """Paper engine whose human approval is bound to the submitted size.

    The base engine intentionally revalidates market and risk conditions at approval.
    That revalidation can legitimately change the allowable contract count. A human
    approval should never silently authorize a different size, so this wrapper fails
    closed whenever the currently allowable size differs from the size recorded when
    the intent entered the approval queue.

    There is still no broker or network order transmission in this class.
    """

    def approve(
        self,
        intent_id: str,
        market: MarketSnapshot,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self._ensure_open()
        operation_time = self._operation_time(now)
        pending = self.state["pending"].get(intent_id)
        if pending is None:
            raise RejectedIntent("unknown_pending_intent")

        # Preserve the base engine's durable expiry behavior before doing any sizing
        # comparison. Calling super records intent_expired and removes the pending item.
        if operation_time.timestamp() >= float(pending["expires_at"]):
            return super().approve(intent_id, market, now=operation_time)

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
            raise RejectedIntent(
                f"approval_terms_changed:submitted_contracts={submitted_contracts},"
                f"currently_allowed={currently_allowed}"
            )

        return super().approve(intent_id, market, now=operation_time)
