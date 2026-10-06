"""Offline development-only candidate command; no data collection or routing."""
from orderflow_edge_lab.development_strategy_candidates_v1 import main


if __name__ == '__main__':
    raise SystemExit(main())
