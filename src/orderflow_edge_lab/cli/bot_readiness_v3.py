"""Dispatcher for the offline, non-authoritative v3 bot-readiness CLI."""

from orderflow_edge_lab.bot_readiness_v3 import main

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
