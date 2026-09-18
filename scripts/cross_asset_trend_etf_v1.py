#!/usr/bin/env python3
import datetime as dt
import json, math, statistics, time, urllib.parse, urllib.request
from collections import defaultdict
from pathlib import Path

UNIVERSE=["SPY","EFA","EEM","IEF","TLT","GLD","DBC","VNQ"]
FETCH_START=dt.date(2006,1,1)
FETCH_END_EXCLUSIVE=dt.date(2018,1,2)
D0_START=dt.date(2008,1,2)
D0_END=dt.date(2017,12,29)
VOL_RETURNS=63
HOLD=21
PRIMARY_TX=10.0
PRIMARY_SHORT=5.0
STRESS_TX=20.0
STRESS_SHORT=10.0
FAMILIES={
 "CROSS_ASSET_TS_H1_RET252_HOLD21":252,
 "CROSS_ASSET_TS_H2_RET126_HOLD21":126
}

def epoch(d):
    return int(dt.datetime(d.year,d.month,d.day,tzinfo=dt.timezone.utc).timestamp())

def fetch_yahoo(symbol):
    params={"period1":epoch(FETCH_START),"period2":epoch(FETCH_END_EXCLUSIVE),
            "interval":"1d","events":"history,splits,div","includeAdjustedClose":"true"}
    url="https://query1.finance.yahoo.com/v8/finance/chart/"+urllib.parse.quote(symbol)+"?"+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 orderflow-edge-lab-research"})
    last=None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req,timeout=30) as r: payload=json.load(r)
            result=payload["chart"]["result"][0]
            stamps=result["timestamp"]
            q=result["indicators"]["quote"][0]
            adj=result["indicators"]["adjclose"][0]["adjclose"]
            out={}
            for i,ts in enumerate(stamps):
                ro=q["open"][i] if i<len(q["open"]) else None
                rc=q["close"][i] if i<len(q["close"]) else None
                ac=adj[i] if i<len(adj) else None
                if ro is None or rc is None or ac is None or rc<=0 or ro<=0 or ac<=0: continue
                factor=float(ac)/float(rc)
                d=dt.datetime.fromtimestamp(ts,tz=dt.timezone.utc).date()
                out[d]={"open":float(ro)*factor,"close":float(ac)}
            if not out: raise RuntimeError("no valid rows")
            return out
        except Exception as e:
            last=e
            time.sleep(2*(attempt+1))
    raise RuntimeError(f"{symbol} fetch failed: {last}")

def sample_std(xs):
    return statistics.stdev(xs) if len(xs)>=2 else float("nan")

def evaluate(data,calendar,name,lookback):
    obs=[]; contrib=defaultdict(float)
    first=max(lookback,VOL_RETURNS)
    i=max(first,next(k for k,d in enumerate(calendar) if d>=D0_START))
    while i<len(calendar):
        signal=calendar[i]
        if signal>D0_END: break
        entry_i=i+1; exit_i=entry_i+HOLD
        if exit_i>=len(calendar): break
        entry=calendar[entry_i]; exitd=calendar[exit_i]
        if entry>D0_END or exitd>D0_END: break
        dirs={}; inv={}; eligible=True
        for s in UNIVERSE:
            try:
                feat=math.log(data[s][signal]["close"]/data[s][calendar[i-lookback]]["close"])
                closes=[data[s][calendar[j]]["close"] for j in range(i-VOL_RETURNS,i+1)]
            except KeyError:
                eligible=False; break
            rets=[math.log(closes[k]/closes[k-1]) for k in range(1,len(closes))]
            sig=sample_std(rets)
            if not (sig>0 and math.isfinite(sig)):
                eligible=False; break
            direction=1 if feat>0 else (-1 if feat<0 else 0)
            if direction!=0:
                dirs[s]=direction; inv[s]=1.0/sig
        if not eligible or not dirs:
            i+=1; continue
        denom=sum(inv.values())
        weights={s:dirs[s]*inv[s]/denom for s in dirs}
        gross=0.0; p_cost=0.0; s_cost=0.0; rev_gross=0.0; rev_p_cost=0.0
        legs={}
        for s,w in weights.items():
            try:
                eo=data[s][entry]["open"]; xo=data[s][exitd]["open"]
            except KeyError:
                eligible=False; break
            r=(xo/eo-1.0)*10000.0
            leg_gross=w*r
            aw=abs(w)
            pc=aw*PRIMARY_TX + (aw*PRIMARY_SHORT if w<0 else 0.0)
            sc=aw*STRESS_TX + (aw*STRESS_SHORT if w<0 else 0.0)
            rw=-w
            rpc=aw*PRIMARY_TX + (aw*PRIMARY_SHORT if rw<0 else 0.0)
            gross+=leg_gross; rev_gross+=rw*r
            p_cost+=pc; s_cost+=sc; rev_p_cost+=rpc
            leg_net=leg_gross-pc
            contrib[s]+=leg_net
            legs[s]={"weight":w,"gross_bps":leg_gross,"primary_cost_bps":pc}
        if not eligible:
            i+=1; continue
        netp=gross-p_cost; nets=gross-s_cost; revp=rev_gross-rev_p_cost
        obs.append({"signal":str(signal),"entry":str(entry),"exit":str(exitd),
                    "net_primary_bps":netp,"net_stress_bps":nets,
                    "reversed_primary_bps":revp,"legs":legs})
        i=exit_i

    mean=lambda xs: statistics.fmean(xs) if xs else None
    years=defaultdict(list)
    for o in obs: years[int(o["signal"][:4])].append(o["net_primary_bps"])
    year_means={str(y):mean(v) for y,v in sorted(years.items())}
    py=sum(v>0 for v in year_means.values())
    h1=[o["net_primary_bps"] for o in obs if o["signal"]<="2012-12-31"]
    h2=[o["net_primary_bps"] for o in obs if o["signal"]>="2013-01-01"]
    pos={s:v for s,v in contrib.items() if v>0}
    pos_sum=sum(pos.values())
    conc=max(pos.values())/pos_sum if pos else None
    m1=mean([o["net_primary_bps"] for o in obs]); ms=mean([o["net_stress_bps"] for o in obs])
    mr=mean([o["reversed_primary_bps"] for o in obs])
    gates={
      "minimum_portfolio_observations":len(obs)>=90,
      "minimum_calendar_years_with_observations":len(years)>=10,
      "net_mean_bps_primary_positive":m1 is not None and m1>0,
      "net_mean_bps_stress_positive":ms is not None and ms>0,
      "original_beats_reversed_primary":m1 is not None and mr is not None and m1>mr,
      "minimum_positive_calendar_year_fraction":len(years)>0 and py/len(years)>=0.70,
      "both_calendar_halves_positive_primary":bool(h1) and bool(h2) and mean(h1)>0 and mean(h2)>0,
      "minimum_assets_with_positive_total_contribution":len(pos)>=6,
      "max_positive_contribution_share_single_asset":conc is not None and conc<=0.30
    }
    return {
      "family":name,"status":"SURVIVES_D0" if all(gates.values()) else "FALSIFIED_D0",
      "observations":len(obs),"net_mean_bps_primary":m1,"net_mean_bps_stress":ms,
      "reversed_mean_bps_primary":mr,"year_means_primary_bps":year_means,
      "positive_year_fraction":py/len(years) if years else None,
      "half1_mean_bps_primary":mean(h1),"half2_mean_bps_primary":mean(h2),
      "asset_contribution_bps":dict(sorted(contrib.items())),
      "positive_asset_count":len(pos),"max_positive_asset_share":conc,
      "gate_results":gates,"observations_detail":obs
    }

def main():
    data={}
    for s in UNIVERSE:
        print("fetch",s,flush=True)
        data[s]=fetch_yahoo(s); time.sleep(0.5)
    common=set.intersection(*(set(data[s]) for s in UNIVERSE))
    calendar=sorted(d for d in common if FETCH_START<=d<FETCH_END_EXCLUSIVE)
    results={name:evaluate(data,calendar,name,lb) for name,lb in FAMILIES.items()}
    survivors=[k for k,v in results.items() if v["status"]=="SURVIVES_D0"]
    out={
      "research_id":"cross_asset_trend_etf_v1","stage":"D0_development",
      "source":{"provider":"Yahoo Finance chart API","adjusted_open_and_close":True,
                "fetch_window":[str(FETCH_START),str(FETCH_END_EXCLUSIVE)],
                "D0_window":[str(D0_START),str(D0_END)],"D3_fetched":False},
      "data_integrity":{"common_sessions":len(calendar),"first_common_session":str(calendar[0]),
                        "last_common_session":str(calendar[-1]),
                        "per_symbol_rows":{s:len(data[s]) for s in UNIVERSE}},
      "families":results,"survivors":survivors,
      "research_state":{"D0":"SURVIVOR_EXISTS" if survivors else "FALSIFIED_ALL_FAMILIES",
                        "D3_holdout":"SEALED_NOT_FETCHED","candidate_created":False,
                        "persistent_edge_established":False,"live_execution_supported":False,
                        "leverage_supported":False}
    }
    p=Path("research/cross_asset_trend_etf_v1/D0_RESULT.json")
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:{"status":v["status"],"n":v["observations"],
      "primary":v["net_mean_bps_primary"],"stress":v["net_mean_bps_stress"],
      "reversed":v["reversed_mean_bps_primary"],"years":v["year_means_primary_bps"],
      "half1":v["half1_mean_bps_primary"],"half2":v["half2_mean_bps_primary"],
      "positive_assets":v["positive_asset_count"],"concentration":v["max_positive_asset_share"],
      "gates":v["gate_results"]} for k,v in results.items()},indent=2))

if __name__=="__main__":
    main()
