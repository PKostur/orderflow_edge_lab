"""Continuous Spot minute source, hypothetical power and execution evidence audit.

No predictions, signals, historical fills, PnL or order transmission are implemented.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import io
import json
import math
import platform
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import NormalDist

from .btc_relative_state import write_csv, write_json
from .public_research_extensions import request_bytes, validate_checksum
from .public_strategy_shadow import iso, sha256_file, utc

SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'LINKUSDT')


def months_between(start: str, stop: str) -> list[str]:
    first, end = utc(start), utc(stop)
    if (first.day != 1 or end.day != 1 or first.time() != datetime.min.time()
            or end.time() != datetime.min.time() or first >= end):
        raise ValueError('whole positive UTC month range required')
    months = []
    while first < end:
        months.append(first.strftime('%Y-%m'))
        first = first.replace(year=first.year + (first.month == 12), month=first.month % 12 + 1)
    return months


def month_bounds(month: str) -> tuple[int, int]:
    start = utc(month + '-01T00:00:00Z')
    return int(start.timestamp()), calendar.monthrange(start.year, start.month)[1] * 1440


def verified_design(root: Path, path: Path, commit: str) -> dict:
    resolved = subprocess.check_output(['git', 'rev-parse', commit + '^{commit}'], cwd=root, text=True).strip()
    if len(commit) != 40 or resolved != commit:
        raise ValueError('full immutable design commit required')
    original = subprocess.check_output(['git', 'show', f'{commit}:{path.resolve().relative_to(root).as_posix()}'], cwd=root)
    if original != path.read_bytes():
        raise ValueError('design bytes changed')
    spec = json.loads(original)
    months = months_between(spec['start_utc'], spec['end_exclusive_utc'])
    expected = int((utc(spec['end_exclusive_utc']) - utc(spec['start_utc'])).total_seconds() / 60)
    if (spec['schema_version'] != 1 or tuple(spec['symbols']) != SYMBOLS or len(months) != spec['months']
            or len(months) * 4 != spec['archives'] or expected != spec['expected_minutes_per_symbol']
            or expected * 4 != spec['expected_panel_candles'] or spec['order_transmission_supported']
            or spec['retuning_permitted'] or not spec['bollinger_bands_excluded']):
        raise ValueError('unsupported or inconsistent research-only design')
    return spec


def audit_archive(path: Path, symbol: str, month: str) -> dict:
    """Audit all observed rows against the full grid; missing intervals are never filled."""
    start, expected = month_bounds(month)
    stop = start + expected * 60
    unit = 1_000_000 if month >= '2025-01' else 1000
    days = [{'day': iso(datetime.fromtimestamp(start + i * 86400, timezone.utc))[:10],
             'symbol': symbol, 'observed_minutes': 0, 'zero_trade_minutes': 0,
             'zero_volume_minutes': 0, 'status': 'AUDITED'} for i in range(expected // 1440)]
    observed, previous, gaps = 0, start - 60, []

    def gap(first, end):
        if first < end:
            gaps.append({'start_utc': iso(datetime.fromtimestamp(first, timezone.utc)),
                         'end_exclusive_utc': iso(datetime.fromtimestamp(end, timezone.utc)),
                         'missing_minutes': (end - first) // 60})

    with zipfile.ZipFile(path) as archive:
        files = archive.namelist()
        required = f'{symbol}-1m-{month}.csv'
        if files != [required] or archive.getinfo(required).file_size > 40_000_000:
            raise ValueError('archive_schema: exact monthly CSV member/size required')
        with archive.open(required) as stream:
            for line, r in enumerate(csv.reader(io.TextIOWrapper(stream, encoding='utf-8')), 1):
                if len(r) != 12:
                    raise ValueError(f'row_schema: line {line} requires 12 columns')
                try:
                    opened, closed = int(r[0]), int(r[6])
                    o, h, l, c, v, q, n, tb, tq = [float(r[j]) for j in (1, 2, 3, 4, 5, 7, 8, 9, 10)]
                except ValueError as exc:
                    raise ValueError(f'row_schema: invalid numeric field at line {line}') from exc
                if opened % (60 * unit) or closed != opened + 60 * unit - 1:
                    raise ValueError(f'timestamp_units_alignment: line {line}')
                t = opened // unit
                if t < start or t >= stop:
                    raise ValueError(f'timestamp_units_range: line {line}')
                if t <= previous:
                    raise ValueError(f'duplicate_or_reversed_timestamp: line {line}')
                if (not all(math.isfinite(x) for x in (o, h, l, c, v, q, n, tb, tq))
                        or min(o, h, l, c) <= 0 or min(v, q, n, tb, tq) < 0 or n != int(n)
                        or h < max(o, c, l) or l > min(o, c, h) or tb > v or tq > q):
                    raise ValueError(f'invalid_ohlcv_trade_count: line {line}')
                gap(previous + 60, t)
                day = days[(t - start) // 86400]
                day['observed_minutes'] += 1
                day['zero_trade_minutes'] += int(n == 0)
                day['zero_volume_minutes'] += int(v == 0)
                observed += 1
                previous = t
    gap(previous + 60, stop)
    missing = sum(g['missing_minutes'] for g in gaps)
    if observed + missing != expected:
        raise ValueError('grid accounting mismatch')
    for day in days:
        day['missing_minutes'] = 1440 - day['observed_minutes']
        day['complete_day'] = day['observed_minutes'] == 1440
    return {'observed_minutes': observed, 'expected_minutes': expected, 'missing_minutes': missing,
            'complete_month': not gaps, 'timestamp_unit': 'us' if unit == 1_000_000 else 'ms',
            'gaps': gaps, 'daily': days}


def planning_power(complete_weeks: int, spec: dict) -> dict:
    p = spec['power']
    required = math.ceil(((NormalDist().inv_cdf(1 - p['alpha']) + NormalDist().inv_cdf(p['power']))
                          / p['standardized_weekly_effect']) ** 2)
    inflated = required * p['four_week_inflation_multiplier']
    if required != p['independent_week_requirement'] or inflated != p['inflated_calendar_week_requirement']:
        raise ValueError('committed power arithmetic differs')
    return {'planning_only': True, 'standardized_effect_assumed_not_measured': p['standardized_weekly_effect'],
            'independent_week_requirement': required, 'inflated_calendar_week_requirement': inflated,
            'complete_shared_weeks': complete_weeks,
            'optimistic_independent_count_sufficient': complete_weeks >= required,
            'four_week_inflated_count_sufficient': complete_weeks >= inflated,
            'optimistic_four_week_count_equivalent_floor': complete_weeks // 4,
            'observed_paired_loss_variance': None, 'effective_independent_sample_size': None,
            'independence_established': False, 'adequate_power_established': False}


def complete_panel_weeks(daily: list[dict], spec: dict) -> list[str]:
    start, end = utc(spec['start_utc']), utc(spec['end_exclusive_utc'])
    expected_days = [iso(start + timedelta(days=i))[:10] for i in range((end - start).days)]
    by_day = {}
    for row in daily:
        key = (row['day'], row['symbol'])
        if key in by_day:
            raise ValueError('duplicate daily quality record')
        by_day[key] = row
    week = start + timedelta(days=(-start.weekday()) % 7)
    result = []
    while week + timedelta(days=7) <= end:
        days = [iso(week + timedelta(days=i))[:10] for i in range(7)]
        if all(by_day.get((d, s), {}).get('complete_day') is True for d in days for s in SYMBOLS):
            result.append(iso(week)[:10])
        week += timedelta(days=7)
    if any(d not in expected_days or s not in SYMBOLS for d, s in by_day):
        raise ValueError('unexpected daily panel record')
    return result


def source_task(raw: Path, symbol: str, month: str) -> tuple[dict, list[dict]]:
    name = f'{symbol}-1m-{month}.zip'
    url = f'https://data.binance.vision/data/spot/monthly/klines/{symbol}/1m/{name}'
    path, check, meta = raw / name, raw / (name + '.CHECKSUM'), raw / (name + '.receipt.json')
    checksum_meta = raw / (name + '.CHECKSUM.receipt.json')
    record = {'symbol': symbol, 'month': month, 'url': url,
              'raw_relative_path': name, 'checksum_relative_path': check.name, 'receipt_relative_path': meta.name,
              'checksum_receipt_relative_path': checksum_meta.name}
    try:
        if meta.exists():
            saved = json.loads(meta.read_text(encoding='utf-8'))
            if (saved['url'] != url or not path.is_file() or sha256_file(path) != saved['sha256']
                    or saved['bytes'] != path.stat().st_size):
                raise ValueError('invalid retained archive receipt/hash')
            record.update(saved)
        elif path.exists() or check.exists() or checksum_meta.exists():
            raise ValueError('unreceipted partial archive; preserve it and use a fresh raw directory')
        else:
            requested = iso(datetime.now(timezone.utc))
            payload = request_bytes(url)
            received = iso(datetime.now(timezone.utc))
            digest = hashlib.sha256(payload).hexdigest()
            saved = {'url': url, 'request_utc': requested, 'receipt_utc': received,
                     'sha256': digest, 'bytes': len(payload)}
            # Each task has distinct paths. Never replace prior retained bytes.
            with path.open('xb') as stream:
                stream.write(payload)
            with meta.open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(saved, stream, sort_keys=True, indent=2)
            record.update(saved)
        record['receipt_sha256'] = sha256_file(meta)
        if checksum_meta.exists():
            check_saved = json.loads(checksum_meta.read_text(encoding='utf-8'))
            if (check_saved['url'] != url + '.CHECKSUM' or not check.is_file()
                    or sha256_file(check) != check_saved['sha256']):
                raise ValueError('invalid retained checksum receipt/hash')
        else:
            if check.exists():
                raise ValueError('unreceipted partial checksum; preserve it and use a fresh raw directory')
            checksum_requested = iso(datetime.now(timezone.utc))
            checksum = request_bytes(url + '.CHECKSUM')
            check_saved = {'url': url + '.CHECKSUM', 'request_utc': checksum_requested,
                           'receipt_utc': iso(datetime.now(timezone.utc)),
                           'sha256': hashlib.sha256(checksum).hexdigest()}
            with check.open('xb') as stream:
                stream.write(checksum)
            with checksum_meta.open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(check_saved, stream, sort_keys=True, indent=2)
        record.update(checksum_sha256=check_saved['sha256'], checksum_request_utc=check_saved['request_utc'],
                      checksum_receipt_utc=check_saved['receipt_utc'], checksum_receipt_sha256=sha256_file(checksum_meta))
        validate_checksum(path.read_bytes(), check.read_bytes(), name)
        if sha256_file(check) != record['checksum_sha256'] or sha256_file(path) != record['sha256']:
            raise ValueError('retained receipt hash mismatch')
        if not (utc(record['request_utc']) <= utc(record['receipt_utc']) <= utc(record['checksum_request_utc'])
                <= utc(record['checksum_receipt_utc'])):
            raise ValueError('invalid receipt chronology')
        record['checksum_verified'] = True
        quality = audit_archive(path, symbol, month)
        daily = quality.pop('daily')
        record.update(quality, status='VERIFIED_COMPLETE' if quality['complete_month'] else 'VERIFIED_WITH_GAPS')
        return record, daily
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, csv.Error) as exc:
        record.update(status='SOURCE_FAILED', error=str(exc), failure_observed_utc=iso(datetime.now(timezone.utc)))
        first, count = month_bounds(month)
        daily = [{'symbol': symbol, 'day': iso(datetime.fromtimestamp(first + i * 86400, timezone.utc))[:10],
                  'status': 'SOURCE_FAILED', 'observed_minutes': None, 'missing_minutes': None,
                  'zero_trade_minutes': None, 'zero_volume_minutes': None, 'complete_day': False}
                 for i in range(count // 1440)]
        return record, daily


def execution_prefix_probe(raw: Path, family: str, symbol: str, bucket: str) -> dict:
    prefix = f'data/spot/monthly/{family}/{symbol}/'
    url = bucket + '?' + urllib.parse.urlencode({'prefix': prefix, 'max-keys': 1000})
    requested = iso(datetime.now(timezone.utc))
    token = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    path = raw / f'{family}-{symbol}-{token}-{uuid.uuid4().hex}-listing.bin'
    output = {'prefix': prefix, 'url': url, 'request_utc': requested, 'historical_execution_calibrated': False}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'orderflow-research-source-audit'}),
                                    timeout=30) as response:
            payload, status = response.read(), response.status
        received = iso(datetime.now(timezone.utc))
        with path.open('xb') as stream:
            stream.write(payload)
        output.update(http_status=status, receipt_utc=received, sha256=sha256_file(path), raw_relative_path=path.name)
        tree = ET.fromstring(payload)
        if (tree.tag.split('}')[-1] != 'ListBucketResult' or tree.findtext('{*}Prefix') != prefix
                or tree.findtext('{*}IsTruncated') not in ('true', 'false')):
            raise ValueError('unexpected bucket listing schema/prefix')
        keys = [node.findtext('{*}Key') for node in tree.findall('{*}Contents')]
        if any(not k or not k.startswith(prefix) for k in keys):
            raise ValueError('listing contains other prefix')
        output.update(http_status=status, receipt_utc=received, sha256=sha256_file(path),
                      raw_relative_path=path.name, listed_object_count=len(keys), first_page_keys=keys,
                      is_truncated=tree.findtext('{*}IsTruncated') == 'true',
                      status='OBJECTS_LISTED_NOT_EXECUTION_VALIDATION' if keys else 'NO_OBJECTS_AT_PROBED_PREFIX')
    except (OSError, ValueError, ET.ParseError) as exc:
        if isinstance(exc, urllib.error.HTTPError):
            payload = exc.read()
            received = iso(datetime.now(timezone.utc))
            with path.open('xb') as stream:
                stream.write(payload)
            output.update(http_status=exc.code, raw_relative_path=path.name, sha256=sha256_file(path), receipt_utc=received)
        observed = iso(datetime.now(timezone.utc))
        output.update(status='PREFIX_ACCESS_UNCONFIRMED', error=str(exc), failure_observed_utc=observed)
        output.setdefault('receipt_utc', observed)
    return output


def final_assessment(records: list[dict], daily: list[dict], probes: list[dict], spec: dict) -> dict:
    if len(records) != spec['archives'] or len(daily) != 4 * (utc(spec['end_exclusive_utc']) - utc(spec['start_utc'])).days:
        raise ValueError('incomplete source task accounting')
    expected_tasks = {(s, m) for m in months_between(spec['start_utc'], spec['end_exclusive_utc']) for s in SYMBOLS}
    actual_tasks = [(r['symbol'], r['month']) for r in records]
    if len(set(actual_tasks)) != len(actual_tasks) or set(actual_tasks) != expected_tasks:
        raise ValueError('source task identities differ from design')
    for r in records:
        if r['status'] != 'SOURCE_FAILED':
            expected = month_bounds(r['month'])[1]
            if (not r.get('checksum_verified') or r['expected_minutes'] != expected
                    or r['observed_minutes'] + r['missing_minutes'] != expected
                    or (r['status'] == 'VERIFIED_COMPLETE') != (r['missing_minutes'] == 0)):
                raise ValueError('source quality accounting mismatch')
    weeks = complete_panel_weeks(daily, spec)
    complete = all(r['status'] == 'VERIFIED_COMPLETE' for r in records)
    failures = [r for r in records if r['status'] == 'SOURCE_FAILED']
    gaps = [r for r in records if r['status'] == 'VERIFIED_WITH_GAPS']
    power = planning_power(len(weeks), spec)
    scenarios = [{'roundtrip_cost_bps': x, 'fee_bps_per_side': spec['execution']['assumed_fee_bps_per_side'],
                  'extra_roundtrip_assumption_bps': extra, 'historically_calibrated': False}
                 for x, extra in zip(spec['execution']['roundtrip_cost_scenarios_bps'],
                                     spec['execution']['assumed_extra_roundtrip_bps'])]
    if any(x['roundtrip_cost_bps'] != x['fee_bps_per_side'] * 2 + x['extra_roundtrip_assumption_bps'] for x in scenarios):
        raise ValueError('cost arithmetic differs')
    return {'source_complete_continuous_panel': complete, 'source_tasks': len(records),
            'checksum_verified_archives': sum(r.get('checksum_verified', False) for r in records),
            'source_failed_months': len(failures), 'verified_months_with_gaps': len(gaps),
            'observed_valid_candles': sum(r.get('observed_minutes', 0) for r in records),
            'missing_minutes_in_verified_archives': sum(r.get('missing_minutes', 0) for r in records),
            'expected_panel_candles': spec['expected_panel_candles'],
            'full_calendar_weeks_before_gaps': spec['power']['full_calendar_weeks_before_source_gaps'],
            'complete_shared_week_starts': weeks, 'power': power, 'execution_prefix_probes': probes,
            'historical_execution_calibrated': False, 'required_missing_execution_evidence': spec['execution']['required_for_historical_readiness'],
            'cost_scenarios_assumptions_only': scenarios, 'primary_stress_bps': spec['execution']['primary_stress_bps'],
            'research_readiness': False,
            'blocking_reasons': ([] if complete else ['continuous_source_panel_failed'])
                + ['independence_and_loss_variance_unestablished', 'four_week_power_scenario_insufficient',
                   'historical_execution_evidence_unconfirmed'],
            'disposition': 'FEASIBILITY_STUDY_COMPLETE_RESEARCH_READINESS_BLOCKED',
            'prediction': 'NOT_DESIGNED_NOT_RUN', 'economics': 'NOT_DESIGNED_NOT_RUN', 'trade_count': None,
            'new_predictor_hypotheses': 0, 'new_trading_cells': 0, 'verified_out_of_sample_evidence': False,
            'order_transmission_supported': False, 'prospective_start_utc': None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--design-commit', required=True)
    parser.add_argument('--raw-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    spec = verified_design(root, args.spec, args.design_commit)
    raw_path, output_path = args.raw_dir.resolve(), args.output_dir.resolve()
    if raw_path.is_relative_to(output_path) or output_path.is_relative_to(raw_path):
        raise ValueError('separate raw and report directories required')
    args.output_dir.mkdir(parents=True, exist_ok=False)
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    identity = {'study_id': spec['study_id'], 'design_commit': args.design_commit,
                'spec_sha256': sha256_file(args.spec)}
    binding = args.raw_dir / 'design_binding.json'
    if binding.exists():
        if json.loads(binding.read_text()) != identity:
            raise ValueError('raw directory belongs to another design')
    else:
        if any(args.raw_dir.iterdir()):
            raise ValueError('unbound nonempty raw directory')
        write_json(binding, identity)
    months = months_between(spec['start_utc'], spec['end_exclusive_utc'])
    tasks = [(s, month) for month in months for s in SYMBOLS]
    records, daily = [], []
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = executor.map(lambda task: source_task(args.raw_dir, *task), tasks)
        for record, days in results:
            records.append(record)
            daily.extend(days)
            print(record['month'], record['symbol'], record['status'], len(records), '/', len(tasks), flush=True)
    probes = [execution_prefix_probe(args.raw_dir, family, s, spec['execution']['historical_probe_bucket'])
              for family in spec['execution']['historical_probe_families'] for s in SYMBOLS]
    result = final_assessment(records, daily, probes, spec)
    write_json(args.output_dir / 'source_manifest.json', records)
    write_csv(args.output_dir / 'daily_quality.csv', daily)
    result.update(identity, source_start_utc=spec['start_utc'], source_end_exclusive_utc=spec['end_exclusive_utc'],
                  repository_head_at_run=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                  implementation_sha256=sha256_file(Path(__file__)), runtime={'python': platform.python_version()},
                  trial_accounting=spec['trial_accounting'],
                  raw_storage_note='exact bytes retained separately; names relative to --raw-dir in source manifest',
                  raw_total_bytes=sum(p.stat().st_size for p in args.raw_dir.iterdir() if p.is_file()),
                  output_sha256={name: sha256_file(args.output_dir / name) for name in ('source_manifest.json', 'daily_quality.csv')})
    write_json(args.output_dir / 'report.json', result)
    print(json.dumps({k: result[k] for k in ('study_id', 'disposition', 'observed_valid_candles', 'blocking_reasons')}))


if __name__ == '__main__':
    main()
