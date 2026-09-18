#!/usr/bin/env python3
import datetime as dt
import json
import math
import statistics
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

UNIVERSE = ["XLB","XLC","XLE","XLF","XLI","XLK","XLP","XLRE","XLU","XLV","XLY"]
D0_START = dt.date(2020,1,2)
D0_END = dt.date(2023,12,29)
FETCH_START = dt.date(2019,9,1)
FETCH_END_EXCLUSIVE = dt.date(2024,1,2)
PRIMARY_COST = 8.0
STRESS_COST = 16.0
FAMILIES = {
    "SECTOR_XS_H1_MOM63_HOLD21": {"lookback":63,"hold":21,"side":"momentum"},
    "SECTOR_XS_H2_MOM21_HOLD5": {"lookback":21,"hold":5,"side":"momentum"},
    "SECTOR_XS_H3_REV5_HOLD5": {"lookback":5,"hold":5,"side":"reversal"},
}

def epoch(d):
    return int(dt.datetime(d.year,d.month,d.day,tzinfo=dt.timezone.utc).timestamp())

def fetch_yahoo(symbol):
    params = {
        "period1": epoch(FETCH_START),
        "period2": epoch(FETCH_END_EXCLUSIVE),
        "interval": "1d",
        "events": "history,splits",
        "includeAdjustedClose": "true",
    }
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(symbol) + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0 orderflow-edge-lab-research"})
    last = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                payload = json.load(r)
            result = payload["chart"]["result"][0]
            stamps = result["timestamp"]
            q = result["indicators"]["quote"][0]
            out = {}
            for i,ts in enumerate(stamps):
                vals = {k:q.get(k,[None]*len(stamps))[i] for k in ("open","high","low","close")}
                if any(v is None for v in vals.values()):
                    continue
                d = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date()
                out[d] = {k:float(v) for k,v in vals.items()}
            if not out:
                raise RuntimeError("no rows")
            return out
        except Exception as e:
            last=e
            time.sleep(2*(attempt+1))
    raise RuntimeError(f"{symbol} fetch failed: {last}")

def rank_positions(features, side):
    ordered = sorted(features.items(), key=lambda kv:(kv[1],kv[0]))
    bottom = [x[0] for x in ordered[:3]]
    top = [x[0] for x in ordered[-3:]]
    if side == "momentum":
        return {**{s:-1 for s in bottom}, **{s:1 for s in top}}
    return {**{s:1 for s in bottom}, **{s:-1 for s in top}}

def evaluate_family(data, calendar, name, spec):
    lb, hold, side = spec["lookback"], spec["hold"], spec["side"]
    date_to_i = {d:i for i,d in enumerate(calendar)}
    first = next(i for i,d in enumerate(calendar) if d >= D0_START and i >= lb)
    observations=[]
    contributions=defaultdict(float)
    selected=set()
    i=first
    while i < len(calendar):
        signal=calendar[i]
        if signal < D0_START:
            i+=1; continue
        if signal > D0_END:
            break
        entry_i=i+1
        exit_i=entry_i+hold
        if exit_i >= len(calendar):
            break
        entry=calendar[entry_i]; exitd=calendar[exit_i]
        if entry > D0_END or exitd > D0_END:
            break
        features={}
        eligible=True
        for s in UNIVERSE:
            try:
                c0=data[s][calendar[i-lb]]["close"]
                c1=data[s][signal]["close"]
            except KeyError:
                eligible=False; break
            if c0<=0 or c1<=0:
                eligible=False; break
            features[s]=c1/c0-1.0
        if not eligible:
            i += 1
            continue
        positions=rank_positions(features,side)
        legs=[]
        for s,direction in positions.items():
            try:
                e=data[s][entry]["open"]; x=data[s][exitd]["open"]
            except KeyError:
                eligible=False; break
            if e<=0 or x<=0:
                eligible=False; break
            gross=direction*(x/e-1.0)*10000.0
            legs.append((s,direction,gross))
        if not eligible or len(legs)!=6:
            i += 1
            continue
        p_net=sum(g-PRIMARY_COST for _,_,g in legs)/6.0
        s_net=sum(g-STRESS_COST for _,_,g in legs)/6.0
        rev=sum(-g-PRIMARY_COST for _,_,g in legs)/6.0
        for s,_,g in legs:
            contributions[s]+=(g-PRIMARY_COST)/6.0
            selected.add(s)
        observations.append({"signal":str(signal),"entry":str(entry),"exit":str(exitd),
                             "net_primary_bps":p_net,"net_stress_bps":s_net,"reversed_primary_bps":rev,
                             "positions":positions})
        i=exit_i

    if observations:
        meanp=statistics.fmean(o["net_primary_bps"] for o in observations)
        means=statistics.fmean(o["net_stress_bps"] for o in observations)
        meanr=statistics.fmean(o["reversed_primary_bps"] for o in observations)
    else:
        meanp=means=meanr=float("nan")
    byyear=defaultdict(list)
    for o in observations:
        byyear[int(o["signal"][:4])].append(o["net_primary_bps"])
    year_means={str(y):statistics.fmean(v) for y,v in sorted(byyear.items())}
    positive_years=sum(v>0 for v in year_means.values())
    positive_contrib={s:v for s,v in contributions.items() if v>0}
    if positive_contrib:
        concentration=max(positive_contrib.values())/sum(positive_contrib.values())
    else:
        concentration=None

    gates={
        "minimum_portfolio_observations": len(observations)>=40,
        "minimum_calendar_years_with_observations": len(byyear)>=4,
        "minimum_distinct_sectors_selected": len(selected)>=9,
        "net_mean_bps_primary_positive": bool(observations) and meanp>0,
        "net_mean_bps_stress_nonnegative": bool(observations) and means>=0,
        "original_beats_reversed_primary": bool(observations) and meanp>meanr,
        "minimum_positive_calendar_year_fraction": len(byyear)>0 and positive_years/len(byyear)>=0.75,
        "minimum_sectors_with_positive_total_contribution": len(positive_contrib)>=6,
        "max_positive_contribution_share_single_sector": concentration is not None and concentration<=0.30,
    }
    return {
        "family":name,
        "status":"SURVIVES_D0" if all(gates.values()) else "FALSIFIED_D0",
        "observations":len(observations),
        "distinct_sectors_selected":len(selected),
        "net_mean_bps_primary":meanp,
        "net_mean_bps_stress":means,
        "reversed_mean_bps_primary":meanr,
        "year_means_primary_bps":year_means,
        "positive_year_fraction": positive_years/len(byyear) if byyear else None,
        "sector_contribution_bps":dict(sorted(contributions.items())),
        "positive_sector_count":len(positive_contrib),
        "max_positive_sector_share":concentration,
        "gate_results":gates,
        "observations_detail":observations,
    }

def main():
    data={}
    for s in UNIVERSE:
        print("fetch",s,flush=True)
        data[s]=fetch_yahoo(s)
        time.sleep(0.5)
    common=set.intersection(*(set(data[s]) for s in UNIVERSE))
    calendar=sorted(d for d in common if FETCH_START <= d < FETCH_END_EXCLUSIVE)
    if not calendar:
        raise SystemExit("no common calendar")
    results={}
    for name,spec in FAMILIES.items():
        results[name]=evaluate_family(data,calendar,name,spec)
    survivors=[k for k,v in results.items() if v["status"]=="SURVIVES_D0"]
    out={
      "research_id":"sector_etf_cross_sectional_v1",
      "stage":"D0_development",
      "source":{"provider":"Yahoo Finance chart API","single_source_all_symbols":True,
                "fetch_window":[str(FETCH_START),str(FETCH_END_EXCLUSIVE)],"D0_window":[str(D0_START),str(D0_END)],
                "D3_fetched":False},
      "data_integrity":{"common_sessions":len(calendar),"first_common_session":str(calendar[0]),
                        "last_common_session":str(calendar[-1]),
                        "per_symbol_rows":{s:len(data[s]) for s in UNIVERSE}},
      "families":results,
      "survivors":survivors,
      "research_state":{"D0":"SURVIVOR_EXISTS" if survivors else "FALSIFIED_ALL_FAMILIES",
                        "D3_holdout":"SEALED_NOT_FETCHED","candidate_created":False,
                        "persistent_edge_established":False,"live_execution_supported":False,
                        "leverage_supported":False}
    }
    Path("research/sector_etf_cross_sectional_v1/D0_RESULT_YAHOO.json").write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:{"status":v["status"],"n":v["observations"],"mean":v["net_mean_bps_primary"],
                         "stress":v["net_mean_bps_stress"],"years":v["year_means_primary_bps"],
                         "gates":v["gate_results"]} for k,v in results.items()},indent=2))

if __name__=="__main__":
    main()
