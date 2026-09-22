from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.session_watch import (
    SessionWatchError,
    build_session_watch_report,
    load_json,
)


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description="Evaluate prospective session-development watches from a cumulative condition aggregate.")
    p.add_argument("condition_aggregate")
    p.add_argument("--watch-config",default="config/session_development_watch_v1.json")
    p.add_argument("--output",required=True)
    args=p.parse_args(argv)
    try:
        aggregate=load_json(args.condition_aggregate)
        config=load_json(args.watch_config)
        report=build_session_watch_report(aggregate,config)
        out=Path(args.output)
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
        print(out)
        return 0
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError,SessionWatchError) as exc:
        print(json.dumps({"status":"failed","error_type":type(exc).__name__,"reason":str(exc)}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
