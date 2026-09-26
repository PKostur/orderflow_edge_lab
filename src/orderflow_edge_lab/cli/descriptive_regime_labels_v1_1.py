from __future__ import annotations
import argparse,json
from pathlib import Path
from orderflow_edge_lab.descriptive_regime_labels_v1_1 import run_from_paths_v1_1

def main() -> None:
    p=argparse.ArgumentParser(description="Run descriptive 8h regime labels v1.1 with null-centered inference.")
    p.add_argument("--source-protocol",required=True); p.add_argument("--regime-config",required=True)
    p.add_argument("--data-dir",required=True); p.add_argument("--output",required=True)
    a=p.parse_args()
    r=run_from_paths_v1_1(a.source_protocol,a.regime_config,a.data_dir)
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
if __name__=="__main__": main()
