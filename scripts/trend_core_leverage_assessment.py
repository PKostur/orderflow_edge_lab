"""Run the registered trend-core leverage assessment (config/trend_core_leverage_assessment_v1.json) ONCE.

Writes research/trend_core_leverage/assessment_v1.json (mode "x": refuses to overwrite).  Descriptive; no orders.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from orderflow_edge_lab import trend_core_leverage as tcl  # noqa: E402

CORE_CONFIG = ROOT / "config" / "crypto_trend_core_v1.json"
STUDY_CONFIG = ROOT / "config" / "trend_core_leverage_assessment_v1.json"
OUTPUT = ROOT / tcl.RESULT_RELPATH


def main() -> int:
    if OUTPUT.exists():
        print(f"refusing to overwrite {OUTPUT}", file=sys.stderr)
        return 2
    core = json.loads(CORE_CONFIG.read_text(encoding="utf-8"))
    study = json.loads(STUDY_CONFIG.read_text(encoding="utf-8"))
    mexc = [str(s) for s in core["groups"]["crypto"]]
    available, missing_from_cache = tcl.split_symbols(mexc)
    frames, funding, marks, dropped, ranges = {}, {}, {}, {}, {}
    fallback_counts: dict[str, dict[str, int]] = {}
    divergence: dict[str, dict] = {}
    for name, sym in available.items():
        perp = tcl.load_hourly(sym, "perp")
        bars, dropped[sym] = tcl.build_8h_bars(perp)
        frames[sym] = bars
        funding[sym] = tcl.load_funding(sym)
        raw_mark = tcl.load_hourly(sym, "mark")
        divergence[sym] = tcl.mark_perp_divergence(raw_mark, perp)
        mark, first_mark, fallback_counts[sym] = tcl.mark_with_fallback(raw_mark, perp)
        marks[sym] = mark
        ranges[sym] = {"first_8h_bar": str(bars.index[0]), "last_8h_bar": str(bars.index[-1]), "bars": int(len(bars)),
                       "incomplete_bars_dropped": dropped[sym],
                       "first_mark_bar_end": None if first_mark is None else str(first_mark),
                       "funding_rows": int(len(funding[sym])), "perp_fallback_mark_bars": fallback_counts[sym]}
    run_core = {**core, "source": {**core["source"], "symbols": list(available.values())}}
    result = tcl.assess(run_core, frames, funding, marks, rest_fetch=tcl.archive.http_fetch)
    first_marks = sorted(r["first_mark_bar_end"] for r in ranges.values() if r["first_mark_bar_end"] is not None)
    mark_note = ("mark-price klines are used where the mark archive has a bar; the perp 1h high/low stand in before a "
                 "symbol's first mark bar and for holes after it (counts per symbol in ranges[*].perp_fallback_mark_bars). "
                 f"First mark bar end per symbol: ranges[*].first_mark_bar_end (earliest {first_marks[0] if first_marks else None}, "
                 f"latest {first_marks[-1] if first_marks else None}; {len(ranges) - len(first_marks)} symbols without any mark bar)")
    payload = {
        "schema_version": 1, "study_id": study["study_id"], "status": "RESULT_DESCRIPTIVE_ONLY",
        "claims": study["claims"],
        "provenance": {
            "core_config_sha256": sha256(CORE_CONFIG.read_bytes()).hexdigest(),
            "study_config_sha256": sha256(STUDY_CONFIG.read_bytes()).hexdigest(),
            "symbols_used": available, "symbols_missing_from_cache": missing_from_cache, "ranges": ranges,
            "funding_coverage": result.pop("funding_coverage"),
            "funding_rest_verification": result.pop("funding_rest_verification"), "mark_vs_perp_divergence": divergence,
            "top_adverse_excursions_by_symbol": result.pop("top_adverse_excursions_by_symbol"),
            "input_sha256": tcl.input_digest(available),
            "mark_note": mark_note,
        },
        "result": result,
    }
    tcl.write_result(OUTPUT, payload)
    print(f"wrote {OUTPUT}; max safe leverage (registered reading) = {result['max_safe_leverage_registered']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
