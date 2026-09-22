from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.session_excursion_aggregate import (
    SessionExcursionAggregateError,
    aggregate_session_excursions,
)


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description="Aggregate historical order-flow MFE/MAE by trading-session context.")
    p.add_argument("history_dir")
    p.add_argument("--horizon-ms",type=int,default=30000)
    p.add_argument("--fee-bps",type=float,default=4.0)
    p.add_argument("--rr-target",type=float,default=3.0)
    p.add_argument("--risk-fraction",type=float,default=0.0025)
    p.add_argument("--output",required=True)
    args=p.parse_args(argv)
    try:
        report=aggregate_session_excursions(
            args.history_dir,
            horizon_ms=args.horizon_ms,
            fee_bps=args.fee_bps,
            rr_target=args.rr_target,
            risk_fraction=args.risk_fraction,
        )
        out=Path(args.output)
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
        print(out)
        return 0
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError,SessionExcursionAggregateError) as exc:
        print(json.dumps({"status":"failed","error_type":type(exc).__name__,"reason":str(exc)}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
