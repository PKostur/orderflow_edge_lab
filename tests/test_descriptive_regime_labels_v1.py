import json,math,unittest
from pathlib import Path
import numpy as np,pandas as pd
from orderflow_edge_lab.descriptive_regime_labels_v1 import (
 LABELS,cell_ids,kaufman_er,garman_klass,market_coupling,percentile_bucket,persist,shock,state_at_entry,bh,holm
)
ROOT=Path(__file__).resolve().parents[1]
def frame(n=700):
    i=pd.date_range("2024-01-01",periods=n,freq="8h",tz="UTC"); t=np.arange(n,dtype=float)
    r=.001+.0008*np.sin(t/13); c=100*np.cumprod(1+r); o=np.r_[c[0]/(1+r[0]),c[:-1]]
    h=np.maximum(o,c)*1.003; l=np.minimum(o,c)*.997
    return pd.DataFrame({"open":o,"high":h,"low":l,"close":c,"volume":1000.},index=i)
class Tests(unittest.TestCase):
    def test_contract(self):
        c=json.loads((ROOT/"config/universal_descriptive_regime_labels_v1.json").read_text())
        self.assertEqual(c["protocol_name"],"universal-descriptive-regime-labels-v1"); self.assertTrue(c["claims"]["descriptive_only"])
        self.assertFalse(c["claims"]["regime_filter_authorized"]); self.assertEqual(len(cell_ids()),162)
        self.assertEqual(len(cell_ids()),math.prod(len(x) for x in LABELS.values()))
    def test_er(self):
        x=kaufman_er(pd.Series(np.arange(1.,80.)),42); self.assertAlmostEqual(float(x.iloc[-1]),1.,12)
    def test_gk(self):
        f=frame(60); a=float(garman_klass(f,21).iloc[-1]); s=f.iloc[-21:]
        v=(.5*np.log(s.high/s.low)**2-(2*np.log(2)-1)*np.log(s.close/s.open)**2).clip(lower=0)
        self.assertAlmostEqual(a,float(np.sqrt(v.mean())),14)
    def test_percentile_is_lagged(self):
        x=pd.Series(np.arange(20.,dtype=float)); raw,lo,hi=percentile_bucket(x,5,1/3,2/3)
        self.assertAlmostEqual(float(lo.iloc[10]),float(x.iloc[5:10].quantile(1/3)),12); self.assertEqual(raw.iloc[10],"HIGH")
    def test_persistence(self):
        r=pd.Series(["LOW","HIGH","HIGH","LOW","HIGH","HIGH","HIGH"]); self.assertEqual(persist(r,3).tolist(),["LOW","LOW","LOW","LOW","LOW","LOW","HIGH"])
    def test_shock(self):
        base=np.resize(np.array([.001,-.001,.0005,-.0005]),541); c=pd.Series(np.exp(np.r_[base,[.10],np.zeros(12)].cumsum()))
        e,a=shock(c,540,4.,10); k=int(np.flatnonzero(e.to_numpy())[0]); self.assertTrue(a.iloc[k]); self.assertTrue(a.iloc[k+9]); self.assertFalse(a.iloc[k+10])
    def test_coupling(self):
        a=frame(140); b=a.copy(); c=a.copy(); b["close"]=a["close"]*2; c["close"]=a["close"]*3
        x=market_coupling({"A":a,"B":b,"C":c},90,3); self.assertAlmostEqual(float(x.dropna().iloc[-1]),1.,12)
    def test_entry_uses_previous_bar(self):
        i=pd.date_range("2026-01-01",periods=3,freq="8h",tz="UTC")
        z=pd.DataFrame({"trend_state":["CHOP","MIXED","TREND"],"volatility_state":["LOW","MID","HIGH"],"coupling_state":["LOW","MID","HIGH"],
        "shock_state":["NORMAL","NORMAL","SHOCK"],"drawdown_state":["NEAR_HIGH","CORRECTION","DEEP_DRAWDOWN"],"trend_efficiency":[.1,.2,.9],
        "gk_volatility":[.01,.02,.03],"market_coupling":[.2,.3,.8],"drawdown":[-.02,-.15,-.3],"shock_event":[False,False,True]},index=i)
        r=state_at_entry(z,i[2]); self.assertEqual(r["state_timestamp"],i[1].isoformat()); self.assertEqual(r["trend_state"],"MIXED")
    def test_adjustments(self):
        p=[.001,.01,.04,.2]
        for raw,q,h in zip(p,bh(p),holm(p)): self.assertGreaterEqual(q+1e-15,raw); self.assertGreaterEqual(h+1e-15,raw)
if __name__=="__main__": unittest.main()
