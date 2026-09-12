from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.news_monitor import NewsMonitorConfig, monitor_news


def _symbols_from_panel(path: str | None) -> list[str]:
    if not path:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    values = payload.get("selected_symbols", [])
    if not isinstance(values, list):
        raise ValueError("panel selected_symbols must be a list")
    return [str(value).upper() for value in values]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect public coin-news headlines and measure subsequent coin/BTC market behavior for research context."
    )
    parser.add_argument("--symbol", action="append", default=[])
    parser.add_argument("--panel", help="Optional correlation-panel JSON whose selected symbols should be monitored")
    parser.add_argument("--context-symbol", default="BTC_USDT")
    parser.add_argument("--interval", default="Min5")
    parser.add_argument("--max-age-hours", type=int, default=48)
    parser.add_argument("--pre-event-minutes", type=int, default=15)
    parser.add_argument("--horizons-minutes", default="5,15,30,60")
    parser.add_argument("--rest-base", default="https://api.mexc.com")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    horizons = tuple(int(value.strip()) for value in args.horizons_minutes.split(",") if value.strip())
    symbols = [str(value).upper() for value in args.symbol]
    symbols.extend(_symbols_from_panel(args.panel))
    symbols.extend([args.context_symbol.upper(), "ENA_USDT"])
    report = monitor_news(
        symbols,
        NewsMonitorConfig(
            context_symbol=args.context_symbol.upper(),
            interval=args.interval,
            max_age_hours=args.max_age_hours,
            pre_event_minutes=args.pre_event_minutes,
            behavior_horizons_minutes=horizons,
            rest_base=args.rest_base,
        ),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
