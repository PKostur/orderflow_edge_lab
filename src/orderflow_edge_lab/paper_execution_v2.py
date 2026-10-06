"""Opt-in v2 safeguards for the local approval-bound manual paper engine.

The legacy ``PaperEngine`` files and journal records remain untouched.  This
module wraps the approval-bound engine for a separately initialized (or
explicitly reconciled-flat migrated) successor run.  It remains paper only:
there is no broker, exchange, network, credential, or scheduling capability.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from orderflow_edge_lab.approval import ApprovalBoundPaperEngine, _market_payload, _sha256_payload
from orderflow_edge_lab.contracts_v2 import (
    ContractValidationError,
    build_file_identity,
    canonical_json_bytes,
    canonical_json_sha256,
    non_authority_claims,
)
from orderflow_edge_lab.execution import (
    HashChainJournal,
    InstrumentSpec,
    MarketSnapshot,
    RejectedIntent,
    StateCorruptionError,
    TradeIntent,
    _parse_dt,
    reconcile_execution,
    validate_execution_state,
)

UTC = timezone.utc
CONFIG_SCHEMA = "orderflow_edge_lab.paper_execution_configuration.v2"
METADATA_SCHEMA = "orderflow_edge_lab.paper_instrument_metadata.v2"
TERMS_POLICY_SCHEMA = "orderflow_edge_lab.approval_market_terms_policy.v2"
ANCHOR_SCHEMA = "orderflow_edge_lab.paper_reconciliation_anchor.v2"
_HEX = frozenset("0123456789abcdef")


class PaperExecutionV2Error(ValueError):
    """Raised for a v2 configuration/anchor/migration violation before use."""


def _sync_parent(path: Path) -> None:
    if os.name == "posix":
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PaperExecutionV2Error(f"cannot read {field}: {path}") from exc
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise PaperExecutionV2Error(f"{field} must be a JSON object")
    return value


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in _HEX for char in value.lower()):
        raise PaperExecutionV2Error(f"{field} must be a SHA-256")
    return value.lower()


def _timestamp(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise PaperExecutionV2Error(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PaperExecutionV2Error(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PaperExecutionV2Error(f"{field} must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decimal_text(value: object, field: str, *, positive: bool = False) -> str:
    # Strings avoid a binary-float modulus becoming the definition of a tick.
    if not isinstance(value, str) or not value.strip():
        raise PaperExecutionV2Error(f"{field} must be a nonempty decimal string")
    try:
        decimal = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise PaperExecutionV2Error(f"{field} must be decimal") from exc
    if not decimal.is_finite() or (positive and decimal <= 0):
        raise PaperExecutionV2Error(f"{field} must be finite" + (" and positive" if positive else ""))
    rendered = format(decimal, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _as_decimal(value: object, field: str) -> Decimal:
    # Runtime legacy objects expose floats; converting via str deliberately maps
    # their operator-visible decimal spelling, never their binary representation.
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise RejectedIntent(f"{field}_not_decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise RejectedIntent(f"{field}_not_decimal") from exc
    if not result.is_finite():
        raise RejectedIntent(f"{field}_not_finite")
    return result


def _normalise_metadata(raw: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], str]:
    if not isinstance(raw, Mapping) or not raw:
        raise PaperExecutionV2Error("instrument_metadata must be a nonempty object")
    normalized: dict[str, dict[str, Any]] = {}
    for symbol, value in raw.items():
        if not isinstance(symbol, str) or not symbol or not isinstance(value, Mapping):
            raise PaperExecutionV2Error("instrument metadata must map symbols to objects")
        expected = {"schema", "symbol", "tick_size", "tick_value", "max_contracts", "contract_increment", "min_contracts"}
        if set(value) != expected or value.get("schema") != METADATA_SCHEMA or value.get("symbol") != symbol:
            raise PaperExecutionV2Error(f"instrument metadata for {symbol} has unsupported shape")
        tick_size = _decimal_text(value["tick_size"], f"{symbol}.tick_size", positive=True)
        tick_value = _decimal_text(value["tick_value"], f"{symbol}.tick_value", positive=True)
        integer_values: dict[str, int] = {}
        for field in ("max_contracts", "contract_increment", "min_contracts"):
            candidate = value[field]
            if type(candidate) is not int or candidate < 1:
                raise PaperExecutionV2Error(f"{symbol}.{field} must be a positive integer")
            integer_values[field] = candidate
        if integer_values["min_contracts"] > integer_values["max_contracts"]:
            raise PaperExecutionV2Error(f"{symbol}.min_contracts exceeds max_contracts")
        if integer_values["max_contracts"] % integer_values["contract_increment"]:
            raise PaperExecutionV2Error(f"{symbol}.max_contracts must align to contract_increment")
        if integer_values["min_contracts"] % integer_values["contract_increment"]:
            raise PaperExecutionV2Error(f"{symbol}.min_contracts must align to contract_increment")
        normalized[symbol] = {
            "schema": METADATA_SCHEMA,
            "symbol": symbol,
            "tick_size": tick_size,
            "tick_value": tick_value,
            **integer_values,
        }
    normalized = dict(sorted(normalized.items()))
    return normalized, canonical_json_sha256(normalized)


def _normalise_terms_policy(raw: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    if not isinstance(raw, Mapping):
        raise PaperExecutionV2Error("terms_policy must be an object")
    expected = {"schema", "max_bid_move_ticks", "max_ask_move_ticks", "max_fill_move_ticks"}
    if set(raw) != expected or raw.get("schema") != TERMS_POLICY_SCHEMA:
        raise PaperExecutionV2Error("terms_policy has unsupported shape")
    result: dict[str, Any] = {"schema": TERMS_POLICY_SCHEMA}
    for field in ("max_bid_move_ticks", "max_ask_move_ticks", "max_fill_move_ticks"):
        value = raw[field]
        if type(value) is not int or value < 0:
            raise PaperExecutionV2Error(f"terms_policy.{field} must be a nonnegative integer")
        result[field] = value
    return result, canonical_json_sha256(result)


def validate_approval_terms_v2(terms: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the portable JSON shape of token-bound manual approval terms.

    The owning engine additionally verifies this record against its caller-frozen
    grid metadata and policy before any state mutation.
    """

    expected = {
        "schema", "symbol", "side", "bid", "ask", "modeled_fill", "contracts", "risk_ticks", "reward_ticks",
        "risk_per_contract", "reward_per_contract", "terms_policy_sha256", "instrument_metadata_sha256",
    }
    if not isinstance(terms, Mapping) or set(terms) != expected or terms.get("schema") != "orderflow_edge_lab.approval_market_terms.v2":
        raise PaperExecutionV2Error("approval terms have unsupported shape")
    if not isinstance(terms["symbol"], str) or not terms["symbol"]:
        raise PaperExecutionV2Error("approval terms symbol is invalid")
    if terms["side"] not in {"LONG", "SHORT"}:
        raise PaperExecutionV2Error("approval terms side is invalid")
    if type(terms["contracts"]) is not int or terms["contracts"] < 1:
        raise PaperExecutionV2Error("approval terms contracts are invalid")
    normalized: dict[str, Any] = {
        "schema": "orderflow_edge_lab.approval_market_terms.v2",
        "symbol": terms["symbol"],
        "side": terms["side"],
        "contracts": terms["contracts"],
        "terms_policy_sha256": _sha256(terms["terms_policy_sha256"], "approval terms policy hash"),
        "instrument_metadata_sha256": _sha256(terms["instrument_metadata_sha256"], "approval terms metadata hash"),
    }
    for field in ("bid", "ask", "modeled_fill", "risk_ticks", "reward_ticks", "risk_per_contract"):
        normalized[field] = _decimal_text(terms[field], f"approval terms {field}", positive=True)
    normalized["reward_per_contract"] = _decimal_text(terms["reward_per_contract"], "approval terms reward_per_contract")
    if Decimal(normalized["bid"]) > Decimal(normalized["ask"]):
        raise PaperExecutionV2Error("approval terms bid exceeds ask")
    return json.loads(canonical_json_bytes(normalized).decode("utf-8"))


def _legacy_instruments(metadata: Mapping[str, Mapping[str, Any]]) -> dict[str, InstrumentSpec]:
    return {
        symbol: InstrumentSpec(
            symbol=symbol,
            tick_size=float(str(spec["tick_size"])),
            tick_value=float(str(spec["tick_value"])),
            max_contracts=int(spec["max_contracts"]),
        )
        for symbol, spec in metadata.items()
    }


def _configuration_payload(
    metadata: Mapping[str, Mapping[str, Any]], metadata_sha256: str, terms_policy: Mapping[str, Any],
    terms_policy_sha256: str, migration: str,
) -> dict[str, Any]:
    unsigned = {
        "schema": CONFIG_SCHEMA,
        "instrument_metadata": metadata,
        "instrument_metadata_sha256": metadata_sha256,
        "terms_policy": terms_policy,
        "terms_policy_sha256": terms_policy_sha256,
        "migration": migration,
    }
    return {**unsigned, "configuration_sha256": canonical_json_sha256(unsigned)}


def _validate_configuration(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "schema", "instrument_metadata", "instrument_metadata_sha256", "terms_policy", "terms_policy_sha256", "migration",
        "configuration_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected or value.get("schema") != CONFIG_SCHEMA:
        raise PaperExecutionV2Error("v2 configuration has unsupported shape")
    metadata, metadata_hash = _normalise_metadata(value["instrument_metadata"])
    policy, policy_hash = _normalise_terms_policy(value["terms_policy"])
    if value.get("instrument_metadata_sha256") != metadata_hash or value.get("terms_policy_sha256") != policy_hash:
        raise PaperExecutionV2Error("v2 configuration component hash mismatch")
    migration = value.get("migration")
    if migration not in {"fresh_successor", "operator_reconciled_flat"}:
        raise PaperExecutionV2Error("v2 configuration migration mode is invalid")
    expected_value = _configuration_payload(metadata, metadata_hash, policy, policy_hash, migration)
    if value.get("configuration_sha256") != expected_value["configuration_sha256"]:
        raise PaperExecutionV2Error("v2 configuration hash mismatch")
    return expected_value


def _write_exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(dict(value)) + b"\n"
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    _sync_parent(path)


class ApprovalBoundPaperEngineV2(ApprovalBoundPaperEngine):
    """Approval-bound paper engine with caller-frozen grid, lot, and terms policy.

    It is intentionally a successor surface.  Existing state/journal pairs are
    refused unless an operator explicitly requests a reconciled-flat migration;
    no existing journal entry is rewritten or reinterpreted.
    """

    def __init__(
        self,
        state_path: str | Path,
        journal_path: str | Path,
        *,
        instrument_metadata: Mapping[str, Any],
        terms_policy: Mapping[str, Any],
        starting_equity: float = 10_000.0,
        policy: Any = None,
        migrate_reconciled_flat: bool = False,
    ):
        metadata, metadata_hash = _normalise_metadata(instrument_metadata)
        frozen_terms, terms_hash = _normalise_terms_policy(terms_policy)
        self.v2_config_path = Path(str(state_path) + ".paper_execution_v2.json")
        state = Path(state_path)
        journal = Path(journal_path)
        config_exists = self.v2_config_path.exists()
        existing_engine_bytes = state.exists() or journal.exists()
        if config_exists:
            existing = _validate_configuration(_read_json(self.v2_config_path, "v2 configuration"))
            desired = _configuration_payload(metadata, metadata_hash, frozen_terms, terms_hash, existing["migration"])
            if canonical_json_bytes(existing) != canonical_json_bytes(desired):
                raise PaperExecutionV2Error("v2 configuration changed; retain original metadata and terms policy")
            migration = existing["migration"]
        else:
            if existing_engine_bytes and not migrate_reconciled_flat:
                raise PaperExecutionV2Error(
                    "existing legacy state requires explicit migrate_reconciled_flat and a reconciled flat state"
                )
            migration = "operator_reconciled_flat" if existing_engine_bytes else "fresh_successor"
            if existing_engine_bytes:
                legacy = _read_json(state, "existing state")
                if legacy.get("positions") or legacy.get("pending"):
                    raise PaperExecutionV2Error("migration requires no pending proposals and no open positions")
        self.instrument_metadata = metadata
        self.instrument_metadata_sha256 = metadata_hash
        self.terms_policy_v2 = frozen_terms
        self.terms_policy_sha256 = terms_hash
        # Policy None means preserve the legacy safe defaults, while all *new* v2
        # policies remain caller supplied above rather than silently invented.
        kwargs: dict[str, Any] = {"instruments": _legacy_instruments(metadata), "migrate_legacy": migrate_reconciled_flat}
        if policy is not None:
            kwargs["policy"] = policy
        try:
            super().__init__(state, journal, starting_equity=starting_equity, **kwargs)
            if not config_exists:
                _write_exclusive_json(
                    self.v2_config_path,
                    _configuration_payload(metadata, metadata_hash, frozen_terms, terms_hash, migration),
                )
        except Exception:
            # The base class takes OS locks.  Release them if a v2 sidecar failure
            # occurs after successful base initialization.
            if hasattr(self, "lock"):
                self.close()
            raise

    def _metadata_for(self, symbol: str) -> Mapping[str, Any]:
        try:
            return self.instrument_metadata[symbol]
        except KeyError as exc:
            raise RejectedIntent("unknown_or_unverified_instrument_metadata") from exc

    def _on_grid(self, value: object, metadata: Mapping[str, Any], field: str) -> Decimal:
        decimal = _as_decimal(value, field)
        tick = Decimal(str(metadata["tick_size"]))
        if decimal <= 0 or decimal % tick != 0:
            raise RejectedIntent("off_tick")
        return decimal

    def _validate_grid_market(self, market: MarketSnapshot, metadata: Mapping[str, Any]) -> None:
        bid = self._on_grid(market.bid, metadata, "market_bid")
        ask = self._on_grid(market.ask, metadata, "market_ask")
        if bid > ask:
            raise RejectedIntent("invalid_market_grid")

    def _validate_grid_intent(self, intent: TradeIntent, metadata: Mapping[str, Any]) -> None:
        self._on_grid(intent.entry_reference, metadata, "intent_entry_reference")
        self._on_grid(intent.stop, metadata, "intent_stop")
        self._on_grid(intent.target, metadata, "intent_target")

    def _modeled_fill(self, intent: TradeIntent, market: MarketSnapshot, metadata: Mapping[str, Any]) -> Decimal:
        tick = Decimal(str(metadata["tick_size"]))
        slip = _as_decimal(self.policy.slippage_ticks, "slippage_ticks") * tick
        raw = _as_decimal(market.ask if intent.side == "LONG" else market.bid, "market_price")
        fill = raw + slip if intent.side == "LONG" else raw - slip
        if fill <= 0 or fill % tick != 0:
            raise RejectedIntent("modeled_fill_off_tick")
        return fill

    def _exit_fill(self, position: Mapping[str, Any], market: MarketSnapshot, metadata: Mapping[str, Any]) -> Decimal:
        tick = Decimal(str(metadata["tick_size"]))
        slip = _as_decimal(self.policy.slippage_ticks, "slippage_ticks") * tick
        raw = _as_decimal(market.bid if position["side"] == "LONG" else market.ask, "market_price")
        result = raw - slip if position["side"] == "LONG" else raw + slip
        if result <= 0 or result % tick != 0:
            raise RejectedIntent("modeled_exit_fill_off_tick")
        return result

    def _normalise_contracts(self, contracts: int, metadata: Mapping[str, Any]) -> int:
        increment = int(metadata["contract_increment"])
        normalized = min(int(contracts), int(metadata["max_contracts"]))
        normalized -= normalized % increment
        if normalized < int(metadata["min_contracts"]):
            raise RejectedIntent("risk_budget_too_small")
        return normalized

    def _validate(self, intent: TradeIntent, market: MarketSnapshot, now: datetime, *, allow_seen: bool = False):
        # This method is called only after v2 public methods checked grids before a
        # base operation can roll the day or persist anything.
        spec, allowed = super()._validate(intent, market, now, allow_seen=allow_seen)
        return spec, self._normalise_contracts(allowed, self._metadata_for(intent.symbol))

    def _terms(self, intent: TradeIntent, market: MarketSnapshot, contracts: int) -> dict[str, Any]:
        metadata = self._metadata_for(intent.symbol)
        tick = Decimal(str(metadata["tick_size"]))
        fill = self._modeled_fill(intent, market, metadata)
        stop = _as_decimal(intent.stop, "intent_stop")
        target = _as_decimal(intent.target, "intent_target")
        risk_ticks = abs(fill - stop) / tick
        reward_ticks = abs(target - fill) / tick
        commission = _as_decimal(self.policy.commission_per_contract_per_side, "commission") * Decimal("2")
        tick_value = Decimal(str(metadata["tick_value"]))
        risk_per_contract = risk_ticks * tick_value + commission
        reward_per_contract = reward_ticks * tick_value - commission
        return validate_approval_terms_v2({
            "schema": "orderflow_edge_lab.approval_market_terms.v2",
            "symbol": intent.symbol,
            "side": intent.side,
            "bid": _decimal_text(str(market.bid), "market.bid", positive=True),
            "ask": _decimal_text(str(market.ask), "market.ask", positive=True),
            "modeled_fill": _decimal_text(str(fill), "modeled_fill", positive=True),
            "contracts": contracts,
            "risk_ticks": _decimal_text(str(risk_ticks), "risk_ticks", positive=True),
            "reward_ticks": _decimal_text(str(reward_ticks), "reward_ticks", positive=True),
            "risk_per_contract": _decimal_text(str(risk_per_contract), "risk_per_contract", positive=True),
            "reward_per_contract": _decimal_text(str(reward_per_contract), "reward_per_contract"),
            "terms_policy_sha256": self.terms_policy_sha256,
            "instrument_metadata_sha256": self.instrument_metadata_sha256,
        })

    def _market_terms_changed(self, submitted: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
        if not isinstance(submitted, Mapping) or submitted.get("schema") != current.get("schema"):
            return ["submitted_terms_missing"]
        metadata = self._metadata_for(str(current["symbol"]))
        tick = Decimal(str(metadata["tick_size"]))
        fields = (
            ("bid", "max_bid_move_ticks"),
            ("ask", "max_ask_move_ticks"),
            ("modeled_fill", "max_fill_move_ticks"),
        )
        changed: list[str] = []
        for field, tolerance_field in fields:
            try:
                movement = abs(Decimal(str(current[field])) - Decimal(str(submitted[field]))) / tick
            except (InvalidOperation, KeyError) as exc:
                raise RejectedIntent("approval_terms_corrupt") from exc
            if movement > Decimal(int(self.terms_policy_v2[tolerance_field])):
                changed.append(field)
        for field in ("contracts", "risk_ticks", "reward_ticks", "risk_per_contract", "reward_per_contract",
                      "terms_policy_sha256", "instrument_metadata_sha256"):
            if submitted.get(field) != current.get(field):
                changed.append(field)
        return changed

    def submit(
        self, intent: TradeIntent, market: MarketSnapshot, *, now: datetime | None = None, evidence: Mapping[str, Any] | None = None
    ) -> str:
        # Grid checks intentionally precede _operation_time/_validate so a bad tick
        # cannot even cause a day-roll checkpoint.
        metadata = self._metadata_for(intent.symbol)
        self._validate_grid_intent(intent, metadata)
        self._validate_grid_market(market, metadata)
        self._modeled_fill(intent, market, metadata)
        evidence_payload = dict(evidence) if evidence is not None else None
        try:
            evidence_sha = _sha256_payload(evidence_payload)
        except (TypeError, ValueError) as exc:
            raise RejectedIntent("evidence_not_canonical_json") from exc
        operation_time = self._operation_time(now)
        _, contracts = self._validate(intent, market, operation_time)
        intent_id = intent.intent_id
        submitted_at = operation_time.isoformat()
        expires_at = operation_time.timestamp() + self.policy.approval_ttl_seconds
        intent_payload = {**asdict(intent), "signal_time": intent.signal_time.astimezone(UTC).isoformat()}
        terms = self._terms(intent, market, contracts)
        binding = {
            "intent_id": intent_id,
            "intent": deepcopy(intent_payload),
            "contracts": contracts,
            "submitted_at": submitted_at,
            "expires_at": expires_at,
            "submitted_market": _market_payload(market),
            "evidence_sha256": evidence_sha,
            "engine_config_sha256": _sha256_payload(self.state["engine_config"]),
            "terms": terms,
            "terms_sha256": _sha256_payload(terms),
            "terms_policy_sha256": self.terms_policy_sha256,
            "instrument_metadata_sha256": self.instrument_metadata_sha256,
        }
        token = _sha256_payload(binding)
        self.state["pending"][intent_id] = {
            "intent": intent_payload,
            "submitted_at": submitted_at,
            "expires_at": expires_at,
            "contracts": contracts,
            "approval_binding": binding,
            "approval_token": token,
        }
        self.state["seen_intents"].append(intent_id)
        self._commit("intent_submitted", {
            "intent_id": intent_id, "contracts": contracts, "evidence": evidence_payload, "approval_token": token,
            "evidence_sha256": evidence_sha, "engine_config_sha256": binding["engine_config_sha256"],
            "terms_sha256": binding["terms_sha256"], "terms_policy_sha256": self.terms_policy_sha256,
            "instrument_metadata_sha256": self.instrument_metadata_sha256,
        }, operation_time)
        return intent_id

    def _fresh_binding(
        self, intent_id: str, intent: TradeIntent, market: MarketSnapshot, contracts: int, old: Mapping[str, Any], now: datetime
    ) -> tuple[dict[str, Any], str]:
        intent_payload = {**asdict(intent), "signal_time": intent.signal_time.astimezone(UTC).isoformat()}
        submitted_at = now.isoformat()
        expires_at = now.timestamp() + self.policy.approval_ttl_seconds
        terms = self._terms(intent, market, contracts)
        binding = {
            "intent_id": intent_id, "intent": intent_payload, "contracts": contracts, "submitted_at": submitted_at,
            "expires_at": expires_at, "submitted_market": _market_payload(market),
            "evidence_sha256": old["evidence_sha256"], "engine_config_sha256": _sha256_payload(self.state["engine_config"]),
            "terms": terms, "terms_sha256": _sha256_payload(terms), "terms_policy_sha256": self.terms_policy_sha256,
            "instrument_metadata_sha256": self.instrument_metadata_sha256,
        }
        return binding, _sha256_payload(binding)

    def approve(
        self, intent_id: str, market: MarketSnapshot, *, approval_token: str | None = None, now: datetime | None = None
    ) -> dict[str, Any]:
        self._ensure_open()
        pending = self.state["pending"].get(intent_id)
        if pending is None:
            raise RejectedIntent("unknown_pending_intent")
        raw = pending.get("intent", {})
        try:
            intent = TradeIntent(
                strategy_id=raw["strategy_id"], symbol=raw["symbol"], side=raw["side"],
                entry_reference=float(raw["entry_reference"]), stop=float(raw["stop"]), target=float(raw["target"]),
                signal_time=_parse_dt(raw["signal_time"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RejectedIntent("approval_binding_terms_mismatch") from exc
        metadata = self._metadata_for(intent.symbol)
        self._validate_grid_intent(intent, metadata)
        self._validate_grid_market(market, metadata)
        self._modeled_fill(intent, market, metadata)
        operation_time = self._operation_time(now)
        if operation_time.timestamp() >= float(pending["expires_at"]):
            self.state["pending"].pop(intent_id, None)
            self._commit("intent_expired", {"intent_id": intent_id}, operation_time)
            raise RejectedIntent("approval_expired")
        binding, expected_token = self._validated_binding(intent_id)
        if not isinstance(approval_token, str) or approval_token != expected_token:
            self._commit("approval_token_rejected", {"intent_id": intent_id, "token_supplied": isinstance(approval_token, str)}, operation_time)
            raise RejectedIntent("approval_token_mismatch")
        _, currently_allowed = self._validate(intent, market, operation_time, allow_seen=True)
        current_terms = self._terms(intent, market, currently_allowed)
        changed = self._market_terms_changed(binding.get("terms", {}), current_terms)
        if changed:
            refreshed, refreshed_token = self._fresh_binding(intent_id, intent, market, currently_allowed, binding, operation_time)
            self.state["pending"][intent_id] = {
                "intent": refreshed["intent"], "submitted_at": refreshed["submitted_at"],
                "expires_at": refreshed["expires_at"], "contracts": currently_allowed,
                "approval_binding": refreshed, "approval_token": refreshed_token,
            }
            self._commit("approval_market_terms_changed", {
                "intent_id": intent_id, "changed_fields": changed, "submitted_terms_sha256": binding.get("terms_sha256"),
                "current_terms_sha256": refreshed["terms_sha256"], "old_approval_token": expected_token,
                "refreshed_approval_token": refreshed_token, "submitted_contracts": binding["contracts"],
                "currently_allowed": currently_allowed,
            }, operation_time)
            return {
                "status": "APPROVAL_MARKET_TERMS_CHANGED", "intent_id": intent_id,
                "refreshed_approval_token": refreshed_token, "changed_fields": changed,
            }
        fill = float(self._modeled_fill(intent, market, metadata))
        position = {
            "intent_id": intent_id, "strategy_id": intent.strategy_id, "symbol": intent.symbol, "side": intent.side,
            "contracts": currently_allowed, "entry_fill": fill, "stop": intent.stop, "target": intent.target,
            "opened_at": operation_time.isoformat(), "instrument_metadata_sha256": self.instrument_metadata_sha256,
        }
        self.state["pending"].pop(intent_id, None)
        self.state["positions"][intent_id] = position
        self.state["trades_today"] += 1
        self._commit("paper_position_opened", position, operation_time)
        return deepcopy(position)

    def close_position(
        self, intent_id: str, market: MarketSnapshot, *, reason: str, now: datetime | None = None
    ) -> dict[str, Any]:
        self._ensure_open()
        position = self.state["positions"].get(intent_id)
        if position is None:
            raise RejectedIntent("unknown_position")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("close reason is required")
        metadata = self._metadata_for(str(position["symbol"]))
        self._validate_grid_market(market, metadata)
        if market.symbol != position["symbol"]:
            raise RejectedIntent("snapshot_symbol_mismatch")
        exit_fill = self._exit_fill(position, market, metadata)
        operation_time = self._operation_time(now)
        market_age = (operation_time - market.timestamp.astimezone(UTC)).total_seconds()
        if market_age < 0 or market_age > self.policy.max_market_age_seconds:
            raise RejectedIntent("stale_market")
        if operation_time < _parse_dt(position["opened_at"]):
            raise RejectedIntent("close_before_open")
        self._roll_day(operation_time)
        signed = exit_fill - _as_decimal(position["entry_fill"], "entry_fill") if position["side"] == "LONG" else _as_decimal(position["entry_fill"], "entry_fill") - exit_fill
        gross = float(signed / Decimal(str(metadata["tick_size"])) * Decimal(str(metadata["tick_value"])) * int(position["contracts"]))
        commissions = 2 * self.policy.commission_per_contract_per_side * int(position["contracts"])
        pnl = gross - commissions
        result = {**position, "exit_fill": float(exit_fill), "closed_at": operation_time.isoformat(), "reason": reason,
                  "gross_pnl": gross, "commissions": commissions, "net_pnl": pnl}
        self.state["positions"].pop(intent_id, None)
        self.state["equity"] += pnl
        self.state["realized_pnl_today"] += pnl
        self._commit("paper_position_closed", result, operation_time)
        return result

    def engage_kill_switch(
        self, snapshots: Mapping[str, MarketSnapshot] | None = None, *, flatten: bool = False, now: datetime | None = None
    ) -> dict[str, Any] | None:
        self._ensure_open()
        if not flatten:
            super().engage_kill_switch(snapshots, flatten=False, now=now)
            return None
        operation_time = self._operation_time(now)
        starting_ids = sorted(self.state["positions"])
        snapshot_map = dict(snapshots or {})
        errors: dict[str, str] = {}
        # Entire preflight runs before the kill/clear checkpoint and before a close.
        for intent_id in starting_ids:
            position = self.state["positions"][intent_id]
            snapshot = snapshot_map.get(position["symbol"])
            if not isinstance(snapshot, MarketSnapshot):
                errors[intent_id] = "missing_flatten_snapshot"
                continue
            try:
                metadata = self._metadata_for(str(position["symbol"]))
                self._validate_grid_market(snapshot, metadata)
                if snapshot.symbol != position["symbol"]:
                    raise RejectedIntent("snapshot_symbol_mismatch")
                if (operation_time - snapshot.timestamp.astimezone(UTC)).total_seconds() < 0 or (
                    operation_time - snapshot.timestamp.astimezone(UTC)).total_seconds() > self.policy.max_market_age_seconds:
                    raise RejectedIntent("stale_market")
                self._exit_fill(position, snapshot, metadata)
            except (RejectedIntent, ValueError) as exc:
                errors[intent_id] = str(exc)
        cancelled = sorted(self.state["pending"])
        self.state["kill_switch"] = True
        self.state["pending"].clear()
        if errors:
            self._commit("kill_switch_flatten_preflight_failed", {
                "expected_position_ids": starting_ids, "cancelled_intents": cancelled, "preflight_errors": errors,
            }, operation_time)
            return {"status": "PREFLIGHT_FAILED", "expected_position_ids": starting_ids, "closed_position_ids": [],
                    "remaining_position_ids": starting_ids, "preflight_errors": errors}
        self._commit("kill_switch_flatten_requested", {
            "expected_position_ids": starting_ids, "cancelled_intents": cancelled,
        }, operation_time)
        closed: list[str] = []
        for intent_id in starting_ids:
            self.close_position(intent_id, snapshot_map[self.state["positions"][intent_id]["symbol"]], reason="kill_switch_flatten", now=operation_time)
            closed.append(intent_id)
        self._commit("kill_switch_flatten_completed", {
            "expected_position_ids": starting_ids, "closed_position_ids": closed, "remaining_position_ids": sorted(self.state["positions"]),
        }, operation_time)
        return {"status": "COMPLETED", "expected_position_ids": starting_ids, "closed_position_ids": closed,
                "remaining_position_ids": sorted(self.state["positions"])}


def _validate_anchor(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "schema", "analysis", "generated_at", "state_identity", "journal_identity", "journal_head", "revision",
        "runtime_identity", "prior_anchor_sha256", "non_authority_claims", "anchor_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected or value.get("schema") != ANCHOR_SCHEMA or value.get("analysis") != "paper_reconciliation_anchor_v2":
        raise PaperExecutionV2Error("anchor has unsupported shape")
    if type(value.get("revision")) is not int or value["revision"] < 0:
        raise PaperExecutionV2Error("anchor revision is invalid")
    if value.get("journal_head") != "GENESIS":
        _sha256(value.get("journal_head"), "anchor.journal_head")
    _timestamp(value.get("generated_at"), "anchor.generated_at")
    if not isinstance(value.get("runtime_identity"), Mapping):
        raise PaperExecutionV2Error("anchor.runtime_identity must be caller-declared JSON object")
    try:
        # File identities and claims are intentionally local/non-authoritative.
        canonical_json_bytes(value["runtime_identity"])
        canonical_json_bytes(value["state_identity"])
        canonical_json_bytes(value["journal_identity"])
        if value["non_authority_claims"] != non_authority_claims():
            raise ValueError("claims")
    except (ContractValidationError, ValueError) as exc:
        raise PaperExecutionV2Error("anchor has invalid local identity or claims") from exc
    previous = value.get("prior_anchor_sha256")
    if previous is not None:
        _sha256(previous, "anchor.prior_anchor_sha256")
    unsigned = {key: value[key] for key in value if key != "anchor_sha256"}
    expected_hash = canonical_json_sha256(unsigned)
    if value.get("anchor_sha256") != expected_hash:
        raise PaperExecutionV2Error("anchor_sha256 mismatch")
    return {**unsigned, "anchor_sha256": expected_hash}


def build_reconciliation_anchor_v2(
    state_path: str | Path, journal_path: str | Path, *, runtime_identity: Mapping[str, Any], generated_at: str,
    prior_anchor: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build (but do not externally retain) a prospective reconciliation anchor."""

    state = Path(state_path)
    journal = Path(journal_path)
    if not state.is_file() or not journal.is_file():
        raise PaperExecutionV2Error("state and journal must be existing local files before anchoring")
    state_data = _read_json(state, "state")
    try:
        validate_execution_state(state_data)
        head = HashChainJournal.verify(journal)
    except (StateCorruptionError, OSError, ValueError) as exc:
        raise PaperExecutionV2Error("state/journal cannot be anchored") from exc
    if state_data.get("journal_head") != head:
        raise PaperExecutionV2Error("state is not checkpointed to the journal head; recover before anchoring")
    prior_hash = None if prior_anchor is None else _validate_anchor(prior_anchor)["anchor_sha256"]
    try:
        runtime = json.loads(canonical_json_bytes(dict(runtime_identity)).decode("utf-8"))
    except (ContractValidationError, TypeError) as exc:
        raise PaperExecutionV2Error("runtime_identity must be canonical JSON") from exc
    unsigned = {
        "schema": ANCHOR_SCHEMA,
        "analysis": "paper_reconciliation_anchor_v2",
        "generated_at": _timestamp(generated_at, "generated_at"),
        "state_identity": build_file_identity(state, logical_name="paper_state_v2"),
        "journal_identity": build_file_identity(journal, logical_name="paper_journal_v2"),
        "journal_head": head,
        "revision": state_data["revision"],
        "runtime_identity": runtime,
        "prior_anchor_sha256": prior_hash,
        "non_authority_claims": non_authority_claims(),
    }
    return {**unsigned, "anchor_sha256": canonical_json_sha256(unsigned)}


def write_reconciliation_anchor_v2(path: str | Path, anchor: Mapping[str, Any]) -> dict[str, Any]:
    """Exclusive-create a local anchor artifact; this does not prove independent retention."""

    normalized = _validate_anchor(anchor)
    target = Path(path)
    _write_exclusive_json(target, normalized)
    return {"path": str(target), "anchor_sha256": normalized["anchor_sha256"], "status": "LOCAL_ANCHOR_WRITTEN",
            "external_storage_verified": False}


def verify_reconciliation_anchor_v2(
    state_path: str | Path, journal_path: str | Path, *, trusted_anchor_path: str | Path | None = None,
    strict_unattended: bool = False,
) -> dict[str, Any]:
    """Read-only rollback/recovery check against an operator-supplied anchor artifact.

    A local anchor is only bytes.  This verifier never reports external retention
    as verified; strict unattended readiness nevertheless requires an operator to
    supply an independently retained anchor artifact for comparison.
    """

    state = Path(state_path)
    journal = Path(journal_path)
    base = {
        "schema": "orderflow_edge_lab.paper_anchor_verification.v2",
        "trusted_anchor_path": str(trusted_anchor_path) if trusted_anchor_path is not None else None,
        "strict_unattended": strict_unattended,
        "verification_scope": "read_only_local_state_journal_and_operator_supplied_anchor_bytes",
        "non_authority_claims": non_authority_claims(),
    }
    if trusted_anchor_path is None:
        return {**base, "status": "TRUSTED_ANCHOR_UNKNOWN", "ready_for_unattended": False if strict_unattended else None,
                "blockers": ["trusted_anchor_required_for_strict_unattended"] if strict_unattended else ["trusted_anchor_not_supplied"]}
    try:
        anchor_path = Path(trusted_anchor_path)
        anchor = _validate_anchor(_read_json(anchor_path, "trusted anchor"))
        state_data = _read_json(state, "state")
        validate_execution_state(state_data)
        records = HashChainJournal.records(journal)
        heads = {row["hash"] for row in records}
        latest, recovery_required = reconcile_execution(state, journal)
    except (PaperExecutionV2Error, StateCorruptionError, OSError, ValueError, KeyError, TypeError) as exc:
        return {**base, "status": "ANCHOR_INVALID_OR_LOCAL_INVALID", "ready_for_unattended": False,
                "blockers": ["anchor_or_local_bytes_invalid"], "error": f"{type(exc).__name__}: {exc}"}
    anchor_head = anchor["journal_head"]
    if anchor_head != "GENESIS" and anchor_head not in heads:
        return {**base, "status": "ROLLBACK_DETECTED", "ready_for_unattended": False,
                "blockers": ["trusted_anchor_head_not_in_current_journal"], "anchor_sha256": anchor["anchor_sha256"]}
    if latest["revision"] < anchor["revision"]:
        return {**base, "status": "ROLLBACK_DETECTED", "ready_for_unattended": False,
                "blockers": ["current_revision_older_than_trusted_anchor"], "anchor_sha256": anchor["anchor_sha256"]}
    if recovery_required:
        return {**base, "status": "RECOVERY_REQUIRED", "ready_for_unattended": False,
                "blockers": ["journal_ahead_recovery_required"], "anchor_sha256": anchor["anchor_sha256"]}
    location_warning = state.resolve().parent == anchor_path.resolve().parent or journal.resolve().parent == anchor_path.resolve().parent
    return {**base, "status": "ANCHOR_COMPARISON_PASSED", "ready_for_unattended": not location_warning,
            "blockers": ["anchor_location_not_independent"] if location_warning else [],
            "anchor_sha256": anchor["anchor_sha256"], "anchor_independent_retention_verified": False,
            "current_revision": latest["revision"], "current_journal_head": HashChainJournal.verify(journal)}


def audit_paper_execution_v2(
    state_path: str | Path, journal_path: str | Path, *, trusted_anchor_path: str | Path | None = None,
    strict_unattended: bool = False,
) -> dict[str, Any]:
    """Read-only successor audit exposing incomplete flatten and anchor blockers."""

    state = Path(state_path)
    journal = Path(journal_path)
    report: dict[str, Any] = {
        "schema": "orderflow_edge_lab.paper_execution_audit.v2",
        "analysis": "paper_execution_audit_v2",
        "non_authority_claims": non_authority_claims(),
        "ready_for_live": False,
    }
    blockers: list[str] = []
    try:
        records = HashChainJournal.records(journal)
        latest, recovery = reconcile_execution(state, journal)
        expected: list[str] | None = None
        closed: set[str] = set()
        completed = False
        for record in records:
            payload = record.get("payload", {})
            if record.get("event_type") == "kill_switch_flatten_requested":
                expected = list(payload.get("expected_position_ids", []))
                closed = set()
                completed = False
            elif expected is not None and record.get("event_type") == "paper_position_closed":
                ident = payload.get("intent_id")
                if isinstance(ident, str):
                    closed.add(ident)
            elif expected is not None and record.get("event_type") == "kill_switch_flatten_completed":
                completed = True
        remaining = sorted(set(expected or []) - closed)
        if expected is not None and not completed:
            blockers.append("flatten_incomplete")
        if recovery:
            blockers.append("recovery_required")
        report.update({
            "state_revision": latest["revision"], "journal_head": latest["journal_head"], "position_ids": sorted(latest["positions"]),
            "flatten": {"expected_position_ids": expected or [], "closed_position_ids": sorted(closed),
                        "remaining_position_ids": remaining, "completed": completed},
        })
    except (StateCorruptionError, OSError, ValueError, TypeError, KeyError) as exc:
        blockers.append("state_or_journal_invalid")
        report["audit_error"] = f"{type(exc).__name__}: {exc}"
    anchor = verify_reconciliation_anchor_v2(state, journal, trusted_anchor_path=trusted_anchor_path,
                                             strict_unattended=strict_unattended)
    report["anchor_verification"] = anchor
    if anchor["status"] != "ANCHOR_COMPARISON_PASSED" or anchor.get("blockers"):
        blockers.extend(f"anchor:{item}" for item in anchor.get("blockers", [anchor["status"]]))
    report["blockers"] = sorted(set(blockers))
    report["operational_ready"] = not report["blockers"]
    if strict_unattended and not anchor.get("ready_for_unattended"):
        report["operational_ready"] = False
    return report


def _load_market(path: str) -> MarketSnapshot:
    raw = _read_json(Path(path), "market")
    raw["timestamp"] = _parse_dt(raw["timestamp"])
    return MarketSnapshot(**raw)


def _load_intent(path: str) -> TradeIntent:
    raw = _read_json(Path(path), "intent")
    raw["signal_time"] = _parse_dt(raw["signal_time"])
    return TradeIntent(**raw)


def _engine_from_args(args: argparse.Namespace) -> ApprovalBoundPaperEngineV2:
    metadata = _read_json(Path(args.instruments), "instrument metadata")
    terms = _read_json(Path(args.terms_policy), "terms policy")
    return ApprovalBoundPaperEngineV2(
        args.state, args.journal, instrument_metadata=metadata, terms_policy=terms,
        starting_equity=args.equity, migrate_reconciled_flat=getattr(args, "migrate_reconciled_flat", False),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Offline manual-paper v2 CLI; no live/broker/network commands exist."""

    parser = argparse.ArgumentParser(description="Opt-in v2 paper-only grid, approval, flatten, and anchor controls.")
    parser.add_argument("--state", required=True)
    parser.add_argument("--journal", required=True)
    parser.add_argument("--instruments", help="caller-frozen v2 instrument metadata JSON")
    parser.add_argument("--terms-policy", help="caller-frozen v2 market-terms policy JSON")
    parser.add_argument("--equity", type=float, default=10000.0)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--migrate-reconciled-flat", action="store_true")
    submit = commands.add_parser("submit")
    submit.add_argument("--intent", required=True)
    submit.add_argument("--market", required=True)
    submit.add_argument("--evidence", required=True, help="caller-declared canonical evidence JSON")
    token = commands.add_parser("token")
    token.add_argument("intent_id")
    approve = commands.add_parser("approve")
    approve.add_argument("intent_id")
    approve.add_argument("--token", required=True)
    approve.add_argument("--market", required=True)
    close = commands.add_parser("close")
    close.add_argument("intent_id")
    close.add_argument("--market", required=True)
    close.add_argument("--reason", required=True)
    kill = commands.add_parser("kill")
    kill.add_argument("--flatten", action="store_true")
    kill.add_argument("--snapshots", help="symbol -> MarketSnapshot JSON object; required with --flatten")
    anchor = commands.add_parser("emit-anchor")
    anchor.add_argument("--runtime-identity", required=True)
    anchor.add_argument("--generated-at", required=True)
    anchor.add_argument("--prior-anchor")
    anchor.add_argument("--output", required=True)
    audit = commands.add_parser("audit")
    audit.add_argument("--trusted-anchor")
    audit.add_argument("--strict-unattended", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            report = audit_paper_execution_v2(args.state, args.journal, trusted_anchor_path=args.trusted_anchor,
                                              strict_unattended=args.strict_unattended)
            print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
            return 0 if report["operational_ready"] else 2
        if args.command == "emit-anchor":
            prior = _read_json(Path(args.prior_anchor), "prior anchor") if args.prior_anchor else None
            artifact = build_reconciliation_anchor_v2(args.state, args.journal,
                runtime_identity=_read_json(Path(args.runtime_identity), "runtime identity"), generated_at=args.generated_at,
                prior_anchor=prior)
            result = write_reconciliation_anchor_v2(args.output, artifact)
            print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
            return 0
        if not args.instruments or not args.terms_policy:
            raise PaperExecutionV2Error("--instruments and --terms-policy are required for engine commands")
        with _engine_from_args(args) as engine:
            if args.command == "init":
                result: dict[str, Any] = {"revision": engine.state["revision"], "configuration_path": str(engine.v2_config_path)}
            elif args.command == "submit":
                intent_id = engine.submit(_load_intent(args.intent), _load_market(args.market), evidence=_read_json(Path(args.evidence), "evidence"))
                result = {"intent_id": intent_id, "approval_token": engine.approval_token_for(intent_id)}
            elif args.command == "token":
                result = {"intent_id": args.intent_id, "approval_token": engine.approval_token_for(args.intent_id)}
            elif args.command == "approve":
                result = engine.approve(args.intent_id, _load_market(args.market), approval_token=args.token)
            elif args.command == "close":
                result = engine.close_position(args.intent_id, _load_market(args.market), reason=args.reason)
            else:
                if args.flatten and not args.snapshots:
                    raise PaperExecutionV2Error("--snapshots is required with --flatten")
                snapshots = None
                if args.snapshots:
                    raw = _read_json(Path(args.snapshots), "snapshots")
                    snapshots = {symbol: MarketSnapshot(**{**row, "timestamp": _parse_dt(row["timestamp"])}) for symbol, row in raw.items()}
                result = engine.engage_kill_switch(snapshots, flatten=args.flatten) or {"status": "KILL_SWITCH_ENGAGED"}
        print(json.dumps({"mode": "paper_v2", "status": "ok", "result": result}, sort_keys=True, indent=2, allow_nan=False))
        return 0 if result.get("status") not in {"PREFLIGHT_FAILED", "APPROVAL_MARKET_TERMS_CHANGED"} else 2
    except (PaperExecutionV2Error, StateCorruptionError, RejectedIntent, OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"mode": "paper_v2", "status": "failed", "reason": str(exc), "error_type": type(exc).__name__}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
