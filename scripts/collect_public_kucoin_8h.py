"""Auditable public Spot retrieval; fixed coverage, fail closed, no orders."""
import csv
import hashlib
import json
import math
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / 'config/public_kucoin_replication_v1.json'
OUT = ROOT / 'artifacts/public_kucoin_8h_20261010'
STEP = 28800


def stamp(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace('+00:00', 'Z')


def validate(rows, start, end):
    ordered = sorted(rows, key=lambda r: int(r[0]))
    if [int(r[0]) for r in ordered] != list(range(start, end, STEP)):
        raise ValueError('requested UTC grid incomplete, duplicate or misaligned; study rejected')
    for r in ordered:
        o, c, h, low, vol = map(float, r[1:6])
        if not all(math.isfinite(x) for x in (o, c, h, low, vol)) or not 0 < low <= min(o, c) <= max(o, c) <= h or vol < 0:
            raise ValueError('invalid OHLCV')
    return ordered


def request(url, path):
    before = datetime.now(timezone.utc).isoformat()
    with urllib.request.urlopen(url, timeout=30) as response:
        raw = response.read()
    with path.open('xb') as stream:
        stream.write(raw)
    value = json.loads(raw)
    if value['code'] != '200000':
        raise ValueError('unsuccessful KuCoin response')
    return value['data'], {'url': url, 'requested_at_utc': before,
                           'received_at_utc': datetime.now(timezone.utc).isoformat(),
                           'file': path.name, 'sha256': hashlib.sha256(raw).hexdigest()}


def main():
    design = json.loads(DESIGN.read_text())
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    committed = subprocess.check_output(['git', 'show', f'{commit}:config/public_kucoin_replication_v1.json'], cwd=ROOT)
    if committed != DESIGN.read_bytes():
        raise ValueError('design must be committed before retrieval')
    OUT.mkdir(exist_ok=False)
    raw_dir = OUT / 'raw'
    raw_dir.mkdir()
    csv_dir = OUT / 'aligned_csv'
    csv_dir.mkdir()
    manifest = {'design_commit': commit, 'design_sha256': hashlib.sha256(committed).hexdigest(),
                'study_id': design['study_id'], 'source': design['venue'], 'requests': [], 'symbols': {},
                'complete': False, 'no_forward_fill': True}
    start = int(datetime.fromisoformat(design['start_utc'].replace('Z', '+00:00')).timestamp())
    end = int(datetime.fromisoformat(design['end_exclusive_utc'].replace('Z', '+00:00')).timestamp())
    try:
        _, meta = request('https://api.kucoin.com/api/v2/symbols', raw_dir / 'symbols.json')
        manifest['requests'].append(meta)
        for symbol in design['symbols']:
            _, meta = request('https://api.kucoin.com/api/v1/market/orderbook/level2_20?symbol=' + symbol,
                              raw_dir / (symbol + '-book.json'))
            manifest['requests'].append(meta)
            rows = []
            for n, cursor in enumerate(range(start, end, STEP * 1000)):
                stop = min(end, cursor + STEP * 1000)
                query = urllib.parse.urlencode({'symbol': symbol, 'type': '8hour', 'startAt': cursor, 'endAt': stop - 1})
                page, meta = request(design['endpoint'] + '?' + query, raw_dir / f'{symbol}-{n}.json')
                manifest['requests'].append(meta)
                rows.extend(page)
                time.sleep(0.1)
            rows = validate(rows, start, end)
            path = csv_dir / (symbol.replace('-', '_') + '.csv')
            with path.open('x', encoding='utf-8', newline='') as stream:
                writer = csv.writer(stream, lineterminator='\n')
                writer.writerow(['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                writer.writerows([stamp(int(r[0])), r[1], r[3], r[4], r[2], r[5]] for r in rows)
            manifest['symbols'][symbol] = {'bars': len(rows), 'first': stamp(start), 'last': stamp(end - STEP),
                                           'csv_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            print(symbol, len(rows), flush=True)
        manifest['complete'] = True
    except Exception as error:
        manifest['failure'] = str(error)
        raise
    finally:
        (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
