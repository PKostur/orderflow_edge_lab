"""strategy-search-v3 round-2 runner: single-look guards and an offline end-to-end run on synthetic data."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from orderflow_edge_lab import liquidation_cascade as lc
from orderflow_edge_lab import strategy_search as ss
from orderflow_edge_lab import strategy_search_round2 as r2
from tests.test_liquidation_cascade import RandomWorld

ROOT = Path(__file__).resolve().parents[1]


def load_script():
    spec = importlib.util.spec_from_file_location("strategy_search_v3_round2",
                                                  ROOT / "scripts" / "strategy_search_v3_round2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_universe(world: RandomWorld) -> dict:
    provenance = {
        "symbols": list(world.perp), "end": "synthetic", "mark_start": "synthetic", "oi_start": "synthetic",
        "per_instrument": {n: {"first_bar_end": str(f.index[0]), "last_bar_end": str(f.index[-1]), "rows": len(f)}
                           for n, f in world.perp.items()},
        "funding": {n: {"rows": len(f), "first": str(f.index[0]), "last": str(f.index[-1]), "interval_hours": [8.0]}
                    for n, f in world.funding.items()},
        "oi": {n: {"rows": len(s), "first": str(s.index[0]), "last": str(s.index[-1]), "zero_or_negative_rows": 0,
                   "n_partial_days": 2 if n == "S00USDT" else 0, "partial_days": {}, "duplicate_rows_dropped": 0}
               for n, s in world.oi.items()},
    }
    return {"perp": {n: f[["close", "quote_volume"]] for n, f in world.perp.items()}, "perp_hl": world.perp_hl, "oi": {k: v.copy() for k, v in world.oi.items()},
            "funding": {k: v.copy() for k, v in world.funding.items()}, "mark": world.mark, "provenance": provenance,
            "universe_definition": {"symbols": list(world.perp)}}


class Guards(unittest.TestCase):
    """Every guard test stubs the network and the evaluation to raise, so a regressed guard fails loudly offline."""

    def setUp(self):
        self.module = load_script()
        boom = mock.Mock(side_effect=AssertionError("guard regressed: reached data loading / evaluation"))
        self.patches = [mock.patch.object(self.module, "load_universe", boom),
                        mock.patch.object(ss, "crypto_trend_core_reference", boom),
                        mock.patch.object(r2, "evaluate_candidate_general", boom)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_refuses_second_run_when_results_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            results, ledger = Path(tmp) / "round2_results.json", Path(tmp) / "trials.jsonl"
            results.write_text("{}", encoding="utf-8")
            code = self.module.main(["--test-mode", "--results", str(results), "--ledger", str(ledger)])
            self.assertEqual(code, 2)
            self.assertFalse(ledger.exists())
            self.assertEqual(results.read_text(encoding="utf-8"), "{}")

    def test_refuses_when_the_v3_ledger_has_a_round_two_record_but_not_for_round_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            results, ledger = Path(tmp) / "round2_results.json", Path(tmp) / "trials.jsonl"
            ledger.write_text(json.dumps({"id": "X", "round": 2, "status": "tested"}) + "\n", encoding="utf-8")
            before = ledger.read_text(encoding="utf-8")
            code = self.module.main(["--test-mode", "--results", str(results), "--ledger", str(ledger)])
            self.assertEqual(code, 2)
            self.assertFalse(results.exists())
            self.assertEqual(ledger.read_text(encoding="utf-8"), before)
            # round-1 records (always present in the real v3 ledger) must not block round 2: it proceeds to the
            # stubbed reference loader, which raises the sentinel
            ledger.write_text(json.dumps({"id": "X", "round": 1, "status": "tested"}) + "\n", encoding="utf-8")
            with self.assertRaises(AssertionError):
                self.module.main(["--test-mode", "--results", str(results), "--ledger", str(ledger),
                                  "--leverage-results", str(Path(tmp) / "lev.json")])

    def test_refuses_when_the_leverage_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            leverage, ledger = Path(tmp) / "lev.json", Path(tmp) / "trials.jsonl"
            leverage.write_text("{}", encoding="utf-8")
            code = self.module.main(["--test-mode", "--results", str(Path(tmp) / "r.json"),
                                     "--leverage-results", str(leverage), "--ledger", str(ledger)])
            self.assertEqual(code, 2)
            self.assertFalse(ledger.exists())

    def test_path_overrides_need_test_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            for option in ("--results", "--leverage-results", "--ledger", "--v1-ledger", "--v2-ledger", "--protocol",
                           "--round-config", "--crypto-config", "--crypto-pickle", "--universe-file"):
                self.assertEqual(self.module.main([option, str(Path(tmp) / "x")]), 2, option)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_there_is_no_draw_override(self):
        for option in ("--draws", "--n-draws", "--seed", "--oi-lag", "--cost-bps"):
            with self.assertRaises(SystemExit) as ctx:
                self.module.main([option, "5"])
            self.assertEqual(ctx.exception.code, 2)

    def test_registered_files_exist_and_the_round_constants_match(self):
        self.assertTrue((ROOT / "config" / "strategy_search_v3_leveraged.json").exists())
        self.assertTrue((ROOT / "config" / "strategy_search_v3_round2.json").exists())
        self.assertEqual(self.module.ROUND, 2)
        self.assertEqual(self.module.OI_REQUIRED_FIRST, "2021-12-01 23:55")  # first sample day after the amendment
        self.assertEqual(self.module.SEARCH_ID, "strategy-search-v3-leveraged")

    def test_cumulative_trial_count_with_the_real_ledgers_is_eleven(self):
        """v1 9 + v3 round 1 (1) + this candidate; records of round 2 itself (after the single look) are excluded."""
        count = self.module.count_tested
        v1 = ss.read_trials(ROOT / "research" / "strategy_search_v1" / "trials.jsonl")
        v2 = ss.read_trials(ROOT / "research" / "strategy_search_v2" / "trials.jsonl")  # absent file: no trials
        v3 = [r for r in ss.read_trials(ROOT / "research" / "strategy_search_v3" / "trials.jsonl")
              if r.get("round") != 2]
        self.assertEqual(count(v1) + count(v2) + count(v3) + 1, 11)


class UniverseFileTests(unittest.TestCase):
    """The fixed universe file must exist and record the amended registered criteria."""

    def setUp(self):
        self.module = load_script()
        self.symbols = [f"S{i:02d}USDT" for i in range(30)]
        self.good = {"symbols": self.symbols, "metrics_day": "2021-12-01", "size": 30,
                     "rank_window": ["2020-10-01", "2020-12-31"]}

    def write(self, tmp, definition):
        path = Path(tmp) / "u.json"
        path.write_text(json.dumps(definition), encoding="utf-8")
        return path

    def test_matching_file_is_loaded_and_passed_to_the_loader(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(self.module.lc, "load_data", return_value={"perp": {}}) as load:
            data = self.module.load_universe(self.write(tmp, self.good))
            self.assertEqual(load.call_args.args[0], self.symbols)
            self.assertEqual(data["universe_definition"], self.good)

    def test_missing_file_fails_loudly_and_never_rebuilds(self):
        boom = mock.Mock(side_effect=AssertionError("must not rebuild or download"))
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(self.module.bfm, "build_universe", boom), \
                mock.patch.object(self.module.lc, "load_data", boom):
            with self.assertRaises(SystemExit) as ctx:
                self.module.load_universe(Path(tmp) / "absent.json")
            self.assertIn("prefetch", str(ctx.exception))

    def test_every_deviation_from_the_registered_criteria_fails_loudly(self):
        bad = {"metrics_day": {**self.good, "metrics_day": "2021-01-01"}, "size": {**self.good, "size": 20},
               "window": {**self.good, "rank_window": ["2020-10-01", "2021-01-31"]},
               "count": {**self.good, "symbols": self.symbols[:29]},
               "duplicate": {**self.good, "symbols": self.symbols[:29] + [self.symbols[0]]},
               "no_criterion": {k: v for k, v in self.good.items() if k != "metrics_day"}}
        boom = mock.Mock(side_effect=AssertionError("must not download"))
        for label, definition in bad.items():
            with tempfile.TemporaryDirectory() as tmp, mock.patch.object(self.module.lc, "load_data", boom):
                with self.assertRaises(SystemExit, msg=label):
                    self.module.load_universe(self.write(tmp, definition))

    def test_the_real_universe_file_if_present_matches_the_registration(self):
        path = ROOT / "research" / "strategy_search_v3" / "round2_universe.json"
        if path.exists():
            self.module.check_universe_definition(json.loads(path.read_text(encoding="utf-8")))


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = RandomWorld(n=14, days=190, seed=21)

    def setUp(self):
        self.module = load_script()
        self.reference = pd.Series(np.random.default_rng(1).normal(0, 0.01, 400),
                                   index=pd.date_range("2023-01-01", periods=400, freq="D", tz="UTC"))
        last_settlement = next(iter(self.world.funding.values())).index[-1]
        first_oi = min(s.index[0] for s in self.world.oi.values())
        last_oi = min(s.index[-1] for s in self.world.oi.values())
        self.patches = [mock.patch.object(ss, "crypto_trend_core_reference", return_value=self.reference),
                        mock.patch.object(self.module, "FUNDING_REQUIRED_LAST", str(last_settlement)),
                        mock.patch.object(self.module, "FINAL_WEEK_START", str(last_settlement - pd.Timedelta(days=7))),
                        mock.patch.object(self.module, "OI_REQUIRED_FIRST", str(first_oi)),
                        mock.patch.object(self.module, "OI_REQUIRED_LAST", str(last_oi))]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def universe(self):
        return synthetic_universe(self.world)

    def paths(self, tmp):
        base = Path(tmp)
        return {"results": base / "r.json", "leverage": base / "lev.json", "ledger": base / "v3.jsonl",
                "v1": base / "v1.jsonl", "v2": base / "v2.jsonl"}

    def args(self, paths):
        return ["--test-mode", "--results", str(paths["results"]), "--leverage-results", str(paths["leverage"]),
                "--ledger", str(paths["ledger"]), "--v1-ledger", str(paths["v1"]), "--v2-ledger", str(paths["v2"])]

    @staticmethod
    def write_ledger(path, n_tested, extra=(), round_no=1):
        records = [{"id": f"T{i}", "round": round_no, "status": "tested"} for i in range(n_tested)] + list(extra)
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    def test_single_look_on_synthetic_data_writes_results_leverage_and_ledger_once(self):
        module = self.module
        lines: list[str] = []
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(module, "load_universe", return_value=self.universe()):
            paths = self.paths(tmp)
            self.write_ledger(paths["v1"], 9, [{"id": "Z", "round": 1, "status": "ineligible"}])
            self.write_ledger(paths["ledger"], 1, [{"id": "T0", "round": 1, "status": "leverage_update"}])
            args = self.args(paths)

            def capture(*a, **k):
                self.assertTrue(paths["results"].exists(), "the verdict must be on disk before PASS/FAIL is printed")
                lines.append(" ".join(map(str, a)))

            with mock.patch("builtins.print", side_effect=capture):
                self.assertEqual(module.main(args), 0)
            payload = json.loads(paths["results"].read_text(encoding="utf-8"))
            self.assertEqual(payload["n_trials_cumulative"], 11)  # v1 9 + v3 round 1 + this candidate
            self.assertEqual(payload["n_trials_breakdown"], {"v1_tested": 9, "v2_tested": 0, "v3_tested_before": 1,
                                                             "this_round": 1})
            self.assertEqual(payload["registered_trials_after_round"], "11 cumulative (N for G5)")
            cand = payload["candidates"][0]
            self.assertEqual(cand["id"], "V3R2C1_liquidation_cascade_reversal")
            self.assertEqual(cand["gates"]["G5"]["n_trials"], 11)
            self.assertEqual(cand["gates"]["G4"]["n_null"], 999)
            self.assertEqual(cand["gates"]["G4"]["null_type"], "event")
            self.assertEqual(len(cand["gates"]["G6"]["variants"]), 8)
            self.assertEqual(payload["cost_bps_round_trip"], 14.0)
            self.assertEqual(payload["periods_per_year"], 365)
            self.assertEqual(payload["null_seed"], 20261012)
            self.assertFalse(payload["claims"]["live_trading_authorized"])
            self.assertNotIn("levels", json.dumps(payload["leverage_assessment"]))  # not in the verdict file
            prov = payload["data_provenance"]
            self.assertEqual(prov["funding_integrity"]["missing"], [])
            self.assertEqual(prov["funding_integrity"]["active_symbols"], 14)
            self.assertEqual(prov["oi_integrity"]["symbols"], 14)
            self.assertEqual(prov["oi_snapshot_lag_minutes"], 5)
            self.assertEqual(len(prov["oi_staleness"]), 14)
            self.assertEqual(prov["universe_definition"]["symbols"], list(self.world.perp))
            self.assertIn("close_frame_sha256", prov)
            self.assertIn("oi_frame_sha256", prov)
            summary = payload["trade_summary"]
            self.assertGreater(summary["trades_taken"], 20)
            report = summary["event_report"]
            self.assertEqual(report["tradable_events_long"] + report["tradable_events_short"],
                             summary["events_long"] + summary["events_short"])
            self.assertGreaterEqual(report["raw_events_long"], report["tradable_events_long"])
            self.assertIn("dropped_dead_bar_long", report)
            self.assertIn("tradable_with_oi_older_than_30min", report)
            self.assertEqual(prov["oi_summary"]["partial_days_total"], 2)
            self.assertEqual(prov["oi_summary"]["symbols_with_partial_days"], ["S00USDT"])
            self.assertEqual(cand["params"]["trade_start"], "2021-12-01")
            self.assertEqual(cand["windows"]["development"][0], "2021-12-01")   # zero-filled from the registered start
            self.assertEqual(cand["windows"]["validation"], ["2023-07-01", "2026-09-30"])
            self.assertEqual(cand["return_days"], (pd.Timestamp("2026-09-30") - pd.Timestamp("2021-12-01")).days + 1)
            lev_check = json.loads(paths["leverage"].read_text(encoding="utf-8"))["leverage_assessment"]
            self.assertIn("positions_using_perp_fallback_bars", lev_check)
            self.assertEqual(lev_check["positions_without_any_bars"], 0)
            self.assertEqual(summary["development"]["long"] + summary["development"]["short"],
                             summary["development"]["trades"])
            lev_payload = json.loads(paths["leverage"].read_text(encoding="utf-8"))
            levels = lev_payload["leverage_assessment"]["levels"]
            self.assertEqual(sorted(levels, key=int), ["1", "2", "3", "5", "10", "20"])
            self.assertEqual(lev_payload["leverage_assessment"]["config"]["paths"], 5000)
            self.assertIn(lev_payload["leverage_assessment"]["max_safe_leverage"], (None, 1, 2, 3, 5, 10, 20))
            self.assertEqual(lev_payload["gate_verdict_file"], "r.json")
            self.assertTrue(lev_payload["leverage_assessment"]["sample"].startswith("validation 2023-07-01"))
            records = ss.read_trials(paths["ledger"])
            tested = [r for r in records if r["status"] == "tested" and r["round"] == 2]
            self.assertEqual([r["id"] for r in tested], ["V3R2C1_liquidation_cascade_reversal"])
            updates = [r for r in records if r["status"] == "leverage_update" and r["round"] == 2]
            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0]["max_safe_leverage"], lev_payload["leverage_assessment"]["max_safe_leverage"])
            self.assertTrue(any("V3R2C1" in line and ("PASS" in line or "FAIL" in line) for line in lines))
            # the single look is now consumed: a second run is refused and nothing changes
            before = paths["results"].read_text(encoding="utf-8")
            self.assertEqual(module.main(args), 2)
            self.assertEqual(paths["results"].read_text(encoding="utf-8"), before)
            # the leverage update is not a trial: a later round would count v1 9 + v3 2
            total = sum(module.count_tested(ss.read_trials(paths[k])) for k in ("v1", "v2", "ledger"))
            self.assertEqual(total, 11)

    def test_development_window_is_read_from_the_round_config(self):
        cfg = json.loads((ROOT / "config" / "strategy_search_v3_round2.json").read_text(encoding="utf-8"))
        cfg["amendments"][0]["changes"]["development"] = ["2021-12-01", "2023-05-31"]
        cfg["amendments"][0]["changes"]["validation"] = ["2023-06-01", "2026-09-30"]
        with tempfile.TemporaryDirectory() as tmp,                 mock.patch.object(self.module, "load_universe", return_value=self.universe()):
            paths = self.paths(tmp)
            cfg_path = Path(tmp) / "round2.json"
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
            self.write_ledger(paths["v1"], 9)
            self.assertEqual(self.module.main(self.args(paths) + ["--round-config", str(cfg_path)]), 0)
            windows = json.loads(paths["results"].read_text(encoding="utf-8"))["candidates"][0]["windows"]
            self.assertEqual(windows["development"][1], "2023-05-31")
            self.assertEqual(windows["validation"][0], "2023-06-01")

    def test_gate_verdict_is_saved_before_the_leverage_step_and_survives_its_failure(self):
        lines: list[str] = []
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(self.module, "load_universe", return_value=self.universe()), \
                mock.patch.object(lc, "assess_trade_book", side_effect=RuntimeError("boom")), \
                mock.patch("builtins.print", side_effect=lambda *a, **k: lines.append(" ".join(map(str, a)))):
            paths = self.paths(tmp)
            self.write_ledger(paths["v1"], 9)
            with self.assertRaises(RuntimeError):
                self.module.main(self.args(paths))
            self.assertTrue(paths["results"].exists())  # verdict on disk
            self.assertFalse(paths["leverage"].exists())
            records = ss.read_trials(paths["ledger"])
            self.assertEqual(sum(r["status"] == "tested" for r in records), 1)
            self.assertFalse(any(r["status"] == "leverage_update" for r in records))
            self.assertTrue(any("V3R2C1" in line and ("PASS" in line or "FAIL" in line) for line in lines))
            self.assertEqual(self.module.main(self.args(paths)), 2)  # the look is consumed

    def test_truncated_funding_fails_loudly_before_any_file_is_written(self):
        universe = self.universe()
        name = next(iter(universe["funding"]))
        universe["funding"][name] = universe["funding"][name].iloc[:-3]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(self.module, "load_universe", return_value=universe):
            paths = self.paths(tmp)
            self.write_ledger(paths["v1"], 9)
            with self.assertRaises(Exception) as ctx:
                self.module.main(self.args(paths))
            self.assertIn("funding", str(ctx.exception))
            self.assertFalse(paths["results"].exists())
            self.assertFalse(paths["ledger"].exists())

    def test_non_finite_funding_rate_fails_loudly(self):
        universe = self.universe()
        name = next(iter(universe["funding"]))
        universe["funding"][name].iloc[5, 0] = np.nan
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(self.module, "load_universe", return_value=universe):
            paths = self.paths(tmp)
            self.write_ledger(paths["v1"], 9)
            with self.assertRaises(Exception):
                self.module.main(self.args(paths))
            self.assertFalse(paths["results"].exists())

    def test_missing_or_non_finite_open_interest_fails_loudly_before_any_file_is_written(self):
        for damage in ("missing_symbol", "truncated", "nan"):
            universe = self.universe()
            name = next(iter(universe["oi"]))
            if damage == "missing_symbol":
                del universe["oi"][name]
            elif damage == "truncated":
                universe["oi"][name] = universe["oi"][name].iloc[:len(universe["oi"][name]) // 2]
            else:
                universe["oi"][name].iloc[7] = np.nan
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(self.module, "load_universe", return_value=universe):
                paths = self.paths(tmp)
                self.write_ledger(paths["v1"], 9)
                with self.assertRaises(lc.CascadeError, msg=damage):
                    self.module.main(self.args(paths))
                self.assertFalse(paths["results"].exists(), damage)
                self.assertFalse(paths["ledger"].exists(), damage)


if __name__ == "__main__":
    unittest.main()
