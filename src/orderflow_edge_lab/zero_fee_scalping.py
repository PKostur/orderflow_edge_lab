"""Development-only, bounded taker simulation; no exchange order interface.

Quotes come from genuine applied depth events, never cached BBO on trade rows.
Top-level capacity is a conservative proxy, not a full-depth fill model.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .pair_screen import NON_CRYPTO_BASES, NON_CRYPTO_CONCEPT_TOKENS, STABLE_BASES


class ScalpingError(ValueError):
    pass


def number(value: Any, name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool):
        raise ScalpingError(f"invalid {name}")
    try:
        out = float(value)
    except (ValueError, TypeError) as exc:
        raise ScalpingError(f"invalid {name}") from exc
    if not math.isfinite(out) or out < minimum:
        raise ScalpingError(f"invalid {name}")
    return out


def timestamp(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ScalpingError(f"invalid {name}")
    return value


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ScalpingError(f"expected JSON object: {path}")
    return value


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def screen_promotional_pairs(contract_path: str | Path, ticker_path: str | Path) -> dict[str, Any]:
    """PnL-independent advertised-zero-fee inventory, never account eligibility."""
    contracts, tickers = read_json(contract_path), read_json(ticker_path)
    if any(p.get("success") is not True or not isinstance(p.get("data"), list) for p in (contracts, tickers)):
        raise ScalpingError("invalid public screen responses")
    details = {row["symbol"]: row for row in contracts["data"]}
    selected = []
    for ticker in tickers["data"]:
        row = details.get(ticker.get("symbol"), {})
        if row.get("quoteCoin") != "USDT" or row.get("settleCoin") != "USDT" or row.get("state") != 0:
            continue
        base = str(row.get("baseCoin", "")).upper()
        concept = str(row.get("conceptPlate", "")).lower()
        if base in STABLE_BASES | NON_CRYPTO_BASES | {"PAXG", "XAUT", "SILVER"} or any(x in concept for x in NON_CRYPTO_CONCEPT_TOKENS):
            continue
        # Unknown rates must never be interpreted as zero.
        try:
            maker = number(row.get("makerFeeRate"), "advertised maker fee")
            taker = number(row.get("takerFeeRate"), "advertised taker fee")
            bid = number(ticker.get("bid1"), "screen bid", minimum=1e-18)
            ask = number(ticker.get("ask1"), "screen ask", minimum=1e-18)
            turnover = number(ticker.get("amount24"), "turnover")
        except ScalpingError:
            continue
        spread = (ask - bid) / ((ask + bid) / 2) * 10000
        if maker != 0 or taker != 0 or not 0 < spread <= 3 or turnover < 10_000_000:
            continue
        selected.append({"symbol": row["symbol"], "spread_bps": spread, "turnover_usdt_24h": turnover,
                         "advertised_maker_bps": maker * 10000, "advertised_taker_bps": taker * 10000,
                         "account_promotion_verified": False, "api_promotion_verified": False})
    selected.sort(key=lambda r: (-r["turnover_usdt_24h"], r["symbol"]))
    return {"experiment": "advertised_zero_fee_pair_screen", "status": "advertised_only",
            "selection_rule": {"max_spread_bps": 3, "min_turnover_usdt_24h": 10_000_000,
                               "ranking": "descending turnover, symbol tie-break", "strategy_pnl_used": False},
            "passing_count": len(selected), "selected": selected[:3],
            "source_hashes": {"contracts": sha256(contract_path), "tickers": sha256(ticker_path)}}


@dataclass(frozen=True)
class ScalpConfig:
    latency_ms: int = 250
    slippage_bps_per_leg: float = 1.0
    max_quote_age_ms: int = 500
    max_spread_bps: float = 3.0
    target_notional_usdt: float = 100.0
    max_top_depth_fraction: float = 0.05
    min_trade_count: int = 5
    min_flow_ratio: float = 0.25
    min_book_imbalance: float = 0.25
    min_microprice_edge: float = 0.20
    warmup_seconds: int = 10
    cooldown_ms: int = 2000
    stop_loss_bps: float = 10.0
    take_profit_bps: float = 10.0
    funding_guard_seconds: int = 180

    def validate(self) -> None:
        for key, value in asdict(self).items():
            number(value, key)
        for key in ("latency_ms", "max_quote_age_ms", "min_trade_count", "warmup_seconds", "cooldown_ms", "funding_guard_seconds"):
            if not isinstance(getattr(self, key), int) or isinstance(getattr(self, key), bool):
                raise ScalpingError(f"{key} must be an integer")
        for key in ("max_quote_age_ms", "max_spread_bps", "target_notional_usdt", "min_trade_count", "warmup_seconds", "stop_loss_bps", "take_profit_bps"):
            if getattr(self, key) <= 0:
                raise ScalpingError(f"{key} must be positive")
        if not 0 < self.max_top_depth_fraction <= 0.1:
            raise ScalpingError("top-depth fraction must be in (0, 0.1]")
        if not all(0 < getattr(self, k) <= 1 for k in ("min_flow_ratio", "min_book_imbalance", "min_microprice_edge")):
            raise ScalpingError("signal thresholds must be in (0, 1]")
        if self.slippage_bps_per_leg >= 10000:
            raise ScalpingError("slippage must be below 10000 bps")
        if self.funding_guard_seconds < 120 + self.latency_ms / 1000:
            raise ScalpingError("funding guard must cover maximum hold plus latency")


@dataclass(frozen=True)
class Contract:
    symbol: str
    contract_size: float
    min_volume: float
    volume_step: float
    funding_interval_hours: int
    next_settlement_ns: int
    funding_observed_ns: int

    @classmethod
    def from_detail(cls, row: Mapping[str, Any], funding: Mapping[str, Any]) -> Contract:
        # Only linear USDT perpetuals. Unknown units/schedule are not guessed.
        if row.get("quoteCoin") != "USDT" or row.get("settleCoin") != "USDT" or row.get("state") != 0:
            raise ScalpingError("requires active linear USDT perpetual")
        if funding.get("success") is not True or not isinstance(funding.get("data"), dict):
            raise ScalpingError("invalid funding response")
        schedule = funding["data"]
        if schedule.get("symbol") != row.get("symbol"):
            raise ScalpingError("funding symbol mismatch")
        interval = number(schedule.get("collectCycle"), "collectCycle", minimum=1)
        if not interval.is_integer() or 24 % int(interval):
            raise ScalpingError("unsupported UTC funding schedule")
        return cls(
            str(row["symbol"]),
            number(row.get("contractSize"), "contractSize", minimum=1e-18),
            number(row.get("minVol"), "minVol", minimum=1e-18),
            number(row.get("volUnit"), "volUnit", minimum=1e-18),
            int(interval),
            timestamp(schedule.get("nextSettleTime"), "nextSettleTime") * 1_000_000,
            timestamp(schedule.get("timestamp"), "funding timestamp") * 1_000_000,
        )

    def size(self, price: float, cfg: ScalpConfig) -> float:
        step = Decimal(str(self.volume_step))
        units = Decimal(str(cfg.target_notional_usdt)) / (Decimal(str(price)) * Decimal(str(self.contract_size)))
        return float((units / step).to_integral_value(rounding=ROUND_FLOOR) * step)

    def near_funding(self, ns: int, guard: int) -> bool:
        cycle = self.funding_interval_hours * 3600
        phase = ((ns - self.next_settlement_ns) / 1e9) % cycle
        return min(phase, cycle - phase) <= guard


class FeePolicy:
    """Account declarations are eligibility inputs, not an independent audit.

    Missing/inapplicable/stale evidence always falls back to declared normal
    fees. A quota-crossing leg is conservatively charged the normal rate in full.
    """

    def __init__(self, record: Mapping[str, Any], *, symbol: str, channel: str):
        self.record = dict(record)
        self.normal = number(record.get("normal_taker_bps"), "normal_taker_bps", minimum=1e-18)
        self.promo = number(record.get("taker_bps"), "taker_bps")
        number(record.get("maker_bps"), "maker_bps")
        self.symbol, self.channel = symbol, channel
        if channel not in {"api", "manual"}:
            raise ScalpingError("unknown execution channel")
        self.used_quota = 0.0

    def rate(self, ns: int, notional: float) -> tuple[float, list[str]]:
        r = self.record
        reasons = []
        for key, required in (("venue", "mexc_futures"), ("market", "linear_usdt_perpetual"), ("symbol", self.symbol), ("execution_channel", self.channel)):
            if r.get(key) != required:
                reasons.append(f"{key}_mismatch")
        for key in ("account_eligible", "region_eligible", "channel_eligible"):
            if r.get(key) is not True:
                reasons.append(f"{key}_not_verified")
        if not isinstance(r.get("terms_url"), str) or not r["terms_url"].startswith("https://"):
            reasons.append("terms_url_missing")
        digest = r.get("terms_snapshot_sha256", "")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            reasons.append("terms_snapshot_hash_missing")
        for key in ("observed_at_ns", "valid_from_ns", "valid_until_ns"):
            v = r.get(key)
            if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                reasons.append(f"{key}_missing")
        if not any(x.endswith("_missing") for x in reasons):
            if not r["valid_from_ns"] <= r["observed_at_ns"] < r["valid_until_ns"]:
                reasons.append("invalid_evidence_interval")
            if ns < r["observed_at_ns"] or ns < r["valid_from_ns"] or ns >= r["valid_until_ns"]:
                reasons.append("evidence_not_contemporaneous")
        quota_kind = r.get("quota_kind")
        if quota_kind == "limited":
            quota = number(r.get("remaining_quota_usdt"), "remaining_quota_usdt")
            if self.used_quota + notional > quota:
                reasons.append("quota_exhausted")
                # A crossing fill consumes the remaining quota even though we
                # conservatively charge its entire notional at the normal rate.
                self.used_quota = quota
        elif quota_kind != "unlimited":
            reasons.append("quota_unknown")
        if reasons:
            return self.normal, reasons
        self.used_quota += notional
        return self.promo, []


@dataclass(frozen=True)
class Quote:
    ns: int
    bid: float
    ask: float
    bid_contracts: float
    ask_contracts: float
    exchange_ns: int
    segment: int

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


def load_events(path: str | Path, symbol: str) -> tuple[list[dict[str, Any]], list[Quote | None], list[tuple[int, int]]]:
    events, states, times = [], [], []
    last_ns = 0
    segment = 0
    gaps = 0
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ScalpingError(f"invalid row {line_no}")
        if row.get("record_type") == "session_summary" and row.get("reconnects", 0) != 0:
            raise ScalpingError("capture reconnects lack feature-stream disconnect timestamps; use a clean capture")
        if row.get("symbol") != symbol:
            continue
        ns = timestamp(row.get("received_at_ns"), "received_at_ns")
        if ns < last_ns:
            raise ScalpingError("observation time regression")
        last_ns = ns
        if row.get("feature_schema_version") != 2:
            raise ScalpingError("requires feature schema v2")
        kind = row.get("event_type")
        new_gaps = row.get("true_depth_gaps_seen", 0)
        if isinstance(new_gaps, bool) or not isinstance(new_gaps, int) or new_gaps < gaps:
            raise ScalpingError("invalid gap counter")
        disrupted = new_gaps > gaps or row.get("recovered_after_gap") is True
        gaps = new_gaps
        if kind == "snapshot" or disrupted or row.get("record_type") == "symbol_unavailable":
            segment += 1
            states.append(None)
            times.append((ns, line_no))
        elif kind == "depth" and row.get("depth_applied") is True:
            bid = number(row.get("best_bid"), "best_bid", minimum=1e-18)
            ask = number(row.get("best_ask"), "best_ask", minimum=1e-18)
            if ask <= bid:
                segment += 1
                states.append(None)
            else:
                states.append(Quote(ns, bid, ask,
                                    number(row.get("best_bid_contract_volume"), "bid volume"),
                                    number(row.get("best_ask_contract_volume"), "ask volume"),
                                    timestamp(row.get("exchange_ts_ms"), "depth exchange timestamp") * 1_000_000,
                                    segment))
            times.append((ns, line_no))
        events.append({**row, "segment": segment, "event_index": line_no})
    if not events:
        raise ScalpingError("no symbol events")
    return events, states, times


def signal_side(row: Mapping[str, Any], cfg: ScalpConfig) -> int:
    if row.get("event_type") != "trade":
        return 0
    observed_ns = timestamp(row.get("received_at_ns"), "trade received timestamp")
    exchange_ns = timestamp(row.get("exchange_ts_ms"), "trade exchange timestamp") * 1_000_000
    if observed_ns - exchange_ns > cfg.max_quote_age_ms * 1_000_000 or exchange_ns - observed_ns > 100_000_000:
        return 0
    count = number(row.get("rolling_trade_count"), "trade count")
    buy = number(row.get("rolling_buy_volume"), "buy volume")
    sell = number(row.get("rolling_sell_volume"), "sell volume")
    if count < cfg.min_trade_count or buy + sell <= 0:
        return 0
    flow = (buy - sell) / (buy + sell)
    imbalance = number(row.get("book_imbalance_10"), "book imbalance", minimum=-1)
    bid = number(row.get("best_bid"), "signal bid", minimum=1e-18)
    ask = number(row.get("best_ask"), "signal ask", minimum=1e-18)
    micro = number(row.get("microprice"), "microprice", minimum=1e-18)
    if ask <= bid:
        return 0
    edge = (micro - (bid + ask) / 2) / ((ask - bid) / 2)
    if abs(imbalance) > 1 or abs(edge) > 1 + 1e-8:
        raise ScalpingError("signal feature outside its valid range")
    for side in (1, -1):
        if side * flow >= cfg.min_flow_ratio and side * imbalance >= cfg.min_book_imbalance and side * edge >= cfg.min_microprice_edge:
            return side
    return 0


def _summary(trades: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = [t[key] for t in trades]
    positive = sum(x for x in values if x > 0)
    negative = -sum(x for x in values if x < 0)
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {"trades": len(values), "net_pnl_usdt": equity,
            "mean_pnl_usdt": equity / len(values) if values else None,
            "win_rate": sum(x > 0 for x in values) / len(values) if values else None,
            "profit_factor": positive / negative if negative else None,
            "max_closed_trade_drawdown_usdt": drawdown}


def simulate(events: list[dict[str, Any]], states: list[Quote | None], times: list[tuple[int, int]], contract: Contract,
             record: Mapping[str, Any], cfg: ScalpConfig, *, channel: str, horizon: int, reverse: bool = False) -> dict[str, Any]:
    cfg.validate()
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 120 or cfg.latency_ms >= horizon * 1000:
        raise ScalpingError("invalid horizon/latency")
    fees = FeePolicy(record, symbol=contract.symbol, channel=channel)
    latency = cfg.latency_ms * 1_000_000
    last_ns = events[-1]["received_at_ns"]
    warmup_end = events[0]["received_at_ns"] + cfg.warmup_seconds * 1_000_000_000
    trades, unresolved = [], []
    rejections: Counter[str] = Counter()
    available_at = warmup_end
    attempts = 0

    def quote_at(ns: int, expected_segment: int | None = None, event_index: int = -1) -> tuple[Quote | None, str]:
        # Timers precede messages at an identical timestamp. Event-time checks
        # see only the source lines already observed, even inside a WS batch.
        idx = bisect_right(times, (ns, event_index)) - 1
        if idx < 0 or states[idx] is None:
            return None, "invalid_book"
        q = states[idx]
        assert q is not None
        if expected_segment is not None and q.segment != expected_segment:
            return None, "book_disruption"
        if ns - q.ns > cfg.max_quote_age_ms * 1_000_000:
            return None, "stale_book"
        if ns - q.exchange_ns > cfg.max_quote_age_ms * 1_000_000 or q.exchange_ns - ns > 100_000_000:
            return None, "stale_exchange_book_or_clock_skew"
        return q, ""

    def fill_price(q: Quote, side: int, entry: bool) -> float:
        buy = (side > 0) == entry
        raw = q.ask if buy else q.bid
        return raw * (1 + (1 if buy else -1) * cfg.slippage_bps_per_leg / 10000)

    for i, row in enumerate(events):
        signal_ns = row["received_at_ns"]
        if signal_ns < available_at:
            continue
        side = signal_side(row, cfg)
        if not side:
            continue
        attempts += 1
        side *= -1 if reverse else 1
        signal_quote, reason = quote_at(signal_ns, event_index=row["event_index"])
        if signal_quote is None:
            rejections[reason] += 1
            continue
        entry_ns = signal_ns + latency
        deadline = entry_ns + horizon * 1_000_000_000
        if deadline > last_ns:
            rejections["capture_tail"] += 1
            continue
        if contract.near_funding(entry_ns, cfg.funding_guard_seconds):
            rejections["funding_window"] += 1
            continue
        q, reason = quote_at(entry_ns, signal_quote.segment)
        if q is None:
            rejections[reason] += 1
            continue
        if (q.ask - q.bid) / q.mid * 10000 > cfg.max_spread_bps:
            rejections["wide_spread"] += 1
            continue
        entry_price = fill_price(q, side, True)
        qty = contract.size(entry_price, cfg)
        if qty < contract.min_volume or qty > cfg.max_top_depth_fraction * (q.ask_contracts if side > 0 else q.bid_contracts):
            rejections["entry_capacity"] += 1
            continue
        base_qty = qty * contract.contract_size
        entry_notional = base_qty * entry_price
        entry_rate, entry_reasons = fees.rate(entry_ns, entry_notional)
        decision_ns = deadline - latency
        exit_reason = "time_stop"
        path_returns = []
        # Observe only events before the hard timer. The exit order arrives no
        # later than the declared maximum hold even with modeled latency.
        for later in events[i + 1:]:
            t = later["received_at_ns"]
            if t <= entry_ns:
                continue
            if t > decision_ns:
                break
            path_quote, path_reason = quote_at(t, q.segment, later["event_index"])
            if path_quote is None:
                decision_ns, exit_reason = t, path_reason
                break
            mark = fill_price(path_quote, side, False)
            move = side * (mark / entry_price - 1) * 10000
            path_returns.append(move)
            if move <= -cfg.stop_loss_bps or move >= cfg.take_profit_bps:
                decision_ns = t
                exit_reason = "stop_loss" if move <= -cfg.stop_loss_bps else "take_profit"
                break
            if signal_side(later, cfg) == -side * (-1 if reverse else 1):
                decision_ns, exit_reason = t, "flow_reversal"
                break
        exit_ns = decision_ns + latency
        out, reason = quote_at(exit_ns, q.segment)
        capacity = 0 if out is None else cfg.max_top_depth_fraction * (out.bid_contracts if side > 0 else out.ask_contracts)
        if out is None or qty > capacity:
            unresolved.append({"entry_at_ns": entry_ns, "requested_exit_at_ns": exit_ns, "side": side,
                               "contracts": qty, "entry_price": entry_price, "entry_notional_usdt": entry_notional,
                               "reason": reason or "exit_capacity", "trigger": exit_reason})
            # Once exposure cannot be closed, this lane halts; no subsequent
            # opportunities are simulated as if inventory had disappeared.
            break
        exit_price = fill_price(out, side, False)
        exit_notional = base_qty * exit_price
        exit_rate, exit_reasons = fees.rate(exit_ns, exit_notional)
        gross = side * base_qty * (exit_price - entry_price)
        fee = (entry_notional * entry_rate + exit_notional * exit_rate) / 10000
        normal_fee = (entry_notional + exit_notional) * fees.normal / 10000
        move = side * (exit_price / entry_price - 1) * 10000
        path_returns.append(move)
        trades.append({"signal_at_ns": signal_ns, "entry_at_ns": entry_ns, "exit_at_ns": exit_ns,
                       "side": side, "contracts": qty, "entry_price": entry_price, "exit_price": exit_price,
                       "entry_notional_usdt": entry_notional, "exit_notional_usdt": exit_notional,
                       "holding_seconds": (exit_ns - entry_ns) / 1e9, "exit_reason": exit_reason,
                       "executable_gross_pnl_usdt": gross, "hypothetical_zero_fee_pnl_usdt": gross,
                       "normal_fee_pnl_usdt": gross - normal_fee, "applicable_fee_pnl_usdt": gross - fee,
                       "entry_fee_bps": entry_rate, "exit_fee_bps": exit_rate,
                       "fee_ineligibility_reasons": sorted(set(entry_reasons + exit_reasons)),
                       "documented_zero_fee_round_trip": not entry_reasons and not exit_reasons and entry_rate == exit_rate == 0,
                       "mid_move_bps": side * (out.mid / q.mid - 1) * 10000,
                       "mae_bps": min(0.0, min(path_returns)), "mfe_bps": max(0.0, max(path_returns))})
        available_at = exit_ns + cfg.cooldown_ms * 1_000_000
    return {"horizon_seconds": horizon, "reversed_control": reverse, "config": asdict(cfg),
            "signal_attempts": attempts, "entry_rejections": dict(rejections), "unresolved_positions": unresolved,
            "status": "incomplete_execution" if unresolved else "development_only", "pnl_complete": not unresolved,
            "completed_fills_per_signal_attempt": len(trades) / attempts if attempts else None,
            "summary": {key: _summary(trades, key) for key in
                        ("hypothetical_zero_fee_pnl_usdt", "normal_fee_pnl_usdt", "applicable_fee_pnl_usdt")},
            "trades": trades}


def evaluate(features_path: str | Path, contract_path: str | Path, funding_path: str | Path,
             fee_path: str | Path, protocol_path: str | Path,
             *, symbol: str) -> dict[str, Any]:
    protocol = read_json(protocol_path)
    if protocol.get("status") != "development_only" or protocol.get("venue") != "mexc_futures":
        raise ScalpingError("runner supports development-only MEXC futures protocol")
    cfg = ScalpConfig(**{key: protocol[key] for key in asdict(ScalpConfig())})
    cfg.validate()
    source_rows = [json.loads(line) for line in Path(features_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    summaries = [row for row in source_rows if isinstance(row, dict) and row.get("record_type") == "session_summary"]
    if len(summaries) != 1 or source_rows[-1] != summaries[0] or type(summaries[0].get("reconnects")) is not int or summaries[0]["reconnects"] != 0:
        raise ScalpingError("requires one terminal clean session_summary with reconnects=0")
    details = read_json(contract_path)
    if details.get("success") is not True or not isinstance(details.get("data"), list):
        raise ScalpingError("invalid contract detail response")
    matches = [r for r in details["data"] if r.get("symbol") == symbol]
    if len(matches) != 1:
        raise ScalpingError("contract metadata missing or duplicated")
    contract = Contract.from_detail(matches[0], read_json(funding_path))
    events, states, times = load_events(features_path, symbol)
    if not 0 <= events[0]["received_at_ns"] - contract.funding_observed_ns <= 24 * 3600 * 1_000_000_000:
        raise ScalpingError("funding metadata must precede capture and be less than 24 hours old")
    if contract.next_settlement_ns <= contract.funding_observed_ns:
        raise ScalpingError("invalid next funding settlement")
    record = read_json(fee_path)
    FeePolicy(record, symbol=symbol, channel=protocol["execution_channel"])
    runs = []
    for stress in protocol["stress_cases"]:
        stressed = replace(cfg, latency_ms=stress["latency_ms"], slippage_bps_per_leg=stress["slippage_bps_per_leg"])
        for horizon in protocol["horizons_seconds"]:
            for reverse in (False, True):
                run = simulate(events, states, times, contract, record, stressed,
                               channel=protocol["execution_channel"], horizon=horizon, reverse=reverse)
                runs.append({"stress_case": stress["name"], **run})
    incomplete = any(run["unresolved_positions"] for run in runs)
    return {"schema_version": 1, "experiment": "zero_fee_scalping_v1", "symbol": symbol,
            "status": "incomplete_execution" if incomplete else "development_only",
            "pnl_complete": not incomplete,
            "causal_clock": "received_at_ns", "contract": asdict(contract),
            "source_hashes": {"features": sha256(features_path), "contract": sha256(contract_path),
                              "funding": sha256(funding_path),
                              "fees": sha256(fee_path), "protocol": sha256(protocol_path),
                              "runner": sha256(__file__)},
            "capture_start_ns": events[0]["received_at_ns"], "capture_end_ns": events[-1]["received_at_ns"],
            "dependence_clusters": 1, "trial_count": len(runs), "runs": runs,
            "limitations": ["Top-level depth capacity proxy; no queue, full L2 impact or partial-fill estimation",
                            "Closed-trade drawdown omits unrealized exposure; unresolved fills block interpretation",
                            "Funding avoided using observed next settlement and interval; no funding PnL estimated",
                            "Manual channel requires human latency calibration, not API timing",
                            "Fee evidence is a user declaration; terms and account applicability are not independently audited",
                            "One capture is one dependence cluster; trials are not independent evidence"],
            "claims": {"exploratory_only": True, "verified_out_of_sample_evidence": False,
                       "profitable_edge_established": False, "live_order_transmission_supported": False,
                       "promotable": False}}
