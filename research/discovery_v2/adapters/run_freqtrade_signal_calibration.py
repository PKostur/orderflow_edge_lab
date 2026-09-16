from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pandas as pd


def _load_strategy(path: Path):
    spec = importlib.util.spec_from_file_location("frozen_ema_atr_freqtrade", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load Freqtrade strategy module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FrozenEmaAtrFreqtrade


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--strategy", default="research/discovery_v2/adapters/FrozenEmaAtrFreqtrade.py")
    args = parser.parse_args()

    protocol = json.loads(Path(args.config).read_text(encoding="utf-8"))
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    cls = _load_strategy(Path(args.strategy))
    strategy = cls({})
    summary = {}

    for symbol in protocol["data"]["symbols"]:
        path = Path(args.data_dir) / f"{symbol}_{protocol['data']['interval']}.csv"
        frame = pd.read_csv(path)
        ts_col = frame.columns[0]
        frame[ts_col] = pd.to_datetime(frame[ts_col], utc=True)
        frame = frame.rename(columns={ts_col: "date"})
        enriched = strategy.populate_indicators(frame.copy(), {"pair": symbol.replace("_", "/")})
        enriched = strategy.populate_entry_trend(enriched, {"pair": symbol.replace("_", "/")})
        enriched = strategy.populate_exit_trend(enriched, {"pair": symbol.replace("_", "/")})
        result = pd.DataFrame({
            "timestamp": pd.to_datetime(enriched["date"], utc=True),
            "raw_target": enriched["cal_target"].astype(float),
            "execution_target": enriched["cal_target"].shift(1).fillna(0.0).astype(float),
            "enter_long": enriched.get("enter_long", 0).fillna(0).astype(int),
            "enter_short": enriched.get("enter_short", 0).fillna(0).astype(int),
            "exit_long": enriched.get("exit_long", 0).fillna(0).astype(int),
            "exit_short": enriched.get("exit_short", 0).fillna(0).astype(int),
        })
        result.to_csv(outdir / f"{symbol}_freqtrade.csv", index=False)
        summary[symbol] = {
            "bars": int(len(result)),
            "long_targets": int((result["raw_target"] == 1.0).sum()),
            "short_targets": int((result["raw_target"] == -1.0).sum()),
            "flat_targets": int((result["raw_target"] == 0.0).sum()),
        }

    try:
        import freqtrade
        version = getattr(freqtrade, "__version__", "unknown")
    except Exception:
        version = "unknown"
    payload = {"engine": "freqtrade", "version": version, "symbols": summary}
    (outdir / "freqtrade_summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
