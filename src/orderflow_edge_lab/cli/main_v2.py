"""Single ``orderflow`` dispatcher for installed operator commands.

Public command exposure is declared only by ``command_registry_v2.json``.  This
preserves historical aliases while making package metadata, help output, and
wheel smoke checks share one inventory; unclassified modules cannot silently
become public commands.
"""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys

from orderflow_edge_lab.command_registry_v2 import dispatcher_commands

_COMMANDS: dict[str, str] = dispatcher_commands()
_NAME_EXCEPTIONS = frozenset({"orderflow-promotion-check", "orderflow-dxfeed-login"})
_ENTRYPOINT_PREFIX = "orderflow_edge_lab.cli."


def _known_modules() -> dict[str, str]:
    """Compatibility helper: public discovery is intentionally disabled in v2."""
    return {}


def available_commands() -> dict[str, str]:
    """Return exactly the registry's dispatcher-visible command mappings."""
    return dict(sorted(_COMMANDS.items()))


def _resolve_target(command: str) -> str | None:
    module = available_commands().get(command)
    return f"{_ENTRYPOINT_PREFIX}{module}:main" if module is not None else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orderflow-v2",
        description="Unified dispatcher for registry-declared Orderflow Edge Lab operator commands.",
    )
    parser.add_argument("--list", action="store_true", dest="list_commands", help="List all available commands and exit.")
    parser.add_argument("--list-json", action="store_true", dest="list_json", help="List available commands as JSON and exit.")
    parser.add_argument("command", nargs="?", help="Command name (same name as the flat orderflow-<name> script).")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed through to the target command.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_commands or args.list_json:
        commands = available_commands()
        if args.list_json:
            print(json.dumps({command: f"{_ENTRYPOINT_PREFIX}{module}:main" for command, module in commands.items()}, sort_keys=True, indent=2))
        else:
            width = max(len(name) for name in commands)
            for command, module in commands.items():
                print(f"{command:<{width}}  ->  cli/{module}.py")
        return 0
    if not args.command:
        build_parser().print_help()
        return 2
    command = args.command
    target = _resolve_target(command)
    if target is None and not command.startswith("orderflow-"):
        command = f"orderflow-{command}"
        target = _resolve_target(command)
    if target is None:
        print(json.dumps({"status": "unknown_command", "command": args.command, "hint": "run 'orderflow --list' to see available commands"}))
        return 2
    module_name, function_name = target.split(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        print(json.dumps({"status": "import_failed", "command": args.command, "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2
    entry = getattr(module, function_name, None)
    if entry is None:
        print(json.dumps({"status": "missing_entry_point", "command": args.command, "target": target}))
        return 2
    try:
        accepts_argv = len(inspect.signature(entry).parameters) > 0
    except (TypeError, ValueError):
        accepts_argv = True
    if accepts_argv:
        result = entry(args.args)
    else:
        original_argv = sys.argv
        sys.argv = [command, *args.args]
        try:
            result = entry()
        finally:
            sys.argv = original_argv
    return 0 if result is None else int(result)


if __name__ == "__main__":
    raise SystemExit(main())
