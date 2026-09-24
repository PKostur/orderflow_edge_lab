from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.mexc_capture_quality import (
    MexcCaptureQualityError,
    aggregate_capture_quality,
    audit_mexc_feature_capture,
)


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description="Audit MEXC order-flow capture integrity.")
    sub=parser.add_subparsers(dest="command",required=True)
    audit=sub.add_parser("audit")
    audit.add_argument("features")
    audit.add_argument("--config",required=True)
    audit.add_argument("--output",required=True)
    aggregate=sub.add_parser("aggregate")
    aggregate.add_argument("reports",nargs="+")
    aggregate.add_argument("--output",required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=="audit":
            cfg=json.loads(Path(args.config).read_text(encoding="utf-8"))
            result=audit_mexc_feature_capture(args.features,cfg)
        else:
            result=aggregate_capture_quality(args.reports)
        out=Path(args.output)
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
        print(json.dumps({
            "analysis":result["analysis"],
            "status":result.get("status"),
            "report_count":result.get("report_count"),
            "status_counts":result.get("status_counts"),
            "reconnects":result.get("reconnects",result.get("total_reconnects")),
        },indent=2,sort_keys=True))
        return 0
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError,MexcCaptureQualityError) as exc:
        print(json.dumps({"status":"failed","error_type":type(exc).__name__,"reason":str(exc)}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
