from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.discovery_screen import (
    DEFAULT_MULTIPLIERS,
    DiscoveryScreenError,
    build_discovery_screen,
    discovery_screen_markdown,
    load_observation_rows,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Discovery-time economics screen: would a candidate clear the declared round-trip cost, and "
            "does the declared cost match friction measured from recorded quotes? The screen threshold is "
            "required from the caller; this tool declares none."
        )
    )
    parser.add_argument("observations", help="JSON-lines or JSON array with gross_bps and cost_bps per row.")
    parser.add_argument(
        "--declared-round-trip-cost-bps",
        type=float,
        required=True,
        help="The frozen round-trip cost this candidate is being screened against.",
    )
    parser.add_argument(
        "--minimum-break-even-ratio",
        type=float,
        required=True,
        help="Caller-declared break-even multiple the candidate must reach.",
    )
    parser.add_argument(
        "--cost-multipliers",
        help=f"Comma-separated friction multipliers (default: {','.join(str(m) for m in DEFAULT_MULTIPLIERS)}).",
    )
    parser.add_argument("--friction-quotes", help="Optional JSON-lines quote file with spread_bps or bid/ask.")
    parser.add_argument(
        "--fee-bps-per-side",
        type=float,
        help="Fee per side; required when --friction-quotes is supplied.",
    )
    parser.add_argument("--spread-field", default="spread_bps", help="Quote field holding the spread in bps.")
    parser.add_argument("--output", help="Optional path for an exclusive-create JSON report.")
    parser.add_argument("--markdown", help="Optional path for a human-readable report.")
    return parser


def _write_exclusive(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()


def _load_quotes(path: str):
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise DiscoveryScreenError(f"cannot read friction quotes: {target}") from exc
    if text.lstrip().startswith("["):
        payload = json.loads(text)
        return [dict(row) for row in payload if isinstance(row, dict)]
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        multipliers = DEFAULT_MULTIPLIERS
        if args.cost_multipliers:
            multipliers = tuple(float(part) for part in args.cost_multipliers.split(",") if part.strip())
        rows = load_observation_rows(args.observations)
        friction_rows = _load_quotes(args.friction_quotes) if args.friction_quotes else None
        report = build_discovery_screen(
            rows,
            declared_round_trip_cost_bps=float(args.declared_round_trip_cost_bps),
            minimum_break_even_ratio=float(args.minimum_break_even_ratio),
            multipliers=multipliers,
            friction_rows=friction_rows,
            fee_bps_per_side=args.fee_bps_per_side,
            spread_field=args.spread_field,
        )
        if args.output:
            _write_exclusive(
                Path(args.output),
                json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
            )
        if args.markdown:
            _write_exclusive(Path(args.markdown), discovery_screen_markdown(report))
        print(json.dumps(report, sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, DiscoveryScreenError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
