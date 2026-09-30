from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from orderflow_edge_lab.evidence_v2_session_forward import (
    EvidenceSessionForwardError,
    build_forward_session_report,
    load_config,
)
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description="Run prospective cross-strategy session watch.")
    p.add_argument("--config",default="config/evidence_v2_session_forward_watch_v1.json")
    p.add_argument("--output",required=True)
    p.add_argument("--source-dir",required=True)
    p.add_argument("--as-of",default=None)
    p.add_argument("--max-workers",type=int,default=5)
    args=p.parse_args(argv)
    try:
        cfg=load_config(args.config)
        as_of=pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp.now(tz="UTC")
        as_of=as_of.tz_localize("UTC") if as_of.tzinfo is None else as_of.tz_convert("UTC")
        warmup=str(cfg["source"]["warmup_start_utc"])
        symbols=[str(x) for x in cfg["source"]["symbols"]]
        intervals=sorted({str(v["interval"]) for v in cfg["variants"]})
        source_dir=Path(args.source_dir)
        source_dir.mkdir(parents=True,exist_ok=True)

        frames_by_interval={interval:{} for interval in intervals}
        source_hashes={}

        def load(interval:str,symbol:str):
            frame=fetch_mexc_futures_klines(symbol,interval,warmup,as_of.isoformat())
            return interval,symbol,frame

        jobs=[]
        with ThreadPoolExecutor(max_workers=max(1,min(int(args.max_workers),len(symbols)*len(intervals)))) as pool:
            futures={}
            for interval in intervals:
                for symbol in symbols:
                    fut=pool.submit(load,interval,symbol)
                    futures[fut]=(interval,symbol)
            for future in as_completed(futures):
                interval,symbol=futures[future]
                got_interval,got_symbol,frame=future.result()
                if got_interval!=interval or got_symbol!=symbol:
                    raise EvidenceSessionForwardError("source identity mismatch")
                frames_by_interval[interval][symbol]=frame
                path=source_dir/f"{symbol}_{interval}.csv"
                frame.to_csv(path,index_label="timestamp")
                source_hashes[f"{symbol}:{interval}"]=sha256(path.read_bytes()).hexdigest()

        report=build_forward_session_report(
            cfg,
            frames_by_interval=frames_by_interval,
            as_of_utc=as_of,
        )
        report["source_sha256"]=source_hashes
        out=Path(args.output)
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
        print(json.dumps({
            "watch_id":report["watch_id"],
            "status":report["status"],
            "as_of_utc":report["as_of_utc"],
            "days_elapsed":report["days_elapsed"],
            "primary_observation":report["primary_observation"],
        },indent=2))
        return 0
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError,EvidenceSessionForwardError) as exc:
        print(json.dumps({"status":"failed","error_type":type(exc).__name__,"reason":str(exc)}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
