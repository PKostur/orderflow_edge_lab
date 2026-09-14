from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import pandas as pd
import requests

STOOQ = {
    'gold': 'https://stooq.com/q/d/l/?s=xauusd&i=d&d1=20090101&d2=20231231',
    'silver': 'https://stooq.com/q/d/l/?s=xagusd&i=d&d1=20090101&d2=20231231',
}
FRED = {
    'real_yield': 'DFII10',
    'nominal_yield': 'DGS10',
    'broad_usd': 'DTWEXBGS',
}

def sha(path: Path) -> str:
    h=hashlib.sha256(); h.update(path.read_bytes()); return h.hexdigest()

def get(url: str) -> bytes:
    r=requests.get(url,timeout=60,headers={'User-Agent':'orderflow-edge-lab/1.0'})
    r.raise_for_status(); return r.content

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--output-dir',required=True); args=ap.parse_args()
    out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    manifest={'schema_version':1,'source_files':{}}
    for name,url in STOOQ.items():
        p=out/f'{name}_stooq_daily.csv'; p.write_bytes(get(url))
        d=pd.read_csv(p)
        if len(d)<2500: raise SystemExit(f'{name} too short: {len(d)}')
        cols={c.lower():c for c in d.columns}
        required={'date','open','high','low','close'}
        if not required.issubset(cols): raise SystemExit(f'{name} missing columns {required-set(cols)}: {list(d.columns)}')
        dt=pd.to_datetime(d[cols['date']],errors='coerce',utc=True)
        if dt.notna().sum()<2500: raise SystemExit(f'{name} date parse failure')
        manifest['source_files'][name]={'url':url,'rows':int(len(d)),'first':str(dt.min()),'last':str(dt.max()),'sha256':sha(p)}
    for name,series in FRED.items():
        url=f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}'
        p=out/f'{name}_{series}.csv'; p.write_bytes(get(url))
        d=pd.read_csv(p)
        if len(d)<2500: raise SystemExit(f'{series} too short: {len(d)}')
        dt=pd.to_datetime(d.iloc[:,0],errors='coerce',utc=True)
        manifest['source_files'][name]={'series':series,'url':url,'rows':int(len(d)),'first':str(dt.min()),'last':str(dt.max()),'sha256':sha(p)}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest,indent=2))
if __name__=='__main__': main()
