"""Synthetic-only pinned dependency parity; no strategy return data or orders."""
from pathlib import Path
import sys
import json
import math
import hashlib
import platform
import argparse
import zipfile
import numpy as np

parser = argparse.ArgumentParser(description="Synthetic pinned MAGen indicator audit; no market outcomes")
parser.add_argument('--runtime', type=Path, required=True, help='Isolated extracted/installed jesse-rust runtime')
parser.add_argument('--wheel', type=Path, required=True, help='Official cp313 Windows wheel pinned below')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
wheel = args.wheel.resolve()
wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
if wheel.name != 'jesse_rust-1.3.0-cp313-cp313-win_amd64.whl' or wheel_hash != '5e29ad2a2388e714239781ecf77ecd001dadc47026c6c64dd46891f5e309ce1b':
    raise ValueError('unsupported native wheel identity')
runtime = args.runtime.resolve()
sys.path.insert(0, str(runtime))
import jesse_rust as native
module = Path(native.__file__).resolve()
if module.parent != runtime / 'jesse_rust':
    raise ValueError('native import did not use the supplied isolated runtime')
with zipfile.ZipFile(wheel) as archive:
    for name in ('jesse_rust/__init__.py', 'jesse_rust/jesse_rust.cp313-win_amd64.pyd'):
        if archive.read(name) != (runtime / name).read_bytes():
            raise ValueError('installed native module differs from pinned wheel')

def atr(candles, period):
    n = len(candles)
    tr = [max(float(row[3]-row[4]), abs(float(row[3]-candles[i-1,2])),
              abs(float(row[4]-candles[i-1,2]))) if i else float(row[3]-row[4])
          for i,row in enumerate(candles)]
    out = np.full(n,np.nan)
    if n >= period:
        out[period-1]=sum(tr[:period])/period
        for i in range(period,n):
            out[i]=out[i-1]+(tr[i]-out[i-1])/period
    return out

def adx(candles, period):
    n=len(candles)
    out=np.full(n,np.nan)
    if n <= 2*period:
        return out
    tr=[0.0]; p=[0.0]; m=[0.0]
    for i in range(1,n):
        up=float(candles[i,3]-candles[i-1,3])
        down=float(candles[i-1,4]-candles[i,4])
        tr.append(max(float(candles[i,3]-candles[i,4]), abs(float(candles[i,3]-candles[i-1,2])),
                      abs(float(candles[i,4]-candles[i-1,2]))))
        p.append(up if up>down and up>0 else 0.0)
        m.append(down if down>up and down>0 else 0.0)
    st,sp,sm=sum(tr[1:period+1]),sum(p[1:period+1]),sum(m[1:period+1])
    dx=np.full(n,np.nan)
    for i in range(period,n):
        if i>period:
            st=st-st/period+tr[i]
            sp=sp-sp/period+p[i]
            sm=sm-sm/period+m[i]
        dp=100*sp/st if st else 0
        dm=100*sm/st if st else 0
        dx[i]=100*abs(dp-dm)/(dp+dm) if dp+dm else 0
    out[2*period]=sum(dx[period:2*period])/period
    for i in range(2*period+1,n):
        out[i]=(out[i-1]*(period-1)+dx[i])/period
    return out

def linearreg(source,period):
    out=np.full(len(source),np.nan)
    sx=period*(period-1)/2
    sxx=sum(i*i for i in range(period))
    den=period*sxx-sx*sx
    for i in range(period-1,len(source)):
        window=source[i-period+1:i+1]
        sy=sum(float(x) for x in window)
        sxy=sum(j*float(y) for j,y in enumerate(window))
        slope=(period*sxy-sx*sy)/den
        intercept=(sy-slope*sx)/period
        out[i]=intercept+slope*(period-1)
    return out

def fixture(kind,n):
    close=np.array([100+.04*i+3*math.sin(i*.37)+2*math.cos(i*.11) for i in range(n)])
    if kind=='flat': close[:]=100
    if kind=='gapped': close[n//2:]+=20
    if kind=='declining': close=close[::-1].copy()
    op=np.r_[close[0],close[:-1]]
    high=np.maximum(op,close)+.8
    low=np.minimum(op,close)-.6
    if kind=='flat': high[:]=100; low[:]=100
    return np.column_stack([np.arange(n,dtype=float)*28800000,op,close,high,low,np.full(n,1000)])

def check(actual,expected,name):
    actual=np.asarray(actual,dtype=float)
    expected=np.asarray(expected,dtype=float)
    if actual.shape != expected.shape:
        raise ValueError((name, actual.shape, expected.shape))
    if not np.array_equal(np.isnan(actual), np.isnan(expected)):
        raise ValueError(name + ' NaN seed placement')
    valid=np.isfinite(actual)
    error=float(np.max(np.abs(actual[valid]-expected[valid]))) if valid.any() else 0
    if not math.isfinite(error) or error >= 1e-9:
        raise ValueError((name, error))
    return error

checks=[]
for kind in ['oscillating','flat','gapped','declining']:
    for n in [16,33,240,600]:
        candles=fixture(kind,n)
        contiguous_close=np.ascontiguousarray(candles[:,2])
        errors={'atr32':check(native.atr(candles,32),atr(candles,32),'atr32'),
                'adx8':check(native.adx(candles,8),adx(candles,8),'adx8'),
                'linearreg5':check(native.linearreg(contiguous_close,5),linearreg(candles[:,2],5),'lr5'),
                'linearreg20':check(native.linearreg(contiguous_close,20),linearreg(candles[:,2],20),'lr20')}
        if n>=32:
            errors['atr_last']=check([native.atr_last(candles,32)],[atr(candles,32)[-1]],'atr_last')
        checks.append({'fixture':kind,'n':n,'max_abs_errors':errors})

rolling=[]
for kind in ['oscillating','flat','gapped','declining']:
    candles=fixture(kind,600)
    for end in [241,333,500,600]:
        window=candles[end-240:end]
        native_atr=native.atr_last(window,32)
        native_adx=native.adx(window,8)[-1]
        check([native_atr], [atr(window,32)[-1]], 'rolling_atr')
        check([native_adx], [adx(window,8)[-1]], 'rolling_adx')
        rolling.append({'fixture':kind,'end':end,'window':240,
                        'atr_abs_error':abs(float(native_atr-atr(window,32)[-1])),
                        'adx_abs_error':abs(float(native_adx-adx(window,8)[-1])),
                        'continuous_vs_native_window_atr_difference':float(atr(candles[:end],32)[-1]-native_atr),
                        'continuous_vs_native_window_adx_difference':float(adx(candles[:end],8)[-1]-native_adx)})
report={'study':'QUEUED-MAGEN-NATIVE-INDICATOR-ENGINEERING-AUDIT','strategy_trading_cells':0,
        'strategy_market_outcomes_inspected':False,'orders':False,'synthetic_fixtures':checks,'rolling_slice_checks':rolling,
        'dependency':'jesse-rust==1.3.0','source_tag_commit':'65e1007faf1804ca66651bc76cccd3feb80a0d6d',
        'jesse_engine_commit':'417f8765225e3bfc12043d4b712f19fe15a3c078','wheel_name':wheel.name,'wheel_sha256':wheel_hash,
        'installed_module_matches_wheel':True,'official_release_digest_previously_verified':True,
        'official_release_metadata':'https://pypi.org/pypi/jesse-rust/1.3.0/json','python':platform.python_version(),'numpy':np.__version__,
        'indicator_tolerance':1e-9,'risk_and_fill_native_parity':False,'source_unchanged_spot_compatibility':False,
        'linearreg_input_contract':'contiguous float64; direct strided input triggered a native panic, so only the supported contiguous input was audited',
        'candidate_viability':'NOT_TESTED','next':'Freeze a declared compatible protective-order port and conservative timestamp/benchmark bounds before market outcomes; separate untouched confirmation remains required.'}
args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
print(json.dumps({'synthetic_cases':len(checks),'rolling_cases':len(rolling),
                  'max_error':max(v for row in checks for v in row['max_abs_errors'].values()),
                  'wheel_sha256':wheel_hash,'market_outcomes':False}))
