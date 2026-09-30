from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.mexc_session_research import MexcSessionStudyConfig, run_mexc_session_study


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description="Analyze MEXC futures market behavior by Asia, London and New York sessions.")
    p.add_argument("--start",required=True,help="UTC start, e.g. 2026-08-23T00:00:00Z")
    p.add_argument("--end",required=True,help="UTC end, exclusive")
    p.add_argument("--symbol",action="append",dest="symbols")
    p.add_argument("--interval",default="15m",choices=("5m","15m","1h"))
    p.add_argument("--output",required=True)
    args=p.parse_args(argv)
    cfg=MexcSessionStudyConfig(symbols=tuple(args.symbols or ("ENA_USDT","BTC_USDT")),interval=args.interval)
    result=run_mexc_session_study(args.start,args.end,cfg)
    out=Path(args.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
    print(out)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
