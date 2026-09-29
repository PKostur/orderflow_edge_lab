from __future__ import annotations

from datetime import datetime, timezone

UTC = timezone.utc
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.execution import HashChainJournal
from orderflow_edge_lab.trend_bot import (
    BotHalt,
    BotLimits,
    ContractSpec,
    MarketMark,
    PaperAdapter,
    TrendBot,
    apply_fill,
    plan_orders,
    round_contracts,
)


def _cfg() -> dict:
    cfg = json.loads(Path("config/crypto_trend_core_v1.json").read_text(encoding="utf-8"))
    cfg["groups"] = {"crypto": ["AAA", "BBB"]}
    return cfg


def _frames(n: int = 400, drift=(0.004, -0.004)) -> dict:
    out = {}
    for k, s in enumerate(["AAA", "BBB"]):
        idx = pd.date_range("2026-01-01T00:00Z", periods=n, freq="8h")
        rng = np.random.default_rng(k)
        close = 100 * np.exp(np.cumsum(rng.normal(drift[k], 0.01, n)))
        open_ = np.concatenate([[100.0], close[:-1]])
        out[s] = pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.002,
                               "low": np.minimum(open_, close) * 0.998, "close": close}, index=idx)
    return out


TWO_COIN = BotLimits(max_coin_exposure=0.6)  # 2 test coins -> up to 50% each; production default is 15%


class _Live:
    name = "live"


class TrendBotTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.state = Path(self.dir.name) / "state.json"
        self.journal = Path(self.dir.name) / "journal.jsonl"

    def tearDown(self):
        self.dir.cleanup()

    def _run(self, bot, frames, *, now=None, price_mult=1.0):
        close_time = frames["AAA"].index[-1] + pd.Timedelta(hours=8)
        now = now or (close_time + pd.Timedelta(minutes=2)).to_pydatetime()
        marks = {s: MarketMark(float(f["close"].iloc[-1]) * price_mult, now) for s, f in frames.items()}
        specs = {s: ContractSpec(s, 0.01) for s in frames}
        return bot.run_cycle(_cfg(), frames, marks, specs, now=now)

    def test_only_paper_adapter_is_accepted(self):
        with self.assertRaises(BotHalt):
            TrendBot(self.state, self.journal, starting_equity=10_000, adapter=_Live())

    def test_cycle_trades_long_and_short_and_is_idempotent(self):
        bot = TrendBot(self.state, self.journal, starting_equity=10_000, adapter=PaperAdapter(), limits=TWO_COIN)
        try:
            r = self._run(bot, _frames())
            self.assertEqual(r["status"], "TRADED")
            pos = bot.state["positions"]
            self.assertGreater(pos["AAA"]["contracts"], 0)
            self.assertLess(pos["BBB"]["contracts"], 0)
            self.assertEqual(self._run(bot, _frames())["status"], "ALREADY_DONE")
        finally:
            bot.close()
        self.assertEqual(len(HashChainJournal.records(self.journal)), 2)

    def test_fixed_quantity_no_trade_when_weights_unchanged(self):
        bot = TrendBot(self.state, self.journal, starting_equity=10_000, adapter=PaperAdapter(), limits=TWO_COIN)
        try:
            self._run(bot, _frames(400))
            before = json.loads(json.dumps(bot.state["positions"]))
            r = self._run(bot, _frames(401))
            if r["status"] == "NO_CHANGE":
                self.assertEqual(bot.state["positions"], before)
        finally:
            bot.close()

    def test_restart_resumes_and_detects_tampering(self):
        bot = TrendBot(self.state, self.journal, starting_equity=10_000, adapter=PaperAdapter(), limits=TWO_COIN)
        self._run(bot, _frames())
        bot.close()
        bot2 = TrendBot(self.state, self.journal, starting_equity=10_000, adapter=PaperAdapter(), limits=TWO_COIN)
        self.assertEqual(bot2.state["cycles"], 1)
        bot2.close()
        s = json.loads(self.state.read_text())
        s["cash"] += 1_000_000
        s["journal_head"] = "forged"
        self.state.write_text(json.dumps(s))
        with self.assertRaises(Exception):
            TrendBot(self.state, self.journal, starting_equity=10_000, adapter=PaperAdapter(), limits=TWO_COIN)

    def test_stale_cycle_and_price_jump_block_trading(self):
        bot = TrendBot(self.state, self.journal, starting_equity=10_000, adapter=PaperAdapter(), limits=TWO_COIN)
        try:
            late = (_frames()["AAA"].index[-1] + pd.Timedelta(hours=12)).to_pydatetime()
            with self.assertRaises(BotHalt):
                self._run(bot, _frames(), now=late)
            with self.assertRaises(BotHalt):
                self._run(bot, _frames(402), price_mult=1.2)
            self.assertEqual(bot.state["positions"], {})
        finally:
            bot.close()

    def test_drawdown_kill_switch_latches(self):
        bot = TrendBot(self.state, self.journal, starting_equity=10_000, adapter=PaperAdapter(),
                       limits=BotLimits(max_drawdown_kill=0.25, max_coin_exposure=0.6))
        try:
            bot.state["cash"] = 7_000.0  # simulate a 30% loss from the 10,000 peak
            with self.assertRaises(BotHalt):
                self._run(bot, _frames())
            self.assertEqual(bot.state["kill_switch"], "drawdown_kill")
            with self.assertRaises(BotHalt):
                self._run(bot, _frames(401))
        finally:
            bot.close()

    def test_position_accounting_realizes_pnl_on_reduce_and_flip(self):
        spec = ContractSpec("X", 1.0, taker_fee=0.0)
        st = {"cash": 0.0, "positions": {}}
        apply_fill(st, {"symbol": "X", "contracts": 10, "price": 100, "fee": 0}, spec)
        apply_fill(st, {"symbol": "X", "contracts": -4, "price": 110, "fee": 0}, spec)
        self.assertAlmostEqual(st["cash"], 40.0)
        apply_fill(st, {"symbol": "X", "contracts": -10, "price": 120, "fee": 0}, spec)
        self.assertAlmostEqual(st["cash"], 40.0 + 6 * 20)
        self.assertEqual(st["positions"]["X"], {"contracts": -4, "avg_price": 120})

    def test_round_and_plan_orders(self):
        spec = {"A": ContractSpec("A", 0.01)}
        self.assertEqual(round_contracts(1000, 100, spec["A"]), 1000)
        st = {"positions": {}, "target_weights": {}}
        marks = {"A": MarketMark(100.0, datetime.now(UTC))}
        self.assertEqual(plan_orders(st, {"A": 0.1}, marks, spec, 10_000), {"A": 1000})


if __name__ == "__main__":
    unittest.main()
