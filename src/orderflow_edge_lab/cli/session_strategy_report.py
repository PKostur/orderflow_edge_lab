from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.session_strategy_report import (
    SessionStrategyReportError,
    build_session_strategy_report,
    load_aggregate,
)


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description="Summarize strategy economics by trading-session regime.")
    p.add_argument("condition_aggregate")
    p.add_argument("--output",required=True)
    args=p.parse_args(argv)
    try:
        aggregate=load_aggregate(args.condition_aggregate)
        report=build_session_strategy_report(aggregate)
        out=Path(args.output)
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
        print(out)
        return 0
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError,SessionStrategyReportError) as exc:
        print(json.dumps({"status":"failed","error_type":type(exc).__name__,"reason":str(exc)}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
