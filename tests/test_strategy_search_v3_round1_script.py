"""strategy-search-v3 round-1 runner: single-look guards and an offline end-to-end run on synthetic data."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from orderflow_edge_lab import perp_basis_strategy as pbs
from orderflow_edge_lab import strategy_search as ss
from orderflow_edge_lab import strategy_search_round2 as r2
from tests.test_perp_basis_strategy import SyntheticWorld

ROOT = Path(__file__).resolve().parents[1]


def load_script():
    spec = importlib.util.spec_from_file_location("strategy_search_v3_round1",
                                                  ROOT / "scripts" / "strategy_search_v3_round1.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_universe(world: SyntheticWorld) -> dict:
    mark = {n: pd.DataFrame({"high": f["close"] * 1.001, "low": f["close"] * 0.999}) for n, f in world.perp.items()}
    provenance = {
        "perp_symbols_listed": len(world.perp), "symbols_excluded": {}, "perps_without_spot": [],
        "symbols_matched": len(world.perp), "instruments_used": len(world.perp), "end": "synthetic",
        "per_instrument": {n: {"first_bar_end": str(f.index[0]), "last_bar_end": str(f.index[-1]), "rows": len(f)}
                           for n, f in world.perp.items()},
        "funding": {n: {"rows": len(f), "first": str(f.index[0]), "last": str(f.index[-1]), "interval_hours": [8.0]}
                    for n, f in world.funding.items()},
        "spot": {},
    }
    return {"perp": world.perp, "spot": world.spot, "funding": world.funding, "mark": mark, "provenance": provenance}


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
            results, ledger = Path(tmp) / "round1_results.json", Path(tmp) / "trials.jsonl"
            results.write_text("{}", encoding="utf-8")
            code = self.module.main(["--test-mode", "--results", str(results), "--ledger", str(ledger)])
            self.assertEqual(code, 2)
            self.assertFalse(ledger.exists())
            self.assertEqual(results.read_text(encoding="utf-8"), "{}")

    def test_refuses_when_the_v3_ledger_has_a_round_one_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            results, ledger = Path(tmp) / "round1_results.json", Path(tmp) / "trials.jsonl"
            ledger.write_text(json.dumps({"id": "X", "round": 1, "status": "tested"}) + "\n", encoding="utf-8")
            before = ledger.read_text(encoding="utf-8")
            code = self.module.main(["--test-mode", "--results", str(results), "--ledger", str(ledger)])
            self.assertEqual(code, 2)
            self.assertFalse(results.exists())
            self.assertEqual(ledger.read_text(encoding="utf-8"), before)

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
                           "--round-config", "--crypto-config", "--crypto-pickle"):
                self.assertEqual(self.module.main([option, str(Path(tmp) / "x")]), 2, option)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_there_is_no_draw_override(self):
        for option in ("--draws", "--n-draws", "--seed"):
            with self.assertRaises(SystemExit) as ctx:
                self.module.main([option, "5"])
            self.assertEqual(ctx.exception.code, 2)

    def test_default_paths_point_at_the_registered_files(self):
        self.assertTrue((ROOT / "config" / "strategy_search_v3_leveraged.json").exists())
        self.assertTrue((ROOT / "config" / "strategy_search_v3_round1.json").exists())
        # the real single look was taken on 2026-10-12 (commit 21be091); tests must never have written it
        results = ROOT / "research" / "strategy_search_v3" / "round1_results.json"
        if results.exists():
            import json
            candidate = json.loads(results.read_text(encoding="utf-8"))["candidates"][0]
            self.assertEqual(candidate["id"], "V3R1C1_logbasis_quintile_8h")
            self.assertFalse(candidate["gates"]["G3"]["pass"])  # the recorded real verdict, not a test's


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.module = load_script()
        self.world = SyntheticWorld(n=14, days=150, edge=0.9, start="2023-05-01 01:00")
        self.reference = pd.Series(np.random.default_rng(1).normal(0, 0.01, 400),
                                   index=pd.date_range("2023-01-01", periods=400, freq="D", tz="UTC"))
        last_settlement = next(iter(self.world.funding.values())).index[-1]
        self.patches = [mock.patch.object(ss, "crypto_trend_core_reference", return_value=self.reference),
                        mock.patch.object(self.module, "FUNDING_REQUIRED_LAST", str(last_settlement)),
                        mock.patch.object(self.module, "FINAL_WEEK_START", str(last_settlement - pd.Timedelta("7D")))]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def paths(self, tmp):
        base = Path(tmp)
        return {"results": base / "r.json", "leverage": base / "lev.json", "ledger": base / "v3.jsonl",
                "v1": base / "v1.jsonl", "v2": base / "v2.jsonl"}

    def args(self, paths):
        return ["--test-mode", "--results", str(paths["results"]), "--leverage-results", str(paths["leverage"]),
                "--ledger", str(paths["ledger"]), "--v1-ledger", str(paths["v1"]), "--v2-ledger", str(paths["v2"])]

    @staticmethod
    def write_ledger(path, n_tested, extra=()):
        records = [{"id": f"T{i}", "round": 1, "status": "tested"} for i in range(n_tested)] + list(extra)
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    def test_single_look_on_synthetic_data_writes_results_leverage_and_ledger_once(self):
        module = self.module
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(module, "load_universe", return_value=synthetic_universe(self.world)):
            paths = self.paths(tmp)
            self.write_ledger(paths["v1"], 9, [{"id": "Z", "round": 1, "status": "ineligible"}])
            self.write_ledger(paths["v2"], 2)
            args = self.args(paths)
            self.assertEqual(module.main(args), 0)
            payload = json.loads(paths["results"].read_text(encoding="utf-8"))
            self.assertEqual(payload["n_trials_cumulative"], 12)  # v1 9 + v2 2 + this candidate; ineligible not counted
            self.assertEqual(payload["n_trials_breakdown"], {"v1_tested": 9, "v2_tested": 2, "v3_tested_before": 0,
                                                             "this_round": 1})
            cand = payload["candidates"][0]
            self.assertEqual(cand["gates"]["G5"]["n_trials"], 12)
            self.assertEqual(cand["gates"]["G4"]["n_null"], 999)
            self.assertEqual(payload["cost_bps_round_trip"], 14.0)
            self.assertEqual(payload["periods_per_year"], 365)
            self.assertFalse(payload["claims"]["live_trading_authorized"])
            self.assertEqual(len(cand["gates"]["G6"]["variants"]), 5)
            self.assertNotIn("levels", json.dumps(payload["leverage_assessment"]))  # not in the verdict file
            prov = payload["data_provenance"]
            self.assertEqual(prov["funding_integrity"]["missing"], [])
            self.assertEqual(prov["funding_integrity"]["active_symbols"], 14)
            self.assertEqual(len(prov["extreme_basis_abs_gt_10pct"]["top_by_share"]), 14)
            lev_payload = json.loads(paths["leverage"].read_text(encoding="utf-8"))
            levels = lev_payload["leverage_assessment"]["levels"]
            self.assertEqual(sorted(levels, key=int), ["1", "2", "3", "5", "10", "20"])  # JSON keys are sorted
            self.assertEqual(lev_payload["leverage_assessment"]["config"]["paths"], 5000)
            self.assertIn(lev_payload["leverage_assessment"]["max_safe_leverage"], (None, 1, 2, 3, 5, 10, 20))
            self.assertEqual(lev_payload["gate_verdict_file"], "r.json")
            records = ss.read_trials(paths["ledger"])
            tested = [r for r in records if r["status"] == "tested"]
            self.assertEqual([r["id"] for r in tested], ["V3R1C1_logbasis_quintile_8h"])
            updates = [r for r in records if r["status"] == "leverage_update"]
            self.assertEqual(len(updates), 1)
            self.assertEqual(updates[0]["max_safe_leverage"], lev_payload["leverage_assessment"]["max_safe_leverage"])
            self.assertTrue(all(r["status"] in ("tested", "leverage_update", "ineligible") for r in records))
            self.assertGreaterEqual(len(records), 3)  # tested, screened-out candidates, leverage update
            # the single look is now consumed: a second run is refused and nothing changes
            before = paths["results"].read_text(encoding="utf-8")
            self.assertEqual(module.main(args), 2)
            self.assertEqual(paths["results"].read_text(encoding="utf-8"), before)
            # update records are not trials: the next round would count v1 9 + v2 2 + v3 1
            total = sum(module.count_tested(ss.read_trials(paths[k])) for k in ("v1", "v2", "ledger"))
            self.assertEqual(total, 12)

    def test_missing_v2_ledger_counts_zero(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(self.module, "load_universe", return_value=synthetic_universe(self.world)):
            paths = self.paths(tmp)
            self.write_ledger(paths["v1"], 9)
            self.assertEqual(self.module.main(self.args(paths)), 0)
            payload = json.loads(paths["results"].read_text(encoding="utf-8"))
            self.assertEqual(payload["n_trials_cumulative"], 10)
            self.assertEqual(payload["n_trials_breakdown"]["v2_tested"], 0)

    def test_gate_verdict_is_saved_before_the_leverage_step_and_survives_its_failure(self):
        lines: list[str] = []
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(self.module, "load_universe", return_value=synthetic_universe(self.world)), \
                mock.patch.object(self.module.lev, "assess_leverage", side_effect=RuntimeError("boom")), \
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
            self.assertTrue(any("V3R1C1" in line and ("PASS" in line or "FAIL" in line) for line in lines))
            # the look is consumed even though the leverage step failed
            self.assertEqual(self.module.main(self.args(paths)), 2)

    def test_truncated_funding_fails_loudly_before_any_file_is_written(self):
        universe = synthetic_universe(self.world)
        name = next(iter(universe["funding"]))
        universe["funding"][name] = universe["funding"][name].iloc[:-3]  # stops short of the required settlement
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(self.module, "load_universe", return_value=universe):
            paths = self.paths(tmp)
            self.write_ledger(paths["v1"], 9)
            with self.assertRaises(pbs.PerpBasisError):
                self.module.main(self.args(paths))
            self.assertFalse(paths["results"].exists())
            self.assertFalse(paths["ledger"].exists())

    def test_non_finite_funding_rate_fails_loudly(self):
        universe = synthetic_universe(self.world)
        name = next(iter(universe["funding"]))
        universe["funding"][name].iloc[5, 0] = np.nan
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(self.module, "load_universe", return_value=universe):
            paths = self.paths(tmp)
            self.write_ledger(paths["v1"], 9)
            with self.assertRaises(pbs.PerpBasisError):
                self.module.main(self.args(paths))
            self.assertFalse(paths["results"].exists())


if __name__ == "__main__":
    unittest.main()
