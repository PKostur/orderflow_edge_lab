from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from orderflow_edge_lab.btc_correlation import CorrelationPanelConfig, build_correlation_panel


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a PnL-independent MEXC research panel diversified by BTC return correlation."
    )
    parser.add_argument("screen", help="Compatibility pair-screen JSON produced by orderflow-pair-screen")
    parser.add_argument("--context-symbol", default="BTC_USDT")
    parser.add_argument("--interval", default="Min5")
    parser.add_argument("--lookback-hours", type=int, default=72)
    parser.add_argument("--min-samples", type=int, default=200)
    parser.add_argument("--panel-size", type=int, default=6)
    parser.add_argument("--high-positive-min", type=float, default=0.65)
    parser.add_argument("--low-absolute-max", type=float, default=0.25)
    parser.add_argument("--high-target", type=int, default=2)
    parser.add_argument("--low-target", type=int, default=2)
    parser.add_argument("--rest-base", default="https://api.mexc.com")
    parser.add_argument("--request-pause-seconds", type=float, default=0.12)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    screen_path = Path(args.screen)
    screen_bytes = screen_path.read_bytes()
    screen = json.loads(screen_bytes.decode("utf-8"))
    report = build_correlation_panel(
        screen,
        CorrelationPanelConfig(
            context_symbol=args.context_symbol,
            interval=args.interval,
            lookback_hours=args.lookback_hours,
            min_samples=args.min_samples,
            panel_size=args.panel_size,
            high_positive_min=args.high_positive_min,
            low_absolute_max=args.low_absolute_max,
            high_target=args.high_target,
            low_target=args.low_target,
            rest_base=args.rest_base,
            request_pause_seconds=args.request_pause_seconds,
        ),
    )
    report["source_screen_sha256"] = hashlib.sha256(screen_bytes).hexdigest()
    report["source_screen_selection_rule"] = screen.get("selection_rule")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
