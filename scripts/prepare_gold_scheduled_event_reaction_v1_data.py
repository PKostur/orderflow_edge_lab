from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

UA = {'User-Agent': 'orderflow-edge-lab research/1.0'}
NY = ZoneInfo('America/New_York')
FIXED_EST = timezone(timedelta(hours=-5))
MONTHS = {m.lower(): i for i, m in enumerate(['January','February','March','April','May','June','July','August','September','October','November','December'], 1)}
MONTHS.update({m[:3].lower(): i for m, i in list(MONTHS.items())})


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def get(url: str) -> str:
    r = requests.get(url, headers=UA, timeout=45)
    r.raise_for_status()
    return r.text


def official_to_data_clock(day: datetime, hour: int, minute: int) -> tuple[str, str]:
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=NY)
    fixed = local.astimezone(timezone.utc).astimezone(FIXED_EST)
    return local.isoformat(), fixed.replace(tzinfo=None).isoformat(timespec='minutes')


def parse_bls_archive(url: str, prefix: str, event_type: str, years: set[int]) -> list[dict]:
    html = get(url)
    soup = BeautifulSoup(html, 'html.parser')
    pat = re.compile(rf'{re.escape(prefix)}_(\d{{8}})\.htm', re.I)
    out = {}
    for a in soup.find_all('a', href=True):
        m = pat.search(a['href'])
        if not m:
            continue
        ds = m.group(1)
        day = datetime.strptime(ds, '%m%d%Y')
        if day.year not in years:
            continue
        official, fixed = official_to_data_clock(day, 8, 30)
        out[day.date().isoformat()] = {
            'event_type': event_type,
            'release_date': day.date().isoformat(),
            'official_et': official,
            'data_clock': fixed,
            'source_url': url,
        }
    return [out[k] for k in sorted(out)]


def parse_hist_fomc_heading(text: str, year: int) -> datetime | None:
    t = ' '.join(text.split())
    low = t.lower()
    if 'meeting' not in low or str(year) not in t:
        return None
    if any(x in low for x in ['unscheduled', 'cancelled', 'notation vote']):
        return None
    m = re.search(r'([A-Za-z]+(?:/[A-Za-z]+)?)\s+(\d{1,2})(?:-(\d{1,2}))?\s+Meeting\s*-\s*(\d{4})', t, re.I)
    if not m:
        return None
    months = m.group(1).split('/')
    d1 = int(m.group(2)); d2 = int(m.group(3) or d1)
    y = int(m.group(4))
    if y != year:
        return None
    end_month_name = months[-1] if len(months) > 1 else months[0]
    month = MONTHS.get(end_month_name.lower()) or MONTHS.get(end_month_name[:3].lower())
    if not month:
        return None
    return datetime(y, month, d2)


def parse_fomc(years: set[int]) -> list[dict]:
    out = {}
    for year in sorted(y for y in years if y <= 2020):
        url = f'https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm'
        soup = BeautifulSoup(get(url), 'html.parser')
        for tag in soup.find_all(['h3','h4','h5','h6']):
            day = parse_hist_fomc_heading(tag.get_text(' ', strip=True), year)
            if day is None:
                continue
            official, fixed = official_to_data_clock(day, 14, 0)
            out[day.date().isoformat()] = {
                'event_type': 'fomc', 'release_date': day.date().isoformat(),
                'official_et': official, 'data_clock': fixed, 'source_url': url,
            }
    recent_years = sorted(y for y in years if 2021 <= y <= 2023)
    if recent_years:
        url = 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'
        soup = BeautifulSoup(get(url), 'html.parser')
        pat = re.compile(r'fomcpresconf(\d{8})\.htm', re.I)
        for a in soup.find_all('a', href=True):
            m = pat.search(a['href'])
            if not m:
                continue
            day = datetime.strptime(m.group(1), '%Y%m%d')
            if day.year not in recent_years:
                continue
            official, fixed = official_to_data_clock(day, 14, 0)
            out[day.date().isoformat()] = {
                'event_type': 'fomc', 'release_date': day.date().isoformat(),
                'official_et': official, 'data_clock': fixed, 'source_url': url,
            }
    return [out[k] for k in sorted(out)]


def parse_mt_year(path: Path, target_ranges: list[tuple[pd.Timestamp,pd.Timestamp]]) -> pd.DataFrame:
    names = ['date','time','open','high','low','close','volume']
    kept = []
    for ch in pd.read_csv(path, header=None, names=names, chunksize=200000):
        dt = pd.to_datetime(ch['date'].astype(str) + ' ' + ch['time'].astype(str), format='%Y.%m.%d %H:%M', errors='coerce')
        ch = ch.assign(timestamp=dt)
        mask = pd.Series(False, index=ch.index)
        for lo, hi in target_ranges:
            mask |= (ch['timestamp'] >= lo) & (ch['timestamp'] <= hi)
        if mask.any():
            k = ch.loc[mask, ['timestamp','open','high','low','close','volume']].copy()
            for c in ['open','high','low','close','volume']:
                k[c] = pd.to_numeric(k[c], errors='coerce')
            kept.append(k)
    if not kept:
        return pd.DataFrame(columns=['timestamp','open','high','low','close','volume'])
    d = pd.concat(kept, ignore_index=True).dropna().drop_duplicates('timestamp', keep='last').sort_values('timestamp')
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--data-dir', required=True)
    ap.add_argument('--output-dir', required=True)
    args = ap.parse_args()
    cfg = json.loads(Path(args.config).read_text())
    years = set(int(y) for y in cfg['market_data']['years'])
    events = []
    events += parse_bls_archive(cfg['event_sources']['cpi']['official_source'], 'cpi', 'cpi', years)
    events += parse_bls_archive(cfg['event_sources']['employment_situation']['official_source'], 'empsit', 'employment_situation', years)
    events += parse_fomc(years)
    ev = pd.DataFrame(events).drop_duplicates(['event_type','release_date']).sort_values(['release_date','event_type']).reset_index(drop=True)
    if ev.empty:
        raise SystemExit('no official events parsed')
    ev['data_clock'] = pd.to_datetime(ev['data_clock'])
    ev['period'] = np.where(ev['data_clock'] < pd.Timestamp(cfg['periods']['development']['end_exclusive']), 'development', 'locked_validation')

    data_dir = Path(args.data_dir)
    out_dir = Path(args.output_dir); out_dir.mkdir(parents=True, exist_ok=True)
    pre = int(cfg['data_admission']['required_pre_event_minutes'])
    post = int(cfg['data_admission']['required_post_event_minutes'])
    event_frames = []
    file_hashes = {}
    for year in sorted(years):
        p = data_dir / cfg['market_data']['file_pattern'].format(year=year)
        if not p.exists():
            raise FileNotFoundError(p)
        file_hashes[str(year)] = sha256_file(p)
        year_events = ev[ev['data_clock'].dt.year == year]
        targets = []
        for t in year_events['data_clock']:
            targets.append((t - pd.Timedelta(minutes=pre), t + pd.Timedelta(minutes=post)))
            pt = t - pd.Timedelta(days=7)
            targets.append((pt - pd.Timedelta(minutes=pre), pt + pd.Timedelta(minutes=post)))
        if targets:
            f = parse_mt_year(p, targets)
            f['year'] = year
            event_frames.append(f)
    bars = pd.concat(event_frames, ignore_index=True).drop_duplicates('timestamp', keep='last').sort_values('timestamp') if event_frames else pd.DataFrame()
    bar_index = pd.DatetimeIndex(bars['timestamp']) if not bars.empty else pd.DatetimeIndex([])

    audits = []
    for _, row in ev.iterrows():
        t = pd.Timestamp(row['data_clock'])
        pre_idx = pd.date_range(t - pd.Timedelta(minutes=pre), t - pd.Timedelta(minutes=1), freq='min')
        post_idx = pd.date_range(t, t + pd.Timedelta(minutes=59), freq='min')
        full_idx = pd.date_range(t, t + pd.Timedelta(minutes=post), freq='min')
        placebo = t - pd.Timedelta(days=7)
        ppre = pd.date_range(placebo - pd.Timedelta(minutes=pre), placebo - pd.Timedelta(minutes=1), freq='min')
        ppost = pd.date_range(placebo, placebo + pd.Timedelta(minutes=59), freq='min')
        admitted = bool(
            t in bar_index
            and int((~pre_idx.isin(bar_index)).sum()) <= int(cfg['data_admission']['maximum_missing_minutes_in_pre_window'])
            and int((~post_idx.isin(bar_index)).sum()) <= int(cfg['data_admission']['maximum_missing_minutes_in_first_60_post'])
            and (t + pd.Timedelta(minutes=65)) in bar_index
        )
        placebo_admitted = bool(
            placebo in bar_index
            and int((~ppre.isin(bar_index)).sum()) <= int(cfg['data_admission']['maximum_missing_minutes_in_pre_window'])
            and int((~ppost.isin(bar_index)).sum()) <= int(cfg['data_admission']['maximum_missing_minutes_in_first_60_post'])
            and (placebo + pd.Timedelta(minutes=65)) in bar_index
        )
        audits.append({
            **row.to_dict(),
            'pre_missing': int((~pre_idx.isin(bar_index)).sum()),
            'post60_missing': int((~post_idx.isin(bar_index)).sum()),
            'window90_missing': int((~full_idx.isin(bar_index)).sum()),
            'event_admitted': admitted,
            'placebo_clock': placebo,
            'placebo_admitted': placebo_admitted,
        })
    audit = pd.DataFrame(audits)
    counts = audit.groupby(['period','event_type'])['event_admitted'].agg(['count','sum']).reset_index()
    dev = counts[counts['period'] == 'development'].set_index('event_type')
    required = cfg['data_admission']['minimum_admitted_development_events']
    failures = []
    for et, minimum in required.items():
        admitted = int(dev.loc[et, 'sum']) if et in dev.index else 0
        if admitted < int(minimum):
            failures.append({'event_type': et, 'admitted': admitted, 'required': int(minimum)})

    event_csv = out_dir / 'events_audit.csv'
    audit.to_csv(event_csv, index=False)
    manifest_core = {
        'schema_version': 1,
        'protocol': cfg['protocol_name'],
        'research_semantics_changed': False,
        'strategy_scoring_performed': False,
        'market_source_commit': cfg['market_data']['commit'],
        'file_sha256': file_hashes,
        'official_event_count': int(len(audit)),
        'counts': counts.to_dict(orient='records'),
        'development_admission_failures': failures,
        'events_audit_sha256': sha256_file(event_csv),
    }
    manifest_bytes = json.dumps(manifest_core, sort_keys=True, separators=(',', ':')).encode()
    manifest_core['manifest_core_sha256'] = hashlib.sha256(manifest_bytes).hexdigest()
    (out_dir / 'manifest.json').write_text(json.dumps(manifest_core, indent=2))
    print(json.dumps(manifest_core, indent=2))
    if failures:
        raise SystemExit('frozen event/data admission rule failed')


if __name__ == '__main__':
    main()
