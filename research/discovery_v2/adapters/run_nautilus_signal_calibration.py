from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from nautilus_trader.indicators import ExponentialMovingAverage, SimpleMovingAverage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    protocol = json.loads(Path(args.config).read_text(encoding="utf-8"))
    strat = protocol["strategy"]
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    summary = {}

    for symbol in protocol["data"]["symbols"]:
        path = Path(args.data_dir) / f"{symbol}_{protocol['data']['interval']}.csv"
        frame = pd.read_csv(path)
        ts_col = frame.columns[0]
        timestamps = pd.to_datetime(frame[ts_col], utc=True)
        close = frame["close"].astype(float).to_numpy()
        high = frame["high"].astype(float).to_numpy()
        low = frame["low"].astype(float).to_numpy()

        fast = ExponentialMovingAverage(int(strat["fast_ema"]))
        slow = ExponentialMovingAverage(int(strat["slow_ema"]))
        atr = SimpleMovingAverage(int(strat["atr_period"]))
        threshold = float(strat["min_atr_spread"])

        targets: list[float] = []
        previous_close = np.nan
        for i in range(len(frame)):
            c = float(close[i])
            h = float(high[i])
            l = float(low[i])
            tr = abs(h - l)
            if np.isfinite(previous_close):
                tr = max(tr, abs(h - previous_close), abs(l - previous_close))
            fast.update_raw(c)
            slow.update_raw(c)
            atr.update_raw(tr)
            if i + 1 < int(strat["slow_ema"]) or i + 1 < int(strat["atr_period"]):
                target = 0.0
            else:
                atr_value = float(atr.value)
                score = (float(fast.value) - float(slow.value)) / atr_value if atr_value != 0.0 else np.nan
                target = 1.0 if score > threshold else (-1.0 if score < -threshold else 0.0)
            targets.append(target)
            previous_close = c

        result = pd.DataFrame({
            "timestamp": timestamps,
            "raw_target": np.asarray(targets, dtype=float),
        })
        result["execution_target"] = result["raw_target"].shift(1).fillna(0.0).astype(float)
        result.to_csv(outdir / f"{symbol}_nautilus.csv", index=False)
        summary[symbol] = {
            "bars": int(len(result)),
            "long_targets": int((result["raw_target"] == 1.0).sum()),
            "short_targets": int((result["raw_target"] == -1.0).sum()),
            "flat_targets": int((result["raw_target"] == 0.0).sum()),
        }

    import nautilus_trader
    payload = {"engine": "nautilus_trader", "version": getattr(nautilus_trader, "__version__", "unknown"), "symbols": summary}
    (outdir / "nautilus_summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
