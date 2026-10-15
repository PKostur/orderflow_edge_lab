from pathlib import Path
import ast,sys,json,hashlib,math,types
import numpy as np,pandas as pd
from scipy import stats
b=Path(__file__).resolve().parent.parent
p=b/'work/post_force_index_source_survey'
sys.path.insert(0,str(b/'work/ou_native_runtime/site'))
import backtrader as bt
source=p/'azary_codes_OUMeanReversionStrategy.py'
assert hashlib.sha256(source.read_bytes()).hexdigest()=='e9940bfb353602c635ca085eb4de3dc8d9521d48e5ca4017c3d83ebb5cfa2fb3'
text=source.read_text(encoding='utf-8-sig')
cls=next(n for n in ast.parse(text).body if isinstance(n,ast.ClassDef) and n.name=='OUMeanReversionStrategy')
module=types.ModuleType('pinned_native_ou');sys.modules[module.__name__]=module
module.__dict__.update(bt=bt,np=np,pd=pd,stats=stats)
exec(compile(ast.Module(body=[cls],type_ignores=[]),str(source),'exec'),module.__dict__)
Original=module.OUMeanReversionStrategy
class Observed(Original):
    def __init__(self):
        super().__init__();self.observed=[];self.advice=[];self.current_fit=None
    def estimate_ou_parameters(self,log_prices):
        result=super().estimate_ou_parameters(log_prices);self.current_fit=result;return result
    def next(self):
        self.current_fit=None;super().next()
        self.observed.append(dict(bar=len(self)-1,fit=self.current_fit,sma=float(self.sma[0])))
    def buy(self,*a,**k):
        order=super().buy(*a,**k);self.advice.append(dict(bar=len(self)-1,side='BUY',size=float(order.size)));return order
    def sell(self,*a,**k):
        order=super().sell(*a,**k);self.advice.append(dict(bar=len(self)-1,side='SELL',size=float(order.size)));return order

def port(prices):
    out=[]
    for i in range(29,len(prices)):
        values=np.array([np.log(float(prices[j])) for j in range(i-29,i+1)])
        fit=(None,None,None,None)
        try:
            slope,intercept,*_=stats.linregress(values[:-1],np.diff(values))
            theta=-slope;mu=intercept/theta if theta>1e-6 else np.mean(values)
            residual=np.diff(values)-(intercept+slope*values[:-1]);sigma=np.std(residual)
            eq=sigma/np.sqrt(2*theta) if theta>1e-6 else sigma
            fit=(mu,theta,sigma,eq)
        except Exception:pass
        out.append(dict(bar=i,fit=fit,sma=math.fsum(float(x) for x in prices[i-29:i+1])/30))
    return out

def native(prices):
    close=np.asarray(prices);opening=np.r_[close[0],close[:-1]]
    df=pd.DataFrame(dict(open=opening,high=np.maximum(opening,close)+1,low=np.minimum(opening,close)-1,close=close,volume=np.ones(len(close))),index=pd.date_range('2020-01-01',periods=len(close),freq='8h'))
    engine=bt.Cerebro(stdstats=False);engine.broker.setcash(100000);engine.adddata(bt.feeds.PandasData(dataname=df,timeframe=bt.TimeFrame.Minutes,compression=480));engine.addstrategy(Observed);result=engine.run()[0]
    return result.observed,result.advice
rng=np.random.default_rng(20261015)
fixtures=[]
for mode in ['ou','random','rising','falling','flat','oscillating']:
    logs=[math.log(100)]
    for i in range(1,400):
        logs.append(math.log(100)+.85*(logs[-1]-math.log(100))+float(rng.normal(0,.025)) if mode=='ou' else logs[-1]+float(rng.normal(0,.02)) if mode=='random' else logs[-1]+.002 if mode=='rising' else logs[-1]-.002 if mode=='falling' else math.log(100) if mode=='flat' else math.log(100)+.12*math.sin(i*.17))
    fixtures.append(dict(name=mode,prices=np.exp(logs).tolist()))
for n in [30,31,59,100,239,240,255]:fixtures.append(dict(name=f'prefix{n}',prices=fixtures[0]['prices'][:n]))
for n in [59,100,240]:fixtures.append(dict(name=f'future{n}',prices=fixtures[0]['prices'][:n]+[100+float(i%10) for i in range(400-n)]))
results=[];rows=0;advices=0
for fixture in fixtures:
    got,advice=native(fixture['prices']);expected=port(fixture['prices']);assert got==expected,fixture['name']
    assert all(a['size'] in (1.,-1.) for a in advice),advice
    results.append(dict(name=fixture['name'],rows=got,advice=advice));rows+=len(got);advices+=len(advice)
    if fixture['name'].startswith('prefix'):assert got==results[0]['rows'][:len(got)]
    if fixture['name'].startswith('future'):
        cut=int(fixture['name'][6:]);assert [x for x in got if x['bar']<cut]==[x for x in results[0]['rows'] if x['bar']<cut]
(p/'ou-8h-synthetic-input.json').write_text(json.dumps(fixtures)+'\n')
(p/'ou-8h-native-synthetic-output.json').write_text(json.dumps(results,allow_nan=False)+'\n')
r=dict(kind='OU_NATIVE_SOURCE_MATH_PREREQUISITE',status='PASS_SYNTHETIC_SOURCE_RUNTIME_MATH_ONLY',source_commit='945c7c430c799687be17092eaebcad6baace1a9e',source_exact_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),backtrader=bt.__version__,scipy=__import__('scipy').__version__,numpy=np.__version__,pandas=pd.__version__,fixtures=len(fixtures),original_native_feature_rows=rows,original_native_synthetic_broker_advice=advices,unit_size_all_native_advices=True,exact_port_vs_native_fit_sma_rows=True,prefix_checks=7,future_mutation_checks=3,new_registered_trials=0,market_data_loaded=False,live_or_exchange_orders=False,scope='Original unmodified strategy class AST run through isolated pinned Backtrader virtual broker on synthetic8h candles; no original module top-level imports or runner download/backtest/plot code executed.',limits=['SMA usesmath.fsum/current30; OLS usespinnedscipy.linregress andnp.std ddof0 in originalorder; not a separately derivedOLS oracle.','Generic published runner selects QuantileChannelStrategy; native unit1 is framework default, not demonstrated publishedOU run.','Full native source is two-sided; any Spot long/cash study must preregister explicit scope and rejected-order lifecycle limits.','No marketperformance or newtrial. Source licenseREADMEclaimsMITcode but standaloneLICENSE absent and placeholder remains.'])
assert (p/'ou-8h-native-synthetic-output.json').read_bytes()==(p/'ou-native-synthetic-output.json').read_bytes()
r['feed_metadata']=dict(timeframe='Minutes',compression=480,timestamp_spacing_minutes=480)
r['same_features_and_advice_as_prior_default_metadata_output']=True
r['file_sha256']={name:hashlib.sha256((p/name).read_bytes()).hexdigest() for name in ['azary_codes_OUMeanReversionStrategy.py','ou-8h-synthetic-input.json','ou-8h-native-synthetic-output.json']}
(b/'outputs/OU-source-native-8h-metadata-prerequisite.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
