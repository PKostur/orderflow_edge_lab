"""Descriptive clock attribution for retained, unchanged public v1 signals."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from .public_strategy_shadow import is_signal, read_bars, sha256_file, utc, validate_spec

# Fixed UTC point-label conventions, not exchange hours or a signal filter.
SESSION_WINDOWS = {"Asia": (0, 9), "London": (7, 16), "New_York": (13, 22)}


def clock_counts(stamps: list[datetime]) -> dict:
    hours = Counter(str(t.hour) for t in stamps)
    memberships = Counter()
    regions = Counter()
    for stamp in stamps:
        active = [name for name, (start, stop) in SESSION_WINDOWS.items() if start <= stamp.hour < stop]
        memberships["+".join(active) or "outside_declared_windows"] += 1
        regions.update(active)
    return {"n": len(stamps), "utc_hour_counts": dict(sorted(hours.items(), key=lambda x: int(x[0]))),
            "nonexclusive_session_counts": dict(sorted(regions.items())),
            "exclusive_membership_counts": dict(sorted(memberships.items()))}


def audit_sessions(spec: dict, exact: dict, data_dir: Path) -> dict:
    validate_spec(spec, prospective=False)
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":"),
                                       allow_nan=False).encode()).hexdigest()
    if digest != exact["specification_sha256"]:
        raise ValueError("retained specification mismatch")
    names = [spec["benchmark_symbol"], *spec["symbols"]]
    hashes = {s: sha256_file(data_dir / f"{s}.csv") for s in names}
    if hashes != exact["source_sha256"]:
        raise ValueError("retained source mismatch")
    step = timedelta(minutes=spec["bar_minutes"])
    frames = {s: read_bars(data_dir / f"{s}.csv", spec["bar_minutes"], utc(exact["as_of_utc"])) for s in names}
    if any([b.timestamp for b in frames[s]] != [b.timestamp for b in frames[names[0]]] for s in names):
        raise ValueError("unaligned source clocks")
    results = []
    for experiment, reference in zip(spec["experiments"], exact["experiments"], strict=True):
        if experiment["id"] != reference["experiment_id"]:
            raise ValueError("experiment identity mismatch")
        opens, closes = [], []
        signal_keys = set()
        for symbol in spec["symbols"]:
            for i in range(experiment["lookback_bars"], len(frames[symbol])):
                if is_signal(frames[symbol], i, experiment):
                    opening = frames[symbol][i].timestamp
                    opens.append(opening)
                    closes.append(opening + step)
                    signal_keys.add((symbol, opening + step))
        completed, pending = [], []
        for event in reference["events"]:
            signal, entry = utc(event["signal_time"]), utc(event["entry_time"])
            if signal != entry or (event["symbol"], signal) not in signal_keys:
                raise ValueError("event clock is not a retained completed-candle signal")
            (completed if event["status"] == "completed" else pending).append(entry)
        if (len(opens) != reference["signals_count"]
                or len(opens) != len(completed) + len(pending) + reference["overlap_skipped"]):
            raise ValueError("signal/event accounting mismatch")
        results.append({"experiment_id": experiment["id"], "overlap_skipped": reference["overlap_skipped"],
                        "all_signal_candle_open_clock": clock_counts(opens),
                        "all_signal_completion_clock": clock_counts(closes),
                        "completed_hypothetical_entry_clock": clock_counts(completed),
                        "pending_earliest_entry_clock": clock_counts(pending)})
    return {"status": "DESCRIPTIVE_COMPLETION_AUDIT_ONLY", "specification_sha256": digest,
            "source_sha256": hashes, "session_windows_utc_start_inclusive_end_exclusive": SESSION_WINDOWS,
            "clock_note": "Signal is knowable at the 8h candle completion, identical to earliest next-open entry. Candle-open attribution is retrospective and never an executable signal time.",
            "session_note": "Fixed UTC point memberships only, without DST adjustment. Session counts are nonexclusive; membership counts are exclusive. They do not identify intrabar signal time, fill sequence or within-candle overlap performance. No filter is selected.",
            "historical_volatility_split_note": "Original diagnostics used sample stdev of 29 prior 8h log returns at 2.5%, although its note said 30. Original regime groups and outputs are preserved; no new split or strategy is fit.",
            "new_trading_cells": 0, "verified_out_of_sample_evidence": False,
            "deployment_eligible": False, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--exact-report", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_sessions(json.loads(args.config.read_bytes()), json.loads(args.exact_report.read_bytes()), args.data_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
