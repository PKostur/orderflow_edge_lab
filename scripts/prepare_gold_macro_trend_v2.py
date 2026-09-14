from __future__ import annotations
import argparse, hashlib, json, time
from pathlib import Path
import pandas as pd
import requests
import yfinance as yf

YAHOO = {
    'gold': 'GC=F',
    'silver': 'SI=F',
}
FRED = {
    'real_yield': 'DFII10',
    'nominal_yield': 'DGS10',
    'broad_usd': 'DTWEXBGS',
}

def sha(path: Path) -> str:
    h=hashlib.sha256(); h.update(path.read_bytes()); return h.hexdigest()

def get(url: str, tries: int = 5) -> bytes:
    last=None
    for attempt in range(tries):
        try:
            r=requests.get(url,timeout=(20,45),headers={'User-Agent':'orderflow-edge-lab/1.0'})
            r.raise_for_status()
            if len(r.content) < 100:
                raise RuntimeError(f'implausibly short response: {len(r.content)} bytes')
            return r.content
        except Exception as exc:
            last=exc
            time.sleep(2.0*(attempt+1))
    raise RuntimeError(f'download failed after {tries} attempts: {url}: {last}')

def fetch_yahoo(symbol: str) -> pd.DataFrame:
    d=yf.download(symbol,start='2009-01-01',end='2024-01-01',interval='1d',auto_adjust=False,actions=False,progress=False,threads=False)
    if isinstance(d.columns,pd.MultiIndex): d.columns=[str(x[0]).lower() for x in d.columns]
    else: d.columns=[str(x).lower() for x in d.columns]
    d=d.reset_index(); d.columns=[str(c).lower() for c in d.columns]
    if 'date' not in d.columns and 'datetime' in d.columns: d=d.rename(columns={'datetime':'date'})
    need=['date','open','high','low','close']
    if not all(c in d.columns for c in need): raise RuntimeError(f'{symbol} missing columns: {list(d.columns)}')
    d=d[need].copy(); d['date']=pd.to_datetime(d['date'],utc=True,errors='coerce')
    for c in ['open','high','low','close']: d[c]=pd.to_numeric(d[c],errors='coerce')
    return d.dropna().sort_values('date')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--output-dir',required=True); args=ap.parse_args()
    out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    manifest={'schema_version':3,'source_amendment':'gold-macro-trend-v2.1-source-amendment','engineering_repairs':['bounded FRED date requests','transport retry/backoff'],'source_files':{}}
    filenames={'gold':'gold_stooq_daily.csv','silver':'silver_stooq_daily.csv'}
    for name,symbol in YAHOO.items():
        d=fetch_yahoo(symbol)
        if len(d)<2500: raise SystemExit(f'{name} too short: {len(d)}')
        p=out/filenames[name]; d.to_csv(p,index=False)
        manifest['source_files'][name]={'provider':'Yahoo Finance via yfinance','symbol':symbol,'instrument_semantics':'continuous front futures proxy','rows':int(len(d)),'first':str(d.date.min()),'last':str(d.date.max()),'sha256':sha(p)}
    for name,series in FRED.items():
        url=f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd=2009-01-01&coed=2023-12-31'
        p=out/f'{name}_{series}.csv'; p.write_bytes(get(url))
        d=pd.read_csv(p)
        if len(d)<2500: raise SystemExit(f'{series} too short: {len(d)}')
        dt=pd.to_datetime(d.iloc[:,0],errors='coerce',utc=True)
        vals=pd.to_numeric(d.iloc[:,1].replace('.',pd.NA),errors='coerce') if d.shape[1] > 1 else pd.Series(dtype=float)
        if dt.notna().sum()<2500 or vals.notna().sum()<1800:
            raise SystemExit(f'{series} data integrity failure: rows={len(d)}, dates={int(dt.notna().sum())}, values={int(vals.notna().sum())}')
        manifest['source_files'][name]={'series':series,'url':url,'rows':int(len(d)),'non_null_values':int(vals.notna().sum()),'first':str(dt.min()),'last':str(dt.max()),'sha256':sha(p)}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest,indent=2))
if __name__=='__main__': main()
