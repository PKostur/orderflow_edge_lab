from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import pandas as pd
import requests
import yfinance as yf

YAHOO = {
    'gold': 'GC=F',
    'silver': 'SI=F',
}
MACRO = {
    'real_yield': {
        'series': 'DFII10',
        'url': 'https://raw.githubusercontent.com/Arqaen/financial-forecasting-xgboost/0df20d1021807d8e89fa46a6f026806bebaa9123/models/data/DFII10.csv',
    },
    'nominal_yield': {
        'series': 'DGS10',
        'url': 'https://raw.githubusercontent.com/Arqaen/financial-forecasting-xgboost/0df20d1021807d8e89fa46a6f026806bebaa9123/models/data/DGS10.csv',
    },
    'broad_usd': {
        'series': 'DTWEXBGS',
        'url': 'https://raw.githubusercontent.com/Lilas-Bertot/ETUDE-DE-CAS-2/3c957c05a93a5398b67271783cd6a32ae0214385/DXY.csv',
    },
}

def sha(path: Path) -> str:
    h=hashlib.sha256(); h.update(path.read_bytes()); return h.hexdigest()

def get(url: str) -> bytes:
    r=requests.get(url,timeout=(20,45),headers={'User-Agent':'orderflow-edge-lab/1.0'})
    r.raise_for_status()
    if len(r.content)<100: raise RuntimeError(f'implausibly short response from {url}: {len(r.content)} bytes')
    return r.content

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
    manifest={'schema_version':4,'source_amendment':'gold-macro-trend-v2.2-macro-mirror-amendment','source_files':{}}
    filenames={'gold':'gold_stooq_daily.csv','silver':'silver_stooq_daily.csv'}
    for name,symbol in YAHOO.items():
        d=fetch_yahoo(symbol)
        if len(d)<2500: raise SystemExit(f'{name} too short: {len(d)}')
        p=out/filenames[name]; d.to_csv(p,index=False)
        manifest['source_files'][name]={'provider':'Yahoo Finance via yfinance','symbol':symbol,'instrument_semantics':'continuous front futures proxy','rows':int(len(d)),'first':str(d.date.min()),'last':str(d.date.max()),'sha256':sha(p)}
    for name,spec in MACRO.items():
        series=spec['series']; p=out/f'{name}_{series}.csv'; p.write_bytes(get(spec['url']))
        d=pd.read_csv(p)
        if d.shape[1]<2 or str(d.columns[0]).strip().lower() not in {'observation_date','date'} or str(d.columns[1]).strip()!=series:
            raise SystemExit(f'{series} header integrity failure: {list(d.columns)}')
        dt=pd.to_datetime(d.iloc[:,0],errors='coerce',utc=True); vals=pd.to_numeric(d.iloc[:,1].replace('.',pd.NA),errors='coerce')
        dev=(dt>=pd.Timestamp('2010-01-01',tz='UTC'))&(dt<pd.Timestamp('2021-01-01',tz='UTC'))
        nonnull_dev=int(vals[dev].notna().sum())
        if int(dt.notna().sum())<2500 or nonnull_dev<1800 or dt.max()<pd.Timestamp('2021-01-01',tz='UTC'):
            raise SystemExit(f'{series} data integrity failure: rows={len(d)}, dev_non_null={nonnull_dev}, last={dt.max()}')
        manifest['source_files'][name]={'series':series,'provider':'immutable GitHub mirror of FRED series','url':spec['url'],'rows':int(len(d)),'development_non_null_values':nonnull_dev,'first':str(dt.min()),'last':str(dt.max()),'sha256':sha(p)}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest,indent=2))
if __name__=='__main__': main()
