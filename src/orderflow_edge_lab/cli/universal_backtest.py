from __future__ import annotations

import argparse
import json
from pathlib import Path
import pandas as pd

from orderflow_edge_lab.universal_backtest import legacy_strategy, run_sweep


def _load_dir(path: Path) -> dict[str, pd.DataFrame]:
    out={}
    for p in sorted(path.glob("*.csv")):
        f=pd.read_csv(p)
        if "timestamp" not in f.columns:
            continue
        f["timestamp"]=pd.to_datetime(f["timestamp"],utc=True,errors="coerce")
        f=f.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()
        out[p.stem]=f
    if not out:
        raise SystemExit(f"no timestamped CSV files found in {path}")
    return out


def main() -> None:
    ap=argparse.ArgumentParser(description="Universal multi-symbol backtest runner")
    ap.add_argument("--data-dir",required=True)
    ap.add_argument("--family",required=True)
    ap.add_argument("--grid-json",required=True,help='JSON parameter grid, e.g. {"lookback":[20,55]}')
    ap.add_argument("--costs",default="12,16,20")
    ap.add_argument("--slippage-bps",type=float,default=0.0)
    ap.add_argument("--output",required=True)
    args=ap.parse_args()
    frames=_load_dir(Path(args.data_dir))
    grid=json.loads(args.grid_json)
    costs=[float(x) for x in args.costs.split(",") if x.strip()]
    report=run_sweep(frames,legacy_strategy(args.family),grid,costs,slippage_bps_per_turnover_unit=args.slippage_bps)
    target=Path(args.output)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({"strategy_id":report["strategy_id"],"trial_count":report["trial_count"],"output":str(target)},indent=2))


if __name__=="__main__":
    main()
