"""Versioned, package-owned operator-command registry.

The JSON registry is installed as package data and is the only public command
inventory for dispatcher, packaging, documentation checks, and wheel smoke.
It declares compatibility aliases rather than deleting historical names.
"""
from __future__ import annotations

from collections.abc import Mapping
from importlib import resources
import json
from typing import Any

SCHEMA = "orderflow_edge_lab.command_registry.v2"


class CommandRegistryError(ValueError):
    pass


def load_command_registry() -> dict[str, Any]:
    try:
        raw = json.loads(resources.files("orderflow_edge_lab").joinpath("command_registry_v2.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise CommandRegistryError("command registry is unreadable") from exc
    if not isinstance(raw, Mapping) or raw.get("schema") != SCHEMA or raw.get("version") != 2:
        raise CommandRegistryError("command registry schema is unsupported")
    commands = raw.get("commands")
    if not isinstance(commands, list) or not commands:
        raise CommandRegistryError("command registry commands must be nonempty")
    names: set[str] = set()
    modules: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for item in commands:
        if not isinstance(item, Mapping):
            raise CommandRegistryError("command registry entry must be an object")
        expected = {"name", "target", "module", "exposure", "safe_probe", "deprecated"}
        if set(item) != expected or not isinstance(item.get("name"), str) or not item["name"].startswith("orderflow"):
            raise CommandRegistryError("command registry entry shape is invalid")
        if item["name"] in names:
            raise CommandRegistryError(f"duplicate command name: {item['name']}")
        names.add(item["name"])
        if not isinstance(item.get("target"), str) or ":main" not in item["target"]:
            raise CommandRegistryError(f"invalid target for {item['name']}")
        if not isinstance(item.get("module"), str) or not item["module"]:
            raise CommandRegistryError(f"invalid module for {item['name']}")
        if item["exposure"] not in {"flat", "dispatcher", "gui", "internal"}:
            raise CommandRegistryError(f"invalid exposure for {item['name']}")
        if not isinstance(item["safe_probe"], str) or not isinstance(item["deprecated"], bool):
            raise CommandRegistryError(f"invalid probe/deprecation fields for {item['name']}")
        if item["module"].startswith("orderflow_edge_lab.cli."):
            if item["module"] in modules:
                raise CommandRegistryError(f"CLI module classified more than once: {item['module']}")
            modules.add(item["module"])
        normalized.append(dict(item))
    normalized.sort(key=lambda item: item["name"])
    return {"schema": SCHEMA, "version": 2, "commands": normalized}


def dispatcher_commands() -> dict[str, str]:
    """Return command-to-CLI-module mappings explicitly declared as dispatchable."""
    return {item["name"]: item["module"].rsplit(".", 1)[1] for item in load_command_registry()["commands"]
            if item["exposure"] in {"flat", "dispatcher", "gui"}
            and item["module"].startswith("orderflow_edge_lab.cli.")
            and item["module"] != "orderflow_edge_lab.cli.main"}


def flat_entry_points() -> dict[str, str]:
    """Return the exact non-GUI flat console-script metadata expected in a wheel."""
    return {item["name"]: item["target"] for item in load_command_registry()["commands"] if item["exposure"] == "flat"}


def gui_entry_points() -> dict[str, str]:
    return {item["name"]: item["target"] for item in load_command_registry()["commands"] if item["exposure"] == "gui"}


def validate_command_metadata(
    project_scripts: Mapping[str, str], gui_scripts: Mapping[str, str], discovered_cli_modules: set[str]
) -> dict[str, int]:
    """Fail closed when packaging or module discovery drifts from the registry.

    This pure checker is consumed by focused tests and the installed-wheel smoke
    path.  It accepts caller-supplied metadata so it never reads a checkout or
    contacts a package index.
    """
    registry = load_command_registry()
    expected_flat = flat_entry_points()
    expected_gui = gui_entry_points()
    if dict(project_scripts) != expected_flat:
        raise CommandRegistryError("project console-script metadata differs from command registry")
    if dict(gui_scripts) != expected_gui:
        raise CommandRegistryError("project gui-script metadata differs from command registry")
    expected_modules = {
        item["module"].rsplit(".", 1)[1]
        for item in registry["commands"]
        if item["module"].startswith("orderflow_edge_lab.cli.")
    }
    if set(discovered_cli_modules) != expected_modules:
        raise CommandRegistryError("CLI module set contains an unclassified or missing module")
    return {"commands": len(registry["commands"]), "flat": len(expected_flat), "gui": len(expected_gui), "cli_modules": len(expected_modules)}
