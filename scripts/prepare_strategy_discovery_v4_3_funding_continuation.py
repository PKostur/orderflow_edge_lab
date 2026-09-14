from __future__ import annotations
import argparse, json, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd, requests
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

BASE='https://api.mexc.com'; FUNDING=f'{BASE}/api/v1/contract/funding_rate/history'
SYMS=['BTC','TRX','ZEC','LTC','HYPE','TAO','NEAR','BCH','ASTER','DOT','XMR','XLM','ETHFI','UNI','SHIB','DASH','ARB','INJ']

def get_json(session,url,params=None,tries=5):
    last=None
    for a in range(tries):
        try:
            r=session.get(url,params=params,timeout=30); r.raise_for_status(); return r.json()
        except Exception as e:
            last=e; time.sleep(1.5*(a+1))
    raise RuntimeError(last)

def funding(sym,start,end):
    st=pd.Timestamp(start); en=pd.Timestamp(end); ses=requests.Session(); rec=[]; page=1
    while page<=50:
        p=get_json(ses,FUNDING,{'symbol':sym,'page_num':page,'page_size':1000}); d=p.get('data') or {}; batch=d.get('resultList') or []
        if not batch: break
        rec.extend(batch); times=[pd.to_datetime(int(x['settleTime']),unit='ms',utc=True) for x in batch if x.get('settleTime')]
        if not times or min(times)<st or page>=int(d.get('totalPage') or page): break
        page+=1; time.sleep(.05)
    if not rec:return pd.DataFrame(columns=['funding_rate'])
    f=pd.DataFrame(rec); f['timestamp']=pd.to_datetime(pd.to_numeric(f['settleTime'],errors='coerce'),unit='ms',utc=True); f['funding_rate']=pd.to_numeric(f['fundingRate'],errors='coerce')
    f=f.dropna(subset=['timestamp','funding_rate']).set_index('timestamp').sort_index(); f=f[~f.index.duplicated(keep='last')]
    return f.loc[(f.index>=st)&(f.index<en),['funding_rate']]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--config',required=True); ap.add_argument('--output-dir',required=True); args=ap.parse_args(); cfg=json.load(open(args.config)); out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    st=cfg['retrospective_temporal_diagnostic']['start']; en=cfg['retrospective_temporal_diagnostic']['end_exclusive']; manifest={'start':st,'end_exclusive':en,'symbols':{},'failures':[]}
    def load(base):
        sym=f'{base}_USDT'; fut=fetch_mexc_futures_klines(sym,'1h',st,en); fun=funding(sym,st,en); fut.to_csv(out/f'{base}_futures_1h.csv'); fun.to_csv(out/f'{base}_funding.csv')
        return base,{'futures_rows':len(fut),'funding_rows':len(fun),'first':str(fut.index.min()),'last':str(fut.index.max())}
    with ThreadPoolExecutor(max_workers=3) as ex:
        jobs={ex.submit(load,s):s for s in SYMS}
        for j in as_completed(jobs):
            try:
                b,m=j.result(); manifest['symbols'][b]=m
            except Exception as e: manifest['failures'].append({'symbol':jobs[j],'type':type(e).__name__,'message':str(e)[:400]})
    if manifest['failures']: raise SystemExit(json.dumps(manifest['failures'],indent=2))
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)); print(json.dumps(manifest,indent=2))
if __name__=='__main__':main()
