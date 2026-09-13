from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.sentiment_monitor import merge_sentiment_ledgers, monitor_sentiment


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _symbols_from_panel(path: str | None) -> list[str]:
    if not path:
        return []
    payload = _load_json(path)
    values = payload.get("selected_symbols", [])
    if not isinstance(values, list):
        raise ValueError("panel selected_symbols must be a list")
    return [str(value).upper() for value in values]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect deterministic public-headline sentiment as observational market-state evidence."
    )
    parser.add_argument("--symbol", action="append", default=[])
    parser.add_argument("--panel", help="Optional PnL-independent correlation-panel JSON")
    parser.add_argument("--protocol", default="config/sentiment_monitor_v1.json")
    parser.add_argument("--prior-ledger", help="Optional previous cumulative sentiment ledger")
    parser.add_argument("--snapshot-output", required=True)
    parser.add_argument("--output", required=True, help="Cumulative sentiment ledger output")
    args = parser.parse_args()

    protocol = _load_json(args.protocol)
    symbols = [str(value).upper() for value in args.symbol]
    symbols.extend(_symbols_from_panel(args.panel))
    context_symbol = str(protocol["market_behavior"]["context_symbol"]).upper()
    symbols.extend([context_symbol, "ENA_USDT"])
    symbols = sorted(set(symbols))

    snapshot = monitor_sentiment(symbols, protocol)
    prior = None
    if args.prior_ledger and Path(args.prior_ledger).exists():
        prior = _load_json(args.prior_ledger)
    ledger = merge_sentiment_ledgers(prior, snapshot, protocol)

    snapshot_output = Path(args.snapshot_output)
    snapshot_output.parent.mkdir(parents=True, exist_ok=True)
    snapshot_output.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(ledger, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "snapshot_output": str(snapshot_output),
                "ledger_output": str(output),
                "snapshot_events": snapshot["summary"]["event_count"],
                "cumulative_events": ledger["summary"]["event_count"],
                "independent_event_clusters": ledger["summary"]["independent_event_cluster_count"],
                "state_screen_ready": ledger["summary"]["state_screen_ready"],
                "sentiment_is_strategy_filter": ledger["claims"]["sentiment_is_strategy_filter"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
