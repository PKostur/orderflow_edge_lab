"""Automated target-position bot for crypto-trend-core-v1 (paper execution only).

Pipeline per completed 8h bar:
    data gates -> frozen signals -> per-coin target weights -> fail-closed risk
    checks -> order plan (fixed quantity: trade only when a target weight
    changes) -> ExecutionAdapter -> journaled, atomic state.

Only ``PaperAdapter`` exists.  There is deliberately no live exchange adapter:
automatic live order transmission stays disabled by repository policy until the
promotion gates are met and a separate live step is explicitly approved.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Protocol

import pandas as pd

from orderflow_edge_lab.execution import HashChainJournal, StateCorruptionError, _EngineLock
from orderflow_edge_lab.universal_backtest import legacy_strategy
from orderflow_edge_lab.vol_sizing import vol_sized_strategy


class BotHalt(RuntimeError):
    """A fail-closed condition: the cycle stops without trading."""


@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    contract_size: float
    min_vol: float = 1.0
    vol_unit: float = 1.0
    taker_fee: float = 0.0004


@dataclass(frozen=True)
class BotLimits:
    max_gross_exposure: float = 1.0
    max_coin_exposure: float = 0.15
    max_drawdown_kill: float = 0.25  # from the pre-registered crypto-trend-core gate
    max_daily_loss_kill: float = 0.05
    max_hours_since_bar_close: float = 1.0  # a bot runs right after the close
    max_price_move_since_close: float = 0.05  # execution mark vs signal close
    slippage_bps: float = 5.0
    max_orders_per_cycle: int = 34


@dataclass(frozen=True)
class MarketMark:
    price: float
    timestamp: datetime


class ExecutionAdapter(Protocol):
    name: str

    def execute(self, symbol: str, contracts: float, mark: MarketMark, spec: ContractSpec,
                slippage_bps: float) -> dict[str, Any]: ...


class PaperAdapter:
    """Fills at the mark plus slippage and taker fee. It never touches a network."""

    name = "paper"

    def execute(self, symbol: str, contracts: float, mark: MarketMark, spec: ContractSpec,
                slippage_bps: float) -> dict[str, Any]:
        side = 1.0 if contracts > 0 else -1.0
        price = mark.price * (1.0 + side * slippage_bps / 10_000.0)
        notional = abs(contracts) * spec.contract_size * price
        return {"symbol": symbol, "contracts": contracts, "price": price,
                "fee": notional * spec.taker_fee, "adapter": self.name}


# ---------------------------------------------------------------- pure logic

def target_weights(config: Mapping[str, Any], frames: Mapping[str, pd.DataFrame]) -> dict[str, float]:
    """Per-coin target weight of equity from the frozen rules on completed 8h bars."""
    sizing = config["sizing"]
    symbols = config["groups"]["crypto"]
    n_sleeves = len(config["strategies"]) * len(symbols)
    weights = {s: 0.0 for s in symbols}
    for spec in config["strategies"]:
        strat = vol_sized_strategy(
            legacy_strategy(str(spec["family"])), window=int(sizing["window_bars"]),
            target_vol=float(sizing["target_annual_vol"]), cap=float(sizing["cap"]),
            bars_per_year=int(sizing.get("bars_per_year", 1095)))
        for s in symbols:
            weights[s] += float(strat.generate_target(frames[s], spec["parameters"], None).iloc[-1]) / n_sleeves
    return weights


def equity_of(state: Mapping[str, Any], marks: Mapping[str, MarketMark], specs: Mapping[str, ContractSpec]) -> float:
    eq = float(state["cash"])
    for s, p in state["positions"].items():
        eq += p["contracts"] * specs[s].contract_size * (marks[s].price - p["avg_price"])
    return eq


def round_contracts(notional: float, price: float, spec: ContractSpec) -> float:
    raw = notional / (price * spec.contract_size)
    q = math.floor(abs(raw) / spec.vol_unit + 1e-9) * spec.vol_unit
    return 0.0 if q < spec.min_vol else math.copysign(q, raw)


def plan_orders(
    state: Mapping[str, Any],
    weights: Mapping[str, float],
    marks: Mapping[str, MarketMark],
    specs: Mapping[str, ContractSpec],
    equity: float,
) -> dict[str, float]:
    """Fixed quantity: only coins whose target weight changed are re-sized."""
    orders = {}
    for s, w in weights.items():
        held = state["positions"].get(s, {}).get("contracts", 0.0)
        if math.isclose(w, state["target_weights"].get(s, 0.0), abs_tol=1e-12) and (held != 0.0 or w == 0.0):
            continue
        target = round_contracts(w * equity, marks[s].price, specs[s])
        if target != held:
            orders[s] = target - held
    return orders


def risk_checks(
    state: Mapping[str, Any],
    weights: Mapping[str, float],
    orders: Mapping[str, float],
    equity: float,
    limits: BotLimits,
    *,
    bar_close: datetime,
    now: datetime,
    closes: Mapping[str, float],
    marks: Mapping[str, MarketMark],
) -> list[str]:
    problems = []
    hours = (now - bar_close).total_seconds() / 3600.0
    if hours < 0 or hours > limits.max_hours_since_bar_close:
        problems.append(f"stale_cycle:{hours:.2f}h")
    for s, m in marks.items():
        if (now - m.timestamp).total_seconds() > 120:
            problems.append(f"stale_mark:{s}")
        if abs(m.price / closes[s] - 1.0) > limits.max_price_move_since_close:
            problems.append(f"price_jump:{s}")
    gross = sum(abs(w) for w in weights.values())
    if gross > limits.max_gross_exposure + 1e-9:
        problems.append(f"gross:{gross:.3f}")
    worst = max((abs(w) for w in weights.values()), default=0.0)
    if worst > limits.max_coin_exposure + 1e-9:
        problems.append(f"coin_exposure:{worst:.3f}")
    if len(orders) > limits.max_orders_per_cycle:
        problems.append("too_many_orders")
    if equity <= state["peak_equity"] * (1.0 - limits.max_drawdown_kill):
        problems.append("drawdown_kill")
    if equity <= state["day_start_equity"] * (1.0 - limits.max_daily_loss_kill):
        problems.append("daily_loss_kill")
    return problems


def apply_fill(state: dict[str, Any], fill: Mapping[str, Any], spec: ContractSpec) -> None:
    s, dq, px = fill["symbol"], float(fill["contracts"]), float(fill["price"])
    pos = state["positions"].get(s, {"contracts": 0.0, "avg_price": px})
    q, avg = pos["contracts"], pos["avg_price"]
    new_q = q + dq
    if q != 0.0 and math.copysign(1, dq) != math.copysign(1, q):  # reducing or flipping
        closed = min(abs(dq), abs(q)) * math.copysign(1, q)
        state["cash"] += closed * spec.contract_size * (px - avg)
        avg = px if abs(dq) > abs(q) else avg
    elif q == 0.0:
        avg = px
    else:  # adding in the same direction
        avg = (q * avg + dq * px) / new_q
    state["cash"] -= float(fill["fee"])
    if abs(new_q) < 1e-12:
        state["positions"].pop(s, None)
    else:
        state["positions"][s] = {"contracts": new_q, "avg_price": avg}


# ---------------------------------------------------------------- runner

class TrendBot:
    STATE_VERSION = 1

    def __init__(self, state_path: str | Path, journal_path: str | Path, *, starting_equity: float,
                 adapter: ExecutionAdapter, limits: BotLimits = BotLimits()):
        if getattr(adapter, "name", None) != "paper":
            raise BotHalt("only the paper adapter is permitted; live transmission is disabled by policy")
        self.state_path = Path(state_path)
        self.adapter = adapter
        self.limits = limits
        self.lock = _EngineLock(self.state_path.with_suffix(".lock"))
        self.lock.acquire()
        try:
            self.journal = HashChainJournal(journal_path)
            if self.state_path.exists():
                self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
                if self.state.get("journal_head") != self.journal._last_hash:
                    raise StateCorruptionError("state does not match journal head; reconcile before trading")
            else:
                self.state = {"version": self.STATE_VERSION, "cash": float(starting_equity),
                              "positions": {}, "target_weights": {}, "peak_equity": float(starting_equity),
                              "day": None, "day_start_equity": float(starting_equity), "kill_switch": None,
                              "last_bar_close": None, "cycles": 0, "journal_head": self.journal._last_hash}
                self._commit("bot_initialized", {"starting_equity": starting_equity, "limits": asdict(limits)},
                             datetime.now(UTC))
        except Exception:
            self.lock.release()
            raise

    def close(self) -> None:
        self.lock.release()

    def _commit(self, event: str, payload: Mapping[str, Any], when: datetime) -> None:
        head = self.journal.append(event, {**deepcopy(dict(payload)), "state_after": deepcopy(self.state)}, when)
        self.state["journal_head"] = head
        tmp = self.state_path.with_suffix(".partial")
        tmp.write_text(json.dumps(self.state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def run_cycle(
        self,
        config: Mapping[str, Any],
        frames: Mapping[str, pd.DataFrame],
        marks: Mapping[str, MarketMark],
        specs: Mapping[str, ContractSpec],
        *,
        now: datetime,
        funding_since_last: Mapping[str, float] | None = None,
    ) -> dict[str, Any]:
        bar_open = max(f.index[-1] for f in frames.values())
        bar_close = (bar_open + pd.Timedelta(hours=8)).to_pydatetime()
        if self.state["last_bar_close"] == bar_close.isoformat():
            return {"status": "ALREADY_DONE", "bar_close": bar_close.isoformat()}
        if self.state["kill_switch"]:
            raise BotHalt(f"kill switch engaged: {self.state['kill_switch']}")
        day = now.date().isoformat()
        # funding cash flows on positions held since the previous cycle (long pays positive)
        for s, rate in (funding_since_last or {}).items():
            pos = self.state["positions"].get(s)
            if pos and rate:
                self.state["cash"] -= pos["contracts"] * specs[s].contract_size * marks[s].price * rate
        equity = equity_of(self.state, marks, specs)
        if self.state["day"] != day:
            self.state["day"], self.state["day_start_equity"] = day, equity
        self.state["peak_equity"] = max(self.state["peak_equity"], equity)
        weights = target_weights(config, frames)
        orders = plan_orders(self.state, weights, marks, specs, equity)
        closes = {s: float(f["close"].iloc[-1]) for s, f in frames.items()}
        problems = risk_checks(self.state, weights, orders, equity, self.limits, bar_close=bar_close,
                               now=now, closes=closes, marks=marks)
        if problems:
            kill = [p for p in problems if p.endswith("_kill")]
            if kill:
                self.state["kill_switch"] = ",".join(kill)
            self._commit("cycle_blocked", {"bar_close": bar_close.isoformat(), "problems": problems,
                                           "equity": equity}, now)
            raise BotHalt(";".join(problems))
        fills = []
        for s, dq in sorted(orders.items()):
            fill = self.adapter.execute(s, dq, marks[s], specs[s], self.limits.slippage_bps)
            apply_fill(self.state, fill, specs[s])
            fills.append(fill)
        self.state["target_weights"] = {s: w for s, w in weights.items()}
        self.state["last_bar_close"] = bar_close.isoformat()
        self.state["cycles"] += 1
        equity_after = equity_of(self.state, marks, specs)
        self._commit("cycle_completed", {"bar_close": bar_close.isoformat(), "orders": orders, "fills": fills,
                                         "equity_before": equity, "equity_after": equity_after,
                                         "gross_weight": sum(abs(w) for w in weights.values())}, now)
        return {"status": "TRADED" if fills else "NO_CHANGE", "bar_close": bar_close.isoformat(),
                "fills": fills, "equity": equity_after}


# ---------------------------------------------------------------- CLI (paper only)

def _get_json(url: str) -> Any:
    import urllib.request

    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.load(response)
    if not payload.get("success", True):
        raise BotHalt(f"exchange data request failed: {url}")
    return payload["data"]


def main(argv: list[str] | None = None) -> int:
    import argparse

    from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
    from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

    p = argparse.ArgumentParser(description="Run one paper cycle of the crypto-trend-core bot.")
    p.add_argument("--config", default="config/crypto_trend_core_v1.json")
    p.add_argument("--state-dir", required=True)
    p.add_argument("--starting-equity", type=float, default=10_000.0)
    a = p.parse_args(argv)
    config = json.loads(Path(a.config).read_text(encoding="utf-8"))
    now = datetime.now(UTC)
    symbols = config["groups"]["crypto"]
    detail = {x["symbol"]: x for x in _get_json("https://contract.mexc.com/api/v1/contract/detail")}
    specs, frames, marks = {}, {}, {}
    start = (pd.Timestamp(now) - pd.Timedelta(days=150)).isoformat()
    for s in symbols:
        d = detail[s]
        if int(d.get("state", 1)) != 0:
            raise BotHalt(f"{s}: contract not in normal trading state")
        specs[s] = ContractSpec(s, float(d["contractSize"]), float(d["minVol"]), float(d.get("volUnit") or 1),
                                float(d.get("takerFeeRate") or 0))
        f = fetch_mexc_futures_klines(s, "8h", start, now.isoformat())
        frames[s] = f.loc[f.index + pd.Timedelta(hours=8) <= pd.Timestamp(now)]
        t = _get_json(f"https://contract.mexc.com/api/v1/contract/ticker?symbol={s}")
        marks[s] = MarketMark(float(t["fairPrice"]), datetime.fromtimestamp(int(t["timestamp"]) / 1000, UTC))
    state_dir = Path(a.state_dir)
    bot = TrendBot(state_dir / "state.json", state_dir / "journal.jsonl", starting_equity=a.starting_equity,
                   adapter=PaperAdapter())
    try:
        funding = {}
        last = bot.state.get("last_bar_close")
        if last and bot.state["positions"]:
            for s in bot.state["positions"]:
                hist = fetch_mexc_funding_history(s, last, now.isoformat())["funding_rate"]
                funding[s] = float(hist.sum())
        result = bot.run_cycle(config, frames, marks, specs, now=now, funding_since_last=funding)
        result["positions"] = bot.state["positions"]
        result["kill_switch"] = bot.state["kill_switch"]
    except BotHalt as exc:
        print(json.dumps({"status": "HALTED", "reason": str(exc)}))
        return 2
    finally:
        bot.close()
    print(json.dumps({k: result[k] for k in ("status", "bar_close", "equity") if k in result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
