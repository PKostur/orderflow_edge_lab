from pathlib import Path
import ast,hashlib,json,math,sys,types
import numpy as np
import pandas as pd

b=Path(__file__).resolve().parent.parent
p=b/'work/post_force_index_source_survey'
sys.path.insert(0,str(b/'work/ou_native_runtime/site'))
import backtrader as bt

source=p/'azary_codes_KeltnerBreakoutStrategy.py'
tree=ast.parse(source.read_text(encoding='utf-8-sig'))
classes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in ('KeltnerChannel','KeltnerBreakoutStrategy')]
assert len(classes)==2
module=types.ModuleType('pinned_native_keltner');sys.modules[module.__name__]=module
module.__dict__['bt']=bt
exec(compile(ast.Module(body=classes,type_ignores=[]),str(source),'exec'),module.__dict__)
class Observed(module.KeltnerBreakoutStrategy):
    def __init__(self):
        super().__init__();self.rows=[];self.advice=[]
    def next(self):
        pos=float(self.position.size)
        super().next()
        self.rows.append(dict(bar=len(self)-1,mid=float(self.keltner.mid[0]),top=float(self.keltner.top[0]),bot=float(self.keltner.bot[0]),position_before_advice=pos))
    def buy(self,*a,**k):
        order=super().buy(*a,**k);self.advice.append(dict(bar=len(self)-1,side='BUY',size=float(order.size)));return order
    def sell(self,*a,**k):
        order=super().sell(*a,**k);self.advice.append(dict(bar=len(self)-1,side='SELL',size=float(order.size)));return order

def port(candles):
    n=len(candles);mid=[None]*n;atr=[None]*n;tr=[None]*n
    for i in range(1,n):tr[i]=max(candles[i][1],candles[i-1][3])-min(candles[i][2],candles[i-1][3])
    atr[7]=math.fsum(tr[1:8])/7;mid[29]=math.fsum(row[3] for row in candles[:30])/30
    for i in range(8,n):atr[i]=atr[i-1]*(1.-1./7.)+tr[i]*(1./7.)
    for i in range(30,n):mid[i]=mid[i-1]*(1.-2./31.)+candles[i][3]*(2./31.)
    rows=[];advice=[];position=0
    for i in range(29,n):
        rows.append(dict(bar=i,mid=mid[i],top=mid[i]+atr[i],bot=mid[i]-atr[i],position_before_advice=float(position)))
        side=None
        if not position and i>29:
            if candles[i-1][3]>mid[i-1]+atr[i-1]:side='BUY';position=1
            elif candles[i-1][3]<mid[i-1]-atr[i-1]:side='SELL';position=-1
        elif position>0 and candles[i][3]<mid[i]:side='SELL';position=0
        elif position<0 and candles[i][3]>mid[i]:side='BUY';position=0
        if side:advice.append(dict(bar=i,side=side,size=1. if side=='BUY' else -1.))
    return rows,advice

def native(candles):
    df=pd.DataFrame(candles,columns=['open','high','low','close','volume'],index=pd.date_range('2020-01-01',periods=len(candles),freq='8h'))
    c=bt.Cerebro(stdstats=False);c.broker.setcash(100000)
    c.adddata(bt.feeds.PandasData(dataname=df,timeframe=bt.TimeFrame.Minutes,compression=480));c.addstrategy(Observed,printlog=False)
    result=c.run()[0];return result.rows,result.advice

rng=np.random.default_rng(20261015);fixtures=[]
for mode in ('random','rising','falling','flat','oscillating','gaps'):
    price=100.;rows=[]
    for i in range(400):
        opening=price+(float(rng.normal(0,4)) if mode=='gaps' else 0.)
        price=max(5.,price+float(rng.normal(0,2))) if mode in ('random','gaps') else price+.5 if mode=='rising' else price*.996 if mode=='falling' else 100. if mode=='flat' else 100.+15.*math.sin(i*.15)
        rows.append([opening,max(opening,price)+1.,min(opening,price)-1.,price,float(rng.integers(0,100))])
    fixtures.append(dict(name=mode,candles=rows))
for n in (30,31,59,100,239,240,255):fixtures.append(dict(name=f'prefix{n}',candles=fixtures[0]['candles'][:n]))
for n in (59,100,240):fixtures.append(dict(name=f'future{n}',candles=fixtures[0]['candles'][:n]+fixtures[4]['candles'][n:]))
results=[]
for f in fixtures:
    rows,advice=native(f['candles']);expected=port(f['candles'])
    assert (rows,advice)==expected,f['name']
    if f['name'].startswith('prefix'):assert rows==results[0]['rows'][:len(rows)]
    if f['name'].startswith('future'):
        cut=int(f['name'][6:]);assert [r for r in rows if r['bar']<cut]==[r for r in results[0]['rows'] if r['bar']<cut]
    results.append(dict(name=f['name'],rows=rows,advice=advice))
(p/'keltner-synthetic-input.json').write_text(json.dumps(fixtures)+'\n')
(p/'keltner-native-synthetic-output.json').write_text(json.dumps(results,allow_nan=False)+'\n')
r=dict(kind='KELTNER_SOURCE_NATIVE_MATH_PREREQUISITE',status='PASS_SYNTHETIC_SOURCE_RUNTIME_MATH_ONLY',source_commit='945c7c430c799687be17092eaebcad6baace1a9e',source_exact_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),backtrader=bt.__version__,fixtures=len(fixtures),original_native_feature_rows=sum(len(x['rows']) for x in results),original_native_synthetic_broker_advices=sum(len(x['advice']) for x in results),prefix_checks=7,future_mutation_checks=3,exact_features_and_advices=True,feed_timeframe='Minutes',compression=480,market_data_loaded=False,new_registered_trials=0,new_attempted_trials=0,orders=False,limits=['Original unmodified two classes only; no top-level finance imports, downloads, plots or runner executed.','Native two-sided synthetic broker state is observed; any Spot long/cash scope must be separately declared. No live/nativeSpot execution parity.','Strategy ATR7 overrides indicator default14. EMA30 SMA seed at29; Wilder ATR7 TR seed bars1..7; original scalar operation order. Entry uses previous completed close/channel, observed after current completed bar; exit uses current close/mid. Default unit1, no stop/target/trailing/timeout.','Same educational book-repository bounded README Code MIT statement; standalone LICENSE absent and placeholder remains. No published profitability claim.','Broad prior trend/ATR/breakout overlap; source mechanics do not demonstrate orthogonality or incremental predictive information.'])
r['file_sha256']={name:hashlib.sha256((p/name).read_bytes()).hexdigest() for name in ['azary_codes_KeltnerBreakoutStrategy.py','keltner-synthetic-input.json','keltner-native-synthetic-output.json']}
(b/'outputs/Keltner-source-native-math-prerequisite.json').write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps(r))
