"""Record a prospective LSK capture attempt before any market outcomes exist."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',default='artifacts/lsk/attempts')
    p.add_argument('--freeze',default='config/lsk_conditional_regime_v1.freeze.json')
    args=p.parse_args()
    freeze=Path(args.freeze).resolve()
    attempt=Path(args.root).resolve()/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    attempt.mkdir(parents=True,exist_ok=False)
    record=dict(attempt_id=attempt.name,registered_at_ns=time.time_ns(),duration_seconds=1200,
                freeze=str(freeze),status='registered_before_capture',ready_for_live=False)
    def save(): (attempt/'attempt.json').write_text(json.dumps(record,indent=2)+'\n')
    save()
    try:
        subprocess.run([sys.executable,'-m','orderflow_edge_lab.lsk_conditional_regime','--mode','forward','--freeze',str(freeze),'--output',str(attempt/'preflight.json')],check=True)
        record['status']='capturing'; record['capture_started_at_ns']=time.time_ns(); save()
        subprocess.run([sys.executable,'-m','orderflow_edge_lab.cli.mexc_record','--symbol','LSK_USDT','--symbol','BTC_USDT','--duration-seconds','1200','--output-dir',str(attempt/'capture')],check=True)
        features=list((attempt/'capture').glob('*_mexc_features.jsonl'))
        if len(features)!=1: raise RuntimeError('expected exactly one feature replay')
        record['status']='evaluating_frozen_rule'; record['feature_file']=str(features[0]); save()
        subprocess.run([sys.executable,'-m','orderflow_edge_lab.lsk_conditional_regime',str(features[0]),'--mode','forward','--freeze',str(freeze),'--output',str(attempt/'forward.json')],check=True)
        record['status']='completed_temporally_eligible_not_promoted'
    except BaseException as exc:
        record['status']='failed'; record['error_type']=type(exc).__name__
        raise
    finally:
        record['finished_at_ns']=time.time_ns(); save()
    print(json.dumps(record))


if __name__=='__main__': main()
