from __future__ import annotations

import argparse
import json
from pathlib import Path

from orderflow_edge_lab.evidence_v2_session_audit import (
    EvidenceSessionAuditError,
    load_config,
    run_evidence_session_audit,
)


def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(description="Run frozen evidence-v2 session audit.")
    p.add_argument("--config",default="config/evidence_v2_session_audit_v1.json")
    p.add_argument("--data-4h",required=True)
    p.add_argument("--data-8h",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args(argv)
    try:
        cfg=load_config(args.config)
        report=run_evidence_session_audit(
            cfg,
            data_dirs={"4h":args.data_4h,"8h":args.data_8h},
        )
        out=Path(args.output)
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
        print(out)
        return 0
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError,EvidenceSessionAuditError) as exc:
        print(json.dumps({"status":"failed","error_type":type(exc).__name__,"reason":str(exc)}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
