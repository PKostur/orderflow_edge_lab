"""Tests for the unified `orderflow` dispatcher (discovery layer only)."""

from __future__ import annotations

import contextlib
import io
import json
import pkgutil
from pathlib import Path
import unittest
from unittest import mock

from orderflow_edge_lab.cli.main import (
    _COMMANDS,
    _NAME_EXCEPTIONS,
    _resolve_target,
    available_commands,
    build_parser,
    main,
)

CLI_DIR = Path(__file__).resolve().parents[1] / "src" / "orderflow_edge_lab" / "cli"


class DispatcherCommandTableTests(unittest.TestCase):
    def test_every_command_maps_to_existing_cli_module(self):
        commands = available_commands()
        self.assertGreater(len(commands), 0)
        for command, module in commands.items():
            self.assertTrue(
                (CLI_DIR / f"{module}.py").is_file(),
                f"{command} maps to missing cli module {module}",
            )

    def test_every_cli_module_is_reachable(self):
        discovered = {
            info.name
            for info in pkgutil.iter_modules([str(CLI_DIR)])
            if not info.name.startswith("_")
        }
        discovered -= {"main"}
        reachable = set(available_commands().values())
        self.assertEqual(
            discovered,
            reachable,
            "every cli module must be reachable under exactly one command name",
        )

    def test_no_duplicate_module_mapping(self):
        modules = list(available_commands().values())
        self.assertEqual(len(modules), len(set(modules)))

    def test_name_exceptions_are_not_duplicated_by_convention(self):
        commands = available_commands()
        for command in _NAME_EXCEPTIONS:
            self.assertIn(command, commands)
        self.assertNotIn("orderflow-promote", commands)
        self.assertNotIn("orderflow-login", commands)

    def test_published_flat_scripts_all_present(self):
        for command in _COMMANDS:
            self.assertIn(command, available_commands())

    def test_list_json_is_sorted_and_wellformed(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["--list-json"])
        self.assertEqual(rc, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(list(payload), sorted(payload))
        for command, target in payload.items():
            self.assertTrue(target.startswith("orderflow_edge_lab.cli."))
            self.assertTrue(target.endswith(":main"))


class DispatcherRoutingTests(unittest.TestCase):
    def test_unknown_command_returns_2_with_payload(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["definitely-not-a-command"])
        self.assertEqual(rc, 2)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["status"], "unknown_command")

    def test_no_command_shows_help_and_returns_2(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main([])
        self.assertEqual(rc, 2)
        self.assertIn("usage:", buffer.getvalue())

    def test_prefixless_invocation_resolves_same_module(self):
        import importlib

        module = importlib.import_module("orderflow_edge_lab.cli.readiness")
        with mock.patch.object(module, "main", return_value=0) as entry:
            rc = main(["readiness"])
        self.assertEqual(rc, 0)
        entry.assert_called_once_with([])

    def test_resolve_target_shapes(self):
        self.assertEqual(
            _resolve_target("orderflow-promotion-check"),
            "orderflow_edge_lab.cli.promote:main",
        )
        self.assertEqual(
            _resolve_target("orderflow-session-metrics"),
            "orderflow_edge_lab.cli.session_metrics:main",
        )
        self.assertIsNone(_resolve_target("nope"))

    def test_argv_passthrough(self):
        parser = build_parser()
        args = parser.parse_args(["orderflow-session-metrics", "--registry", "x.json"])
        self.assertEqual(args.command, "orderflow-session-metrics")
        self.assertEqual(args.args, ["--registry", "x.json"])

    def test_none_return_maps_to_zero(self):
        import importlib

        module = importlib.import_module("orderflow_edge_lab.cli.readiness")
        with mock.patch.object(module, "main", return_value=None):
            rc = main(["orderflow-readiness"])
        self.assertEqual(rc, 0)

    def test_none_return_maps_to_zero_for_sysargv_style_entry(self):
        import importlib
        import inspect

        module = importlib.import_module("orderflow_edge_lab.cli.multi_agent")
        with mock.patch.object(module, "main", return_value=None):
            rc = main(["orderflow-multi-agent"])
        self.assertEqual(rc, 0)
        # multi_agent.main must remain a zero-argv entry point for this shim
        # path to be the exercised one.
        self.assertEqual(len(inspect.signature(module.main).parameters), 0)

    def test_return_code_is_propagated(self):
        import importlib

        module = importlib.import_module("orderflow_edge_lab.cli.readiness")
        with mock.patch.object(module, "main", return_value=3):
            rc = main(["orderflow-readiness"])
        self.assertEqual(rc, 3)

    def test_sysargv_style_entry_receives_shimmed_argv(self):
        captured = {}

        def fake_main():
            captured["argv"] = list(sys_argv())

        def sys_argv():
            import sys

            return sys.argv

        import importlib

        module = importlib.import_module("orderflow_edge_lab.cli.readiness")
        with mock.patch.object(module, "main", fake_main):
            rc = main(["orderflow-readiness", "--some-flag", "value"])
        self.assertEqual(rc, 0)
        self.assertEqual(captured["argv"], ["orderflow-readiness", "--some-flag", "value"])


if __name__ == "__main__":
    unittest.main()
