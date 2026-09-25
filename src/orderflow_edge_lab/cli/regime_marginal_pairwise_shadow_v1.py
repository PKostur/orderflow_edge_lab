from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines
from orderflow_edge_lab.regime_marginal_pairwise_shadow_v1 import (
    RegimeMarginalPairwiseShadowV1Error,
    build_shadow_report,
)


def _load(path: str | Path) -> dict:
    value=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value,dict):
        raise RegimeMarginalPairwiseShadowV1Error(f"{path}: expected JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    p=argparse.ArgumentParser(description="Run frozen prospective marginal/pairwise regime shadow v1.")
    p.add_argument("--config",required=True)
    p.add_argument("--anchor-binding",required=True)
    p.add_argument("--label-config",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--source-dir",required=True)
    p.add_argument("--as-of",default=None)
    p.add_argument("--max-workers",type=int,default=5)
    a=p.parse_args(argv)
    try:
        config=_load(a.config)
        binding=_load(a.anchor_binding)
        labels=_load(a.label_config)
        as_of=pd.Timestamp(a.as_of) if a.as_of else pd.Timestamp.now(tz="UTC")
        as_of=as_of.tz_localize("UTC") if as_of.tzinfo is None else as_of.tz_convert("UTC")
        source=config["source"]
        symbols=[str(v) for v in source["symbols"]]
        interval=str(source["interval"])
        warmup=str(source["warmup_start_utc"])
        root=Path(a.source_dir); root.mkdir(parents=True,exist_ok=True)
        frames={}
        hashes={}

        def load(symbol: str):
            return symbol,fetch_mexc_futures_klines(symbol,interval,warmup,as_of.isoformat())

        with ThreadPoolExecutor(max_workers=max(1,min(int(a.max_workers),len(symbols)))) as pool:
            futures={pool.submit(load,symbol):symbol for symbol in symbols}
            for future in as_completed(futures):
                expected=futures[future]
                symbol,frame=future.result()
                if symbol!=expected:
                    raise RegimeMarginalPairwiseShadowV1Error("source identity mismatch")
                frames[symbol]=frame
                path=root/f"{symbol}_{interval}.csv"
                frame.to_csv(path,index_label="timestamp")
                hashes[symbol]=sha256(path.read_bytes()).hexdigest()

        report=build_shadow_report(config,binding,labels,frames,as_of_utc=as_of)
        report["source_sha256"]=dict(sorted(hashes.items()))
        out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
        print(json.dumps({
            "watch_id":report["watch_id"],
            "status":report["status"],
            "prospective_start_utc":report["prospective_start_utc"],
            "as_of_utc":report["as_of_utc"],
            "calendar_days_elapsed":report["calendar_days_elapsed"],
            "inferential_window_open":report["inferential_window_open"],
            "historical_anchor_count":report["historical_anchor_count"],
            "completed_trades":{row["audit_id"]:row["completed_post_start_trade_count"] for row in report["reports"]},
            "open_snapshots":{row["audit_id"]:row["open_post_start_snapshot_count"] for row in report["reports"]},
        },indent=2,sort_keys=True))
        return 0
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError,RegimeMarginalPairwiseShadowV1Error) as exc:
        print(json.dumps({"status":"failed","error_type":type(exc).__name__,"reason":str(exc)}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
