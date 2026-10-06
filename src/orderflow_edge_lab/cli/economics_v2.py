"""Dispatcher delegator for the additive offline economics v2 CLI."""

from __future__ import annotations

from typing import Sequence

from orderflow_edge_lab.economics_v2 import main as _economics_main


def main(argv: Sequence[str] | None = None) -> int:
    """Delegate unchanged arguments to the offline economics v2 module CLI."""

    return _economics_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
