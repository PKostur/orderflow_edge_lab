'''Opt-in causal feature, target, and state-discovery contracts (v2).

Legacy streams, scans, BTC panels, and condition reports are deliberately not
modified. This successor is offline only and cannot collect data, schedule work,
use credentials, authorize promotion, or route orders.
'''
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

from orderflow_edge_lab.contracts_v2 import (
    CLOSED_OPEN,
    OPEN_CLOSED,
    ContractValidationError,
    build_canonical_source_set,
    build_file_identity,
    build_manifest_result,
    build_source_record,
    build_utc_interval,
    canonical_json_bytes,
    canonical_json_sha256,
    missing_value,
    non_authority_claims,
    observed_value,
    source_sets_equal,
    validate_canonical_source_set,
    validate_manifest_result,
    validate_non_authority_claims,
    validate_utc_interval,
)
from orderflow_edge_lab.orthogonality import (
    OrthogonalityError,
    build_orthogonality_report,
    incremental_information,
)

UTC = timezone.utc
FEATURE_POLICY_SCHEMA = 'orderflow_edge_lab.causal_feature_policy.v2'
QUOTE_PROVENANCE_SCHEMA = 'orderflow_edge_lab.quote_provenance.v2'
TARGET_SCHEMA = 'orderflow_edge_lab.mature_target.v2'
FEATURE_ELIGIBILITY_SCHEMA = 'orderflow_edge_lab.feature_eligibility.v2'
SCAN_SCHEMA = 'orderflow_edge_lab.causal_market_state_scan.v2'
ORTHOGONALITY_POLICY_SCHEMA = 'orderflow_edge_lab.full_baseline_orthogonality_policy.v2'
ORTHOGONALITY_SCHEMA = 'orderflow_edge_lab.full_baseline_orthogonality.v2'
BTC_POLICY_SCHEMA = 'orderflow_edge_lab.btc_correlation_input_policy.v2'
BTC_INPUT_SCHEMA = 'orderflow_edge_lab.btc_correlation_input.v2'
BTC_PANEL_SCHEMA = 'orderflow_edge_lab.btc_correlation_panel.v2'
STATE_DISCOVERY_SCHEMA = 'orderflow_edge_lab.state_discovery.v2'
PNL_REPORT_SCHEMA = 'orderflow_edge_lab.conditioned_pnl_barrier.v2'
CAPTURE_PAIR_BINDING_SCHEMA = 'orderflow_edge_lab.capture_pair_binding.v2'
LINEAGE_SCHEMA = 'orderflow_edge_lab.state_hypothesis_trial_lineage.v2'


class FeatureV2Error(ValueError):
    '''Raised when a v2 causal-feature input is malformed or ineligible.'''


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise FeatureV2Error(f'{name} must be an object with string keys')
    return value


def _exact_keys(value: Mapping[str, Any], keys: set[str], name: str) -> None:
    if set(value) != keys:
        missing = sorted(keys - set(value))
        extra = sorted(set(value) - keys)
        parts = []
        if missing:
            parts.append('missing=' + ','.join(missing))
        if extra:
            parts.append('extra=' + ','.join(extra))
        raise FeatureV2Error(f"{name} has unsupported shape ({'; '.join(parts)})")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FeatureV2Error(f'{name} must be a nonempty string')
    return value.strip()


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value.lower()):
        raise FeatureV2Error(f'{name} must be a 64-character hexadecimal SHA-256')
    return value.lower()


def _int(value: object, name: str, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise FeatureV2Error(f'{name} must be an integer')
    if minimum is not None and value < minimum:
        raise FeatureV2Error(f'{name} must be >= {minimum}')
    return value


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FeatureV2Error(f'{name} must be a finite number')
    output = float(value)
    if not math.isfinite(output):
        raise FeatureV2Error(f'{name} must be a finite number')
    return output


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise FeatureV2Error(f'{name} must be a timezone-aware ISO-8601 string')
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError as exc:
        raise FeatureV2Error(f'{name} must be a timezone-aware ISO-8601 string') from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FeatureV2Error(f'{name} must include a timezone')
    return parsed.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace('+00:00', 'Z')


def _ns_to_utc(ns: int) -> str:
    return _format_utc(datetime.fromtimestamp(ns / 1_000_000_000, tz=UTC))


def _utc_to_ns(value: str, name: str) -> int:
    return int(_utc(value, name).timestamp() * 1_000_000_000)


def _json_copy(value: object) -> Any:
    try:
        return json.loads(canonical_json_bytes(value).decode('utf-8'))
    except ContractValidationError as exc:
        raise FeatureV2Error(str(exc)) from exc


def _result(unsigned: Mapping[str, Any], hash_key: str) -> dict[str, Any]:
    normalized = _json_copy(dict(unsigned))
    return {**normalized, hash_key: canonical_json_sha256(normalized)}


def _validate_result_hash(value: Mapping[str, Any], hash_key: str, name: str) -> dict[str, Any]:
    raw = _mapping(value, name)
    if hash_key not in raw:
        raise FeatureV2Error(f'{name}.{hash_key} is required')
    unsigned = dict(raw)
    supplied = _sha(unsigned.pop(hash_key), f'{name}.{hash_key}')
    try:
        expected = canonical_json_sha256(unsigned)
    except ContractValidationError as exc:
        raise FeatureV2Error(str(exc)) from exc
    if supplied != expected:
        raise FeatureV2Error(f'{name}.{hash_key} does not match canonical content')
    return _json_copy(raw)


def _source_set(value: object, name: str = 'source_set') -> dict[str, Any]:
    try:
        return validate_canonical_source_set(_mapping(value, name))
    except ContractValidationError as exc:
        raise FeatureV2Error(str(exc)) from exc


def _claims(value: object, name: str = 'non_authority_claims') -> dict[str, bool]:
    try:
        return validate_non_authority_claims(_mapping(value, name))
    except ContractValidationError as exc:
        raise FeatureV2Error(str(exc)) from exc


def _same_source(left: Mapping[str, Any], right: Mapping[str, Any], name: str) -> None:
    try:
        equal = source_sets_equal(left, right)
    except ContractValidationError as exc:
        raise FeatureV2Error(str(exc)) from exc
    if not equal:
        raise FeatureV2Error(f'{name} source_set does not match exactly')


def _validate_lifecycle(
    frozen_at_utc: object,
    evidence_start_utc: object,
    lifecycle: object,
    freeze_evidence_sha256: object,
    name: str,
) -> tuple[str, str, str, str | None]:
    frozen = _format_utc(_utc(frozen_at_utc, f'{name}.frozen_at_utc'))
    start = _format_utc(_utc(evidence_start_utc, f'{name}.evidence_start_utc'))
    if _utc(frozen, f'{name}.frozen_at_utc') > _utc(start, f'{name}.evidence_start_utc'):
        raise FeatureV2Error(f'{name}.frozen_at_utc must not be after evidence_start_utc')
    status = _text(lifecycle, f'{name}.lifecycle')
    if status not in {'DECLARED_INACTIVE', 'FROZEN_FOR_NEW_EVIDENCE'}:
        raise FeatureV2Error(f'{name}.lifecycle must be DECLARED_INACTIVE or FROZEN_FOR_NEW_EVIDENCE')
    if status == 'FROZEN_FOR_NEW_EVIDENCE':
        return frozen, start, status, _sha(freeze_evidence_sha256, f'{name}.freeze_evidence_sha256')
    if freeze_evidence_sha256 is not None:
        raise FeatureV2Error(f'{name}.freeze_evidence_sha256 must be null while inactive')
    return frozen, start, status, None


def _validate_quote_policy(value: object) -> dict[str, Any]:
    raw = _mapping(value, 'policy.quote')
    _exact_keys(raw, {
        'accepted_event_types', 'max_quote_age_ns', 'max_context_quote_age_ns',
        'require_exchange_timestamp', 'allow_recovered_book',
        'recovered_book_cooldown_ns', 'require_context_quote',
    }, 'policy.quote')
    accepted = raw['accepted_event_types']
    if not isinstance(accepted, list) or not accepted:
        raise FeatureV2Error('policy.quote.accepted_event_types must be a nonempty list')
    accepted_out = [_text(item, 'policy.quote.accepted_event_types[]') for item in accepted]
    if sorted(set(accepted_out)) != sorted(accepted_out):
        raise FeatureV2Error('policy.quote.accepted_event_types must be unique')
    if any(item not in {'snapshot', 'depth'} for item in accepted_out):
        raise FeatureV2Error('policy.quote.accepted_event_types may contain only snapshot/depth')
    for key in ('require_exchange_timestamp', 'allow_recovered_book', 'require_context_quote'):
        if type(raw[key]) is not bool:
            raise FeatureV2Error(f'policy.quote.{key} must be boolean')
    return {
        'accepted_event_types': sorted(accepted_out),
        'max_quote_age_ns': _int(raw['max_quote_age_ns'], 'policy.quote.max_quote_age_ns', minimum=0),
        'max_context_quote_age_ns': _int(raw['max_context_quote_age_ns'], 'policy.quote.max_context_quote_age_ns', minimum=0),
        'require_exchange_timestamp': raw['require_exchange_timestamp'],
        'allow_recovered_book': raw['allow_recovered_book'],
        'recovered_book_cooldown_ns': _int(raw['recovered_book_cooldown_ns'], 'policy.quote.recovered_book_cooldown_ns', minimum=0),
        'require_context_quote': raw['require_context_quote'],
    }


def _validate_target_spec(value: object) -> dict[str, Any]:
    raw = _mapping(value, 'policy.targets[]')
    _exact_keys(raw, {'target_id', 'horizon_ns', 'max_endpoint_lag_ns', 'max_interior_gap_ns', 'minimum_quote_points'}, 'policy.targets[]')
    return {
        'target_id': _text(raw['target_id'], 'policy.targets[].target_id'),
        'horizon_ns': _int(raw['horizon_ns'], 'policy.targets[].horizon_ns', minimum=1),
        'max_endpoint_lag_ns': _int(raw['max_endpoint_lag_ns'], 'policy.targets[].max_endpoint_lag_ns', minimum=0),
        'max_interior_gap_ns': _int(raw['max_interior_gap_ns'], 'policy.targets[].max_interior_gap_ns', minimum=0),
        'minimum_quote_points': _int(raw['minimum_quote_points'], 'policy.targets[].minimum_quote_points', minimum=1),
    }


def build_feature_policy_v2(declaration: Mapping[str, Any]) -> dict[str, Any]:
    '''Build a caller-declared successor policy; it never verifies the freeze.'''
    raw = _mapping(declaration, 'feature policy declaration')
    _exact_keys(raw, {
        'policy_id', 'frozen_at_utc', 'evidence_start_utc', 'lifecycle',
        'freeze_evidence_sha256', 'quote', 'scan', 'targets',
    }, 'feature policy declaration')
    frozen, evidence_start, lifecycle, freeze_hash = _validate_lifecycle(
        raw['frozen_at_utc'], raw['evidence_start_utc'], raw['lifecycle'], raw['freeze_evidence_sha256'], 'feature policy'
    )
    scan_raw = _mapping(raw['scan'], 'policy.scan')
    _exact_keys(scan_raw, {'analysis_interval', 'sample_cadence_ns', 'context_lookback_ns', 'minimum_association_observations'}, 'policy.scan')
    try:
        interval = validate_utc_interval(_mapping(scan_raw['analysis_interval'], 'policy.scan.analysis_interval'))
    except ContractValidationError as exc:
        raise FeatureV2Error(str(exc)) from exc
    if interval['convention'] != CLOSED_OPEN:
        raise FeatureV2Error('policy.scan.analysis_interval must use CLOSED_OPEN')
    if _utc(interval['start_utc'], 'policy.scan.analysis_interval.start_utc') < _utc(evidence_start, 'policy.evidence_start_utc'):
        raise FeatureV2Error('policy.scan.analysis_interval starts before evidence_start_utc')
    targets_raw = raw['targets']
    if not isinstance(targets_raw, list) or not targets_raw:
        raise FeatureV2Error('policy.targets must be a nonempty list')
    targets = [_validate_target_spec(item) for item in targets_raw]
    if len({item['target_id'] for item in targets}) != len(targets):
        raise FeatureV2Error('policy.targets target_id values must be unique')
    targets.sort(key=lambda item: item['target_id'])
    unsigned = {
        'schema': FEATURE_POLICY_SCHEMA,
        'analysis': 'caller_declared_causal_feature_policy',
        'policy_id': _text(raw['policy_id'], 'policy.policy_id'),
        'frozen_at_utc': frozen,
        'evidence_start_utc': evidence_start,
        'lifecycle': lifecycle,
        'freeze_evidence_sha256': freeze_hash,
        'freeze_verification': 'CALLER_DECLARED_LOCAL_IDENTITY_ONLY',
        'quote': _validate_quote_policy(raw['quote']),
        'scan': {
            'analysis_interval': interval,
            'sample_cadence_ns': _int(scan_raw['sample_cadence_ns'], 'policy.scan.sample_cadence_ns', minimum=1),
            'context_lookback_ns': _int(scan_raw['context_lookback_ns'], 'policy.scan.context_lookback_ns', minimum=1),
            'minimum_association_observations': _int(scan_raw['minimum_association_observations'], 'policy.scan.minimum_association_observations', minimum=2),
        },
        'targets': targets,
        'non_authority_claims': non_authority_claims(),
    }
    return _result(unsigned, 'policy_sha256')


def validate_feature_policy_v2(policy: Mapping[str, Any]) -> dict[str, Any]:
    raw = _validate_result_hash(policy, 'policy_sha256', 'feature policy')
    _exact_keys(raw, {
        'schema', 'analysis', 'policy_id', 'frozen_at_utc', 'evidence_start_utc', 'lifecycle',
        'freeze_evidence_sha256', 'freeze_verification', 'quote', 'scan', 'targets',
        'non_authority_claims', 'policy_sha256',
    }, 'feature policy')
    if raw['schema'] != FEATURE_POLICY_SCHEMA or raw['analysis'] != 'caller_declared_causal_feature_policy':
        raise FeatureV2Error('feature policy schema/analysis is unsupported')
    if raw['freeze_verification'] != 'CALLER_DECLARED_LOCAL_IDENTITY_ONLY':
        raise FeatureV2Error('feature policy may not claim external freeze verification')
    rebuilt = build_feature_policy_v2({
        'policy_id': raw['policy_id'], 'frozen_at_utc': raw['frozen_at_utc'],
        'evidence_start_utc': raw['evidence_start_utc'], 'lifecycle': raw['lifecycle'],
        'freeze_evidence_sha256': raw['freeze_evidence_sha256'], 'quote': raw['quote'],
        'scan': raw['scan'], 'targets': raw['targets'],
    })
    if rebuilt != raw:
        raise FeatureV2Error('feature policy is not normalized canonical policy content')
    _claims(raw['non_authority_claims'])
    return raw


def _validate_capture_pair(value: Mapping[str, Any], source_set: Mapping[str, Any]) -> dict[str, Any]:
    raw = _validate_result_hash(value, 'capture_pair_sha256', 'capture_pair')
    _exact_keys(raw, {
        'schema', 'analysis', 'source_set', 'outcome', 'replay_status',
        'capture_start_utc', 'capture_end_utc', 'non_authority_claims', 'capture_pair_sha256',
    }, 'capture_pair')
    if raw['schema'] != CAPTURE_PAIR_BINDING_SCHEMA or raw['analysis'] != 'capture_pair_replay_eligibility':
        raise FeatureV2Error('capture_pair schema/analysis is unsupported')
    if raw['outcome'] != 'COMPLETE' or raw['replay_status'] != 'REPLAY_ELIGIBLE':
        raise FeatureV2Error('capture_pair must be COMPLETE and REPLAY_ELIGIBLE')
    normalized_source = _source_set(raw['source_set'], 'capture_pair.source_set')
    _same_source(normalized_source, source_set, 'capture_pair')
    start = _format_utc(_utc(raw['capture_start_utc'], 'capture_pair.capture_start_utc'))
    end = _format_utc(_utc(raw['capture_end_utc'], 'capture_pair.capture_end_utc'))
    if _utc(end, 'capture_pair.capture_end_utc') <= _utc(start, 'capture_pair.capture_start_utc'):
        raise FeatureV2Error('capture_pair capture interval must be positive')
    _claims(raw['non_authority_claims'])
    return {**raw, 'source_set': normalized_source, 'capture_start_utc': start, 'capture_end_utc': end}


def _number_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _quote_values(event: Mapping[str, Any]) -> tuple[dict[str, float] | None, str | None]:
    bid = _number_or_none(event.get('best_bid'))
    ask = _number_or_none(event.get('best_ask'))
    if bid is None or ask is None or bid <= 0 or ask <= bid:
        return None, 'INVALID_BBO'
    bid_qty = _number_or_none(event.get('best_bid_contract_volume', event.get('best_bid_qty')))
    ask_qty = _number_or_none(event.get('best_ask_contract_volume', event.get('best_ask_qty')))
    mid = (bid + ask) / 2.0
    values: dict[str, float] = {
        'best_bid': bid,
        'best_ask': ask,
        'mid': mid,
        'spread_bps': (ask - bid) / mid * 10_000.0,
    }
    if bid_qty is not None and ask_qty is not None and bid_qty >= 0 and ask_qty >= 0:
        values['top_depth_notional'] = bid * bid_qty + ask * ask_qty
    micro = _number_or_none(event.get('microprice'))
    if micro is not None:
        values['microprice_edge_spread_units'] = (micro - mid) / ((ask - bid) / 2.0)
    imbalance = _number_or_none(event.get('book_imbalance_10'))
    if imbalance is not None:
        values['book_imbalance_10'] = imbalance
    depth_flow = _number_or_none(event.get('depth_flow_imbalance'))
    if depth_flow is not None:
        values['depth_flow_imbalance'] = depth_flow
    return values, None


def build_quote_provenance_v2(
    quote_event: Mapping[str, Any] | None,
    *,
    feature_received_at_ns: int,
    source_set: Mapping[str, Any],
    policy: Mapping[str, Any],
    role: str = 'primary',
) -> dict[str, Any]:
    '''Bind one feature-time quote to its original accepted depth/snapshot event.'''
    normalized_policy = validate_feature_policy_v2(policy)
    sources = _source_set(source_set)
    feature_ns = _int(feature_received_at_ns, 'feature_received_at_ns', minimum=0)
    if role not in {'primary', 'context'}:
        raise FeatureV2Error('role must be primary or context')
    base = {
        'schema': QUOTE_PROVENANCE_SCHEMA,
        'analysis': 'quote_provenance_and_freshness',
        'source_set': sources,
        'policy_sha256': normalized_policy['policy_sha256'],
        'role': role,
        'feature_received_at_ns': feature_ns,
        'feature_received_at_utc': _ns_to_utc(feature_ns),
        'quote_source_event_type': None,
        'quote_received_at_ns': None,
        'quote_received_at_utc': None,
        'quote_exchange_ts_ms': None,
        'quote_age_ns_at_feature': None,
        'quote_values': None,
        'quote_is_fresh': False,
        'eligibility': 'INELIGIBLE',
        'eligibility_reason': None,
        'non_authority_claims': non_authority_claims(),
    }
    if quote_event is None:
        return _result({**base, 'eligibility_reason': 'MISSING_QUOTE_PROVENANCE'}, 'quote_provenance_sha256')
    event = _mapping(quote_event, 'quote_event')
    event_type = event.get('event_type')
    received = event.get('received_at_ns')
    if type(received) is not int or received < 0:
        return _result({**base, 'eligibility_reason': 'MISSING_QUOTE_RECEIPT_TIME'}, 'quote_provenance_sha256')
    exchange = event.get('exchange_ts_ms')
    exchange_value = exchange if type(exchange) is int and exchange >= 0 else None
    values, invalid_reason = _quote_values(event)
    filled = {
        **base,
        'quote_source_event_type': event_type if isinstance(event_type, str) else None,
        'quote_received_at_ns': received,
        'quote_received_at_utc': _ns_to_utc(received),
        'quote_exchange_ts_ms': exchange_value,
        'quote_age_ns_at_feature': feature_ns - received,
        'quote_values': values,
    }
    if event_type not in normalized_policy['quote']['accepted_event_types']:
        return _result({**filled, 'eligibility_reason': 'EVENT_NOT_ACCEPTED_QUOTE_SOURCE'}, 'quote_provenance_sha256')
    if event_type == 'depth' and event.get('depth_applied') is not True:
        return _result({**filled, 'eligibility_reason': 'DEPTH_NOT_ACCEPTED_TRANSITION'}, 'quote_provenance_sha256')
    if invalid_reason is not None:
        return _result({**filled, 'eligibility_reason': invalid_reason}, 'quote_provenance_sha256')
    if normalized_policy['quote']['require_exchange_timestamp'] and exchange_value is None:
        return _result({**filled, 'eligibility_reason': 'MISSING_EXCHANGE_TIMESTAMP'}, 'quote_provenance_sha256')
    age = feature_ns - received
    if age < 0:
        return _result({**filled, 'eligibility_reason': 'FEATURE_BEFORE_QUOTE'}, 'quote_provenance_sha256')
    recovered = event.get('recovered_book') is True
    if recovered and not normalized_policy['quote']['allow_recovered_book']:
        return _result({**filled, 'eligibility_reason': 'RECOVERED_BOOK_PROHIBITED'}, 'quote_provenance_sha256')
    if recovered and age < normalized_policy['quote']['recovered_book_cooldown_ns']:
        return _result({**filled, 'eligibility_reason': 'RECOVERY_COOLDOWN'}, 'quote_provenance_sha256')
    maximum = normalized_policy['quote']['max_context_quote_age_ns'] if role == 'context' else normalized_policy['quote']['max_quote_age_ns']
    if age > maximum:
        return _result({**filled, 'eligibility_reason': 'QUOTE_STALE'}, 'quote_provenance_sha256')
    return _result({**filled, 'quote_is_fresh': True, 'eligibility': 'ELIGIBLE', 'eligibility_reason': 'FRESH_ACCEPTED_QUOTE'}, 'quote_provenance_sha256')


def validate_quote_provenance_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _validate_result_hash(value, 'quote_provenance_sha256', 'quote_provenance')
    required = {
        'schema', 'analysis', 'source_set', 'policy_sha256', 'role', 'feature_received_at_ns',
        'feature_received_at_utc', 'quote_source_event_type', 'quote_received_at_ns',
        'quote_received_at_utc', 'quote_exchange_ts_ms', 'quote_age_ns_at_feature', 'quote_values',
        'quote_is_fresh', 'eligibility', 'eligibility_reason', 'non_authority_claims', 'quote_provenance_sha256',
    }
    _exact_keys(raw, required, 'quote_provenance')
    if raw['schema'] != QUOTE_PROVENANCE_SCHEMA or raw['analysis'] != 'quote_provenance_and_freshness':
        raise FeatureV2Error('quote_provenance schema/analysis is unsupported')
    _source_set(raw['source_set'], 'quote_provenance.source_set')
    _sha(raw['policy_sha256'], 'quote_provenance.policy_sha256')
    _claims(raw['non_authority_claims'])
    if raw['eligibility'] not in {'ELIGIBLE', 'INELIGIBLE'} or type(raw['quote_is_fresh']) is not bool:
        raise FeatureV2Error('quote_provenance eligibility fields are invalid')
    if raw['eligibility'] == 'ELIGIBLE' and raw['quote_is_fresh'] is not True:
        raise FeatureV2Error('eligible quote_provenance must be fresh')
    return raw


def _target_points(points: Sequence[Mapping[str, Any]], source_set: Mapping[str, Any], policy_sha: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, item in enumerate(points):
        quote = validate_quote_provenance_v2(item)
        _same_source(quote['source_set'], source_set, f'target quote {index}')
        if quote['policy_sha256'] != policy_sha:
            raise FeatureV2Error('target quote policy_sha256 does not match')
        if quote['eligibility'] != 'ELIGIBLE' or quote['quote_values'] is None:
            continue
        output.append(quote)
    output.sort(key=lambda item: int(item['quote_received_at_ns']))
    times = [int(item['quote_received_at_ns']) for item in output]
    if len(times) != len(set(times)):
        raise FeatureV2Error('target quote points must have unique receipt timestamps')
    return output


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _return_bps(start: float, end: float) -> float | None:
    if start <= 0 or end <= 0:
        return None
    result = (end / start - 1.0) * 10_000.0
    return result if math.isfinite(result) else None


def build_mature_target_v2(
    anchor_quote: Mapping[str, Any],
    quote_points: Sequence[Mapping[str, Any]],
    *,
    target_spec: Mapping[str, Any],
    capture_end_ns: int,
    source_set: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    '''Build a strictly post-anchor target and its complete maturity/coverage record.'''
    normalized_policy = validate_feature_policy_v2(policy)
    sources = _source_set(source_set)
    anchor = validate_quote_provenance_v2(anchor_quote)
    _same_source(anchor['source_set'], sources, 'anchor_quote')
    if anchor['policy_sha256'] != normalized_policy['policy_sha256']:
        raise FeatureV2Error('anchor_quote policy_sha256 does not match')
    spec = _validate_target_spec(target_spec)
    known_specs = {item['target_id']: item for item in normalized_policy['targets']}
    if known_specs.get(spec['target_id']) != spec:
        raise FeatureV2Error('target_spec is not an exact caller-declared policy target')
    capture_end = _int(capture_end_ns, 'capture_end_ns', minimum=0)
    if anchor['eligibility'] != 'ELIGIBLE' or anchor['quote_values'] is None:
        raise FeatureV2Error('anchor_quote must be an eligible primary quote')
    anchor_ns = int(anchor['feature_received_at_ns'])
    end_ns = anchor_ns + spec['horizon_ns']
    interval = build_utc_interval(_ns_to_utc(anchor_ns), _ns_to_utc(end_ns), convention=OPEN_CLOSED)
    points = _target_points(quote_points, sources, normalized_policy['policy_sha256'])
    future = [item for item in points if anchor_ns < int(item['quote_received_at_ns']) <= end_ns]
    endpoint_candidates = [item for item in points if int(item['quote_received_at_ns']) >= end_ns]
    endpoint = endpoint_candidates[0] if endpoint_candidates else None
    gaps: list[int] = []
    future_times = [int(item['quote_received_at_ns']) for item in future]
    if future_times:
        gaps.append(future_times[0] - anchor_ns)
        gaps.extend(right - left for left, right in zip(future_times, future_times[1:]))
        gaps.append(end_ns - future_times[-1])
    max_gap = max(gaps) if gaps else None
    reason: str | None = None
    maturity = 'MATURE'
    if capture_end < end_ns:
        maturity, reason = 'NOT_MATURE', 'CAPTURE_ENDED_BEFORE_HORIZON'
    elif not future:
        maturity, reason = 'NOT_MATURE', 'NO_STRICTLY_POST_ANCHOR_QUOTES'
    elif len(future) < spec['minimum_quote_points']:
        maturity, reason = 'NOT_MATURE', 'INSUFFICIENT_POST_ANCHOR_QUOTE_POINTS'
    elif max_gap is not None and max_gap > spec['max_interior_gap_ns']:
        maturity, reason = 'NOT_MATURE', 'INTERIOR_QUOTE_GAP_EXCEEDED'
    elif endpoint is None and capture_end < end_ns + spec['max_endpoint_lag_ns']:
        maturity, reason = 'NOT_MATURE', 'ENDPOINT_PENDING_OR_CAPTURE_TRUNCATED'
    elif endpoint is None:
        maturity, reason = 'NOT_MATURE', 'ENDPOINT_MISSING'
    elif int(endpoint['quote_received_at_ns']) > end_ns + spec['max_endpoint_lag_ns']:
        maturity, reason = 'NOT_MATURE', 'ENDPOINT_TOO_LATE'
    values: dict[str, float | None] = {
        'future_mid_mean': None,
        'future_spread_bps': None,
        'future_top_depth_notional': None,
        'signed_return_bps': None,
        'future_range_bps': None,
        'future_realized_volatility_bps': None,
        'directionality_efficiency': None,
    }
    endpoint_lag = None if endpoint is None else int(endpoint['quote_received_at_ns']) - end_ns
    if maturity == 'MATURE':
        mids = [float(item['quote_values']['mid']) for item in future]
        spreads = [float(item['quote_values']['spread_bps']) for item in future]
        depths = [float(item['quote_values']['top_depth_notional']) for item in future if 'top_depth_notional' in item['quote_values']]
        anchor_mid = float(anchor['quote_values']['mid'])
        endpoint_mid = float(endpoint['quote_values']['mid']) if endpoint is not None else None
        values['future_mid_mean'] = _mean(mids)
        values['future_spread_bps'] = _mean(spreads)
        values['future_top_depth_notional'] = _mean(depths)
        values['signed_return_bps'] = _return_bps(anchor_mid, endpoint_mid) if endpoint_mid is not None else None
        values['future_range_bps'] = _return_bps(min(mids), max(mids)) if mids else None
        if len(mids) >= 2:
            log_returns = [math.log(right / left) for left, right in zip(mids, mids[1:]) if left > 0 and right > 0]
            values['future_realized_volatility_bps'] = math.sqrt(sum(x * x for x in log_returns)) * 10_000.0 if log_returns else None
            span = max(mids) - min(mids)
            values['directionality_efficiency'] = abs(mids[-1] - mids[0]) / span if span > 0 else 0.0
    quality = {
        'anchor_received_at_ns': anchor_ns,
        'target_end_ns': end_ns,
        'capture_end_ns': capture_end,
        'post_anchor_quote_points': len(future),
        'max_interior_gap_ns': max_gap,
        'endpoint_received_at_ns': None if endpoint is None else int(endpoint['quote_received_at_ns']),
        'endpoint_lag_ns': endpoint_lag,
        'strict_interval': '(anchor, anchor+horizon]',
    }
    unsigned = {
        'schema': TARGET_SCHEMA,
        'analysis': 'strictly_post_anchor_mature_target',
        'target_id': spec['target_id'],
        'source_set': sources,
        'policy_sha256': normalized_policy['policy_sha256'],
        'target_interval': interval,
        'target_spec': spec,
        'maturity': maturity,
        'eligibility': 'ELIGIBLE' if maturity == 'MATURE' else 'INELIGIBLE',
        'ineligibility_reason': reason,
        'quality': quality,
        'values': values,
        'non_authority_claims': non_authority_claims(),
    }
    return _result(unsigned, 'target_sha256')


def validate_mature_target_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _validate_result_hash(value, 'target_sha256', 'mature_target')
    required = {
        'schema', 'analysis', 'target_id', 'source_set', 'policy_sha256', 'target_interval',
        'target_spec', 'maturity', 'eligibility', 'ineligibility_reason', 'quality', 'values',
        'non_authority_claims', 'target_sha256',
    }
    _exact_keys(raw, required, 'mature_target')
    if raw['schema'] != TARGET_SCHEMA or raw['analysis'] != 'strictly_post_anchor_mature_target':
        raise FeatureV2Error('mature_target schema/analysis is unsupported')
    _source_set(raw['source_set'], 'mature_target.source_set')
    _sha(raw['policy_sha256'], 'mature_target.policy_sha256')
    if validate_utc_interval(raw['target_interval'])['convention'] != OPEN_CLOSED:
        raise FeatureV2Error('mature_target interval must use OPEN_CLOSED')
    _validate_target_spec(raw['target_spec'])
    if raw['maturity'] not in {'MATURE', 'NOT_MATURE'} or raw['eligibility'] not in {'ELIGIBLE', 'INELIGIBLE'}:
        raise FeatureV2Error('mature_target status fields are invalid')
    if (raw['maturity'] == 'MATURE') != (raw['eligibility'] == 'ELIGIBLE'):
        raise FeatureV2Error('mature_target maturity and eligibility disagree')
    _claims(raw['non_authority_claims'])
    return raw


def feature_eligibility_v2(
    quote_provenance: Mapping[str, Any],
    *,
    capture_pair: Mapping[str, Any],
    source_set: Mapping[str, Any],
    policy: Mapping[str, Any],
    context_quote_provenance: Mapping[str, Any] | None = None,
    target: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    '''Fail closed unless replay binding, quote freshness, and optional target maturity agree.'''
    normalized_policy = validate_feature_policy_v2(policy)
    sources = _source_set(source_set)
    capture = _validate_capture_pair(capture_pair, sources)
    quote = validate_quote_provenance_v2(quote_provenance)
    _same_source(quote['source_set'], sources, 'quote_provenance')
    if quote['policy_sha256'] != normalized_policy['policy_sha256']:
        raise FeatureV2Error('quote_provenance policy_sha256 does not match')
    reasons: list[str] = []
    if normalized_policy['lifecycle'] != 'FROZEN_FOR_NEW_EVIDENCE':
        reasons.append('POLICY_INACTIVE')
    if quote['eligibility'] != 'ELIGIBLE':
        reasons.append('PRIMARY_' + str(quote['eligibility_reason']))
    context = None
    if context_quote_provenance is not None:
        context = validate_quote_provenance_v2(context_quote_provenance)
        _same_source(context['source_set'], sources, 'context_quote_provenance')
        if context['policy_sha256'] != normalized_policy['policy_sha256']:
            raise FeatureV2Error('context_quote_provenance policy_sha256 does not match')
    if normalized_policy['quote']['require_context_quote'] and (context is None or context['eligibility'] != 'ELIGIBLE'):
        reasons.append('CONTEXT_QUOTE_INELIGIBLE')
    normalized_target = None
    if target is not None:
        normalized_target = validate_mature_target_v2(target)
        _same_source(normalized_target['source_set'], sources, 'target')
        if normalized_target['policy_sha256'] != normalized_policy['policy_sha256']:
            raise FeatureV2Error('target policy_sha256 does not match')
        if normalized_target['eligibility'] != 'ELIGIBLE':
            reasons.append('TARGET_' + str(normalized_target['ineligibility_reason']))
    status = 'ELIGIBLE' if not reasons else 'INELIGIBLE'
    unsigned = {
        'schema': FEATURE_ELIGIBILITY_SCHEMA,
        'analysis': 'capture_bound_feature_and_target_eligibility',
        'source_set': sources,
        'capture_pair_sha256': capture['capture_pair_sha256'],
        'policy_sha256': normalized_policy['policy_sha256'],
        'quote_provenance_sha256': quote['quote_provenance_sha256'],
        'context_quote_provenance_sha256': None if context is None else context['quote_provenance_sha256'],
        'target_sha256': None if normalized_target is None else normalized_target['target_sha256'],
        'eligibility': status,
        'reasons': sorted(reasons),
        'non_authority_claims': non_authority_claims(),
    }
    return _result(unsigned, 'feature_eligibility_sha256')


def _load_event_sequence(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)) or not events:
        raise FeatureV2Error('events must be a nonempty sequence of event objects')
    output: list[dict[str, Any]] = []
    previous = -1
    for index, item in enumerate(events):
        row = dict(_mapping(item, f'events[{index}]'))
        received = _int(row.get('received_at_ns'), f'events[{index}].received_at_ns', minimum=0)
        if received < previous:
            raise FeatureV2Error('events must be in nondecreasing received_at_ns order')
        previous = received
        _text(row.get('symbol'), f'events[{index}].symbol')
        _text(row.get('event_type'), f'events[{index}].event_type')
        output.append(row)
    return output


def _latest_event(events: Sequence[Mapping[str, Any]], times: Sequence[int], at_ns: int) -> Mapping[str, Any] | None:
    position = bisect_right(times, at_ns) - 1
    return events[position] if position >= 0 else None


def _association_v2(rows: Sequence[Mapping[str, Any]], feature: str, target: str, minimum: int) -> dict[str, Any] | None:
    pairs: list[tuple[float, float]] = []
    for row in rows:
        left = row['features'].get(feature)
        right = row['target_values'].get(target)
        if left is None or right is None:
            continue
        if math.isfinite(float(left)) and math.isfinite(float(right)):
            pairs.append((float(left), float(right)))
    if len(pairs) < minimum:
        return None
    xs = [item[0] for item in pairs]
    ys = [item[1] for item in pairs]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in pairs)
    denominator = math.sqrt(sum((x - x_mean) ** 2 for x in xs) * sum((y - y_mean) ** 2 for y in ys))
    return {
        'feature': feature,
        'target': target,
        'observations': len(pairs),
        'pearson': None if denominator == 0 else max(-1.0, min(1.0, numerator / denominator)),
        'research_only': True,
    }


def scan_market_state_v2(
    events: Sequence[Mapping[str, Any]],
    *,
    source_set: Mapping[str, Any],
    capture_pair: Mapping[str, Any],
    policy: Mapping[str, Any],
    symbol: str,
    context_symbol: str,
) -> dict[str, Any]:
    '''Run the prospective quote-provenance/mature-target market-state scan offline.

    Trade events can provide flow references but never enter the quote series or
    quote-update count. Existing market_state_scan outputs are not read or changed.
    '''
    normalized_policy = validate_feature_policy_v2(policy)
    if normalized_policy['lifecycle'] != 'FROZEN_FOR_NEW_EVIDENCE':
        raise FeatureV2Error('scan requires a caller-declared FROZEN_FOR_NEW_EVIDENCE policy')
    sources = _source_set(source_set)
    capture = _validate_capture_pair(capture_pair, sources)
    primary_symbol = _text(symbol, 'symbol')
    btc_symbol = _text(context_symbol, 'context_symbol')
    rows = _load_event_sequence(events)
    if _utc_to_ns(normalized_policy['evidence_start_utc'], 'policy.evidence_start_utc') > int(rows[0]['received_at_ns']):
        raise FeatureV2Error('raw events begin before the policy evidence_start_utc')
    capture_start = _utc_to_ns(capture['capture_start_utc'], 'capture_pair.capture_start_utc')
    capture_end = _utc_to_ns(capture['capture_end_utc'], 'capture_pair.capture_end_utc')
    if int(rows[0]['received_at_ns']) < capture_start or int(rows[-1]['received_at_ns']) > capture_end:
        raise FeatureV2Error('raw events fall outside the capture_pair interval')
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_symbol[str(row['symbol'])].append(row)
    primary_rows = by_symbol.get(primary_symbol, [])
    context_rows = by_symbol.get(btc_symbol, [])
    if not primary_rows or not context_rows:
        raise FeatureV2Error('both primary and context symbols require raw event rows')
    primary_quote_events = [row for row in primary_rows if row['event_type'] in {'snapshot', 'depth'}]
    context_quote_events = [row for row in context_rows if row['event_type'] in {'snapshot', 'depth'}]
    primary_quote_times = [int(row['received_at_ns']) for row in primary_quote_events]
    context_quote_times = [int(row['received_at_ns']) for row in context_quote_events]
    primary_trade_events = [row for row in primary_rows if row['event_type'] == 'trade']
    primary_trade_times = [int(row['received_at_ns']) for row in primary_trade_events]
    interval = normalized_policy['scan']['analysis_interval']
    start_ns = _utc_to_ns(interval['start_utc'], 'policy.scan.analysis_interval.start_utc')
    end_ns = _utc_to_ns(interval['end_utc'], 'policy.scan.analysis_interval.end_utc')
    cadence = normalized_policy['scan']['sample_cadence_ns']
    anchors = list(range(start_ns, end_ns, cadence))
    if not anchors:
        raise FeatureV2Error('caller-declared scan interval contains no sample anchors')
    primary_target_points = [
        build_quote_provenance_v2(row, feature_received_at_ns=int(row['received_at_ns']), source_set=sources, policy=normalized_policy)
        for row in primary_quote_events
    ]
    raw_counts = Counter(str(row['event_type']) for row in rows)
    trade_echoes = sum(
        1 for row in primary_trade_events
        if _quote_values(row)[0] is not None
    )
    observations: list[dict[str, Any]] = []
    coverage_observations: list[dict[str, Any]] = []
    target_quality_counts: Counter[str] = Counter()
    for anchor_ns in anchors:
        primary_event = _latest_event(primary_quote_events, primary_quote_times, anchor_ns)
        context_event = _latest_event(context_quote_events, context_quote_times, anchor_ns)
        trade_event = _latest_event(primary_trade_events, primary_trade_times, anchor_ns)
        quote = build_quote_provenance_v2(
            primary_event, feature_received_at_ns=anchor_ns, source_set=sources, policy=normalized_policy, role='primary'
        )
        context_quote = build_quote_provenance_v2(
            context_event, feature_received_at_ns=anchor_ns, source_set=sources, policy=normalized_policy, role='context'
        )
        base_eligibility = feature_eligibility_v2(
            quote, capture_pair=capture, source_set=sources, policy=normalized_policy,
            context_quote_provenance=context_quote,
        )
        values = quote['quote_values'] if quote['eligibility'] == 'ELIGIBLE' else None
        features: dict[str, float | None] = {
            'spread_bps': None if values is None else values.get('spread_bps'),
            'top_depth_notional': None if values is None else values.get('top_depth_notional'),
            'book_imbalance_10': None if values is None else values.get('book_imbalance_10'),
            'microprice_edge_spread_units': None if values is None else values.get('microprice_edge_spread_units'),
            'depth_flow_imbalance': None if values is None else values.get('depth_flow_imbalance'),
            'btc_return_lookback_bps': None,
        }
        past_context = _latest_event(context_quote_events, context_quote_times, anchor_ns - normalized_policy['scan']['context_lookback_ns'])
        if context_quote['eligibility'] == 'ELIGIBLE' and past_context is not None:
            past_values, _ = _quote_values(past_context)
            if past_values is not None and context_quote['quote_values'] is not None:
                features['btc_return_lookback_bps'] = _return_bps(float(past_values['mid']), float(context_quote['quote_values']['mid']))
        if trade_event is not None:
            buy = _number_or_none(trade_event.get('rolling_buy_volume'))
            sell = _number_or_none(trade_event.get('rolling_sell_volume'))
            if buy is not None and sell is not None and buy + sell > 0:
                features['flow_ratio_10s'] = (buy - sell) / (buy + sell)
            else:
                features['flow_ratio_10s'] = None
        else:
            features['flow_ratio_10s'] = None
        targets: dict[str, dict[str, Any]] = {}
        target_values: dict[str, float | None] = {}
        target_eligibility: dict[str, str] = {}
        for spec in normalized_policy['targets']:
            if quote['eligibility'] == 'ELIGIBLE':
                target = build_mature_target_v2(
                    quote, primary_target_points, target_spec=spec, capture_end_ns=capture_end,
                    source_set=sources, policy=normalized_policy,
                )
            else:
                target = None
            if target is None:
                target_eligibility[spec['target_id']] = 'INELIGIBLE'
                target_quality_counts['PRIMARY_QUOTE_INELIGIBLE'] += 1
                coverage_observations.append({
                    'observation_id': f'{anchor_ns}:{spec["target_id"]}',
                    'observation': missing_value('primary_quote_ineligible'),
                })
                continue
            combined = feature_eligibility_v2(
                quote, capture_pair=capture, source_set=sources, policy=normalized_policy,
                context_quote_provenance=context_quote, target=target,
            )
            targets[spec['target_id']] = target
            target_eligibility[spec['target_id']] = combined['eligibility']
            target_quality_counts[str(target['maturity']) if combined['eligibility'] == 'ELIGIBLE' else str(target['ineligibility_reason'] or 'FEATURE_INELIGIBLE')] += 1
            for field, value in target['values'].items():
                target_values[f'{spec["target_id"]}.{field}'] = value if combined['eligibility'] == 'ELIGIBLE' else None
            coverage_observations.append({
                'observation_id': f'{anchor_ns}:{spec["target_id"]}',
                'observation': observed_value(1) if combined['eligibility'] == 'ELIGIBLE' else missing_value(
                    ';'.join(combined['reasons']) or 'target_ineligible'
                ),
            })
        observations.append({
            'anchor_received_at_ns': anchor_ns,
            'anchor_received_at_utc': _ns_to_utc(anchor_ns),
            'quote_provenance': quote,
            'context_quote_provenance': context_quote,
            'feature_eligibility': base_eligibility,
            'trade_reference': None if trade_event is None else {
                'event_type': 'trade', 'trade_received_at_ns': int(trade_event['received_at_ns']),
                'has_trade_carried_bbo': _quote_values(trade_event)[0] is not None,
            },
            'features': features,
            'targets': targets,
            'target_eligibility': target_eligibility,
            'target_values': target_values,
        })
    try:
        coverage = build_manifest_result  # retain import use for static checkers
        from orderflow_edge_lab.contracts_v2 import build_coverage_result
        grid_coverage = build_coverage_result('causal_feature_target_anchor_grid_v2', interval, coverage_observations)
        manifest = build_manifest_result(
            'causal_market_state_scan_v2', sources,
            'COMPLETE' if grid_coverage['status'] == 'COMPLETE' else 'INCOMPLETE',
            coverage=grid_coverage, policy_sha256=normalized_policy['policy_sha256'],
            attributes={
                'capture_pair_sha256': capture['capture_pair_sha256'],
                'quote_series_event_types': normalized_policy['quote']['accepted_event_types'],
                'trade_echoes_excluded_from_quote_series': trade_echoes,
            },
        )
    except ContractValidationError as exc:
        raise FeatureV2Error(str(exc)) from exc
    association_rows = [
        row for row in observations
        if row['feature_eligibility']['eligibility'] == 'ELIGIBLE'
    ]
    feature_names = sorted({name for row in observations for name in row['features']})
    target_names = sorted({name for row in observations for name in row['target_values']})
    associations = [
        item for feature in feature_names for target_name in target_names
        if (item := _association_v2(association_rows, feature, target_name, normalized_policy['scan']['minimum_association_observations'])) is not None
    ]
    accepted_primary_quotes = sum(item['eligibility'] == 'ELIGIBLE' for item in primary_target_points)
    unsigned = {
        'schema': SCAN_SCHEMA,
        'analysis': 'quote_provenance_and_mature_target_market_state_scan',
        'source_set': sources,
        'capture_pair_sha256': capture['capture_pair_sha256'],
        'policy_sha256': normalized_policy['policy_sha256'],
        'symbol': primary_symbol,
        'context_symbol': btc_symbol,
        'manifest': manifest,
        'quote_series': {
            'source_event_types_only': normalized_policy['quote']['accepted_event_types'],
            'raw_quote_candidate_count': len(primary_quote_events),
            'accepted_quote_count': accepted_primary_quotes,
            'trade_event_count': len(primary_trade_events),
            'trade_carried_bbo_excluded_count': trade_echoes,
            'quote_update_intensity_count': accepted_primary_quotes,
        },
        'raw_event_counts': dict(sorted(raw_counts.items())),
        'target_quality_counts': dict(sorted(target_quality_counts.items())),
        'observations': observations,
        'associations': associations,
        'claims': {
            'market_state_discovery_is_pnl_free': True,
            'trade_echoes_are_quote_observations': False,
            'automatic_feature_admission': False,
            'promotion_authorized': False,
        },
        'non_authority_claims': non_authority_claims(),
    }
    return _result(unsigned, 'scan_sha256')


def validate_scan_market_state_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _validate_result_hash(value, 'scan_sha256', 'scan')
    required = {
        'schema', 'analysis', 'source_set', 'capture_pair_sha256', 'policy_sha256', 'symbol', 'context_symbol',
        'manifest', 'quote_series', 'raw_event_counts', 'target_quality_counts', 'observations', 'associations',
        'claims', 'non_authority_claims', 'scan_sha256',
    }
    _exact_keys(raw, required, 'scan')
    if raw['schema'] != SCAN_SCHEMA or raw['analysis'] != 'quote_provenance_and_mature_target_market_state_scan':
        raise FeatureV2Error('scan schema/analysis is unsupported')
    _source_set(raw['source_set'], 'scan.source_set')
    _sha(raw['capture_pair_sha256'], 'scan.capture_pair_sha256')
    _sha(raw['policy_sha256'], 'scan.policy_sha256')
    try:
        validate_manifest_result(raw['manifest'])
    except ContractValidationError as exc:
        raise FeatureV2Error(str(exc)) from exc
    _claims(raw['non_authority_claims'])
    if raw['claims'] != {
        'market_state_discovery_is_pnl_free': True,
        'trade_echoes_are_quote_observations': False,
        'automatic_feature_admission': False,
        'promotion_authorized': False,
    }:
        raise FeatureV2Error('scan claims are invalid')
    return raw


def build_orthogonality_policy_v2(declaration: Mapping[str, Any]) -> dict[str, Any]:
    '''Build a target-specific, caller-declared baseline/admission policy.'''
    raw = _mapping(declaration, 'orthogonality policy declaration')
    _exact_keys(raw, {
        'policy_id', 'frozen_at_utc', 'evidence_start_utc', 'lifecycle', 'freeze_evidence_sha256',
        'target_baselines', 'candidate_admission_order', 'redundancy_threshold', 'resamples', 'confidence', 'seed',
    }, 'orthogonality policy declaration')
    frozen, start, lifecycle, freeze_hash = _validate_lifecycle(
        raw['frozen_at_utc'], raw['evidence_start_utc'], raw['lifecycle'], raw['freeze_evidence_sha256'], 'orthogonality policy'
    )
    baseline_raw = _mapping(raw['target_baselines'], 'orthogonality policy.target_baselines')
    order_raw = _mapping(raw['candidate_admission_order'], 'orthogonality policy.candidate_admission_order')
    if set(baseline_raw) != set(order_raw) or not baseline_raw:
        raise FeatureV2Error('orthogonality target_baselines and candidate_admission_order need identical nonempty targets')
    baselines: dict[str, list[str]] = {}
    orders: dict[str, list[str]] = {}
    for target in sorted(baseline_raw):
        target_id = _text(target, 'orthogonality target')
        baseline_values = baseline_raw[target]
        candidate_values = order_raw[target]
        if not isinstance(baseline_values, list) or not baseline_values:
            raise FeatureV2Error('each orthogonality baseline must be a nonempty list')
        if not isinstance(candidate_values, list) or not candidate_values:
            raise FeatureV2Error('each orthogonality candidate order must be a nonempty list')
        base = [_text(item, 'orthogonality baseline feature') for item in baseline_values]
        candidates = [_text(item, 'orthogonality candidate feature') for item in candidate_values]
        if len(base) != len(set(base)) or len(candidates) != len(set(candidates)):
            raise FeatureV2Error('orthogonality baseline/candidate names must be unique')
        if set(base).intersection(candidates):
            raise FeatureV2Error('candidate cannot also be a baseline feature')
        baselines[target_id] = base
        orders[target_id] = candidates
    threshold = _finite(raw['redundancy_threshold'], 'orthogonality policy.redundancy_threshold')
    if not 0 < threshold <= 1:
        raise FeatureV2Error('orthogonality policy.redundancy_threshold must be in (0, 1]')
    confidence = _finite(raw['confidence'], 'orthogonality policy.confidence')
    if not 0 < confidence < 1:
        raise FeatureV2Error('orthogonality policy.confidence must be in (0, 1)')
    unsigned = {
        'schema': ORTHOGONALITY_POLICY_SCHEMA,
        'analysis': 'caller_declared_full_baseline_admission_policy',
        'policy_id': _text(raw['policy_id'], 'orthogonality policy.policy_id'),
        'frozen_at_utc': frozen,
        'evidence_start_utc': start,
        'lifecycle': lifecycle,
        'freeze_evidence_sha256': freeze_hash,
        'freeze_verification': 'CALLER_DECLARED_LOCAL_IDENTITY_ONLY',
        'target_baselines': baselines,
        'candidate_admission_order': orders,
        'redundancy_threshold': threshold,
        'resamples': _int(raw['resamples'], 'orthogonality policy.resamples', minimum=100),
        'confidence': confidence,
        'seed': _int(raw['seed'], 'orthogonality policy.seed', minimum=0),
        'non_authority_claims': non_authority_claims(),
    }
    return _result(unsigned, 'policy_sha256')


def validate_orthogonality_policy_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _validate_result_hash(value, 'policy_sha256', 'orthogonality policy')
    required = {
        'schema', 'analysis', 'policy_id', 'frozen_at_utc', 'evidence_start_utc', 'lifecycle',
        'freeze_evidence_sha256', 'freeze_verification', 'target_baselines', 'candidate_admission_order',
        'redundancy_threshold', 'resamples', 'confidence', 'seed', 'non_authority_claims', 'policy_sha256',
    }
    _exact_keys(raw, required, 'orthogonality policy')
    if raw['schema'] != ORTHOGONALITY_POLICY_SCHEMA or raw['analysis'] != 'caller_declared_full_baseline_admission_policy':
        raise FeatureV2Error('orthogonality policy schema/analysis is unsupported')
    if raw['freeze_verification'] != 'CALLER_DECLARED_LOCAL_IDENTITY_ONLY':
        raise FeatureV2Error('orthogonality policy may not claim external freeze verification')
    rebuilt = build_orthogonality_policy_v2({
        'policy_id': raw['policy_id'], 'frozen_at_utc': raw['frozen_at_utc'], 'evidence_start_utc': raw['evidence_start_utc'],
        'lifecycle': raw['lifecycle'], 'freeze_evidence_sha256': raw['freeze_evidence_sha256'],
        'target_baselines': raw['target_baselines'], 'candidate_admission_order': raw['candidate_admission_order'],
        'redundancy_threshold': raw['redundancy_threshold'], 'resamples': raw['resamples'],
        'confidence': raw['confidence'], 'seed': raw['seed'],
    })
    if rebuilt != raw:
        raise FeatureV2Error('orthogonality policy is not normalized canonical content')
    _claims(raw['non_authority_claims'])
    return raw


def _orthogonality_rows(
    rows: Sequence[Mapping[str, Any]], target: str, baseline: Sequence[str], candidates: Sequence[str]
) -> list[dict[str, Any]]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or not rows:
        raise FeatureV2Error('evidence rows must be a nonempty sequence')
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    required = {'observation_id', 'batch_id', 'dependence_cluster', 'feature_eligibility', 'target_maturity', 'features', 'targets'}
    names = [*baseline, *candidates]
    for position, value in enumerate(rows):
        row = _mapping(value, f'evidence_rows[{position}]')
        _exact_keys(row, required, f'evidence_rows[{position}]')
        observation_id = _text(row['observation_id'], f'evidence_rows[{position}].observation_id')
        if observation_id in seen:
            raise FeatureV2Error('evidence_rows observation_id values must be unique')
        seen.add(observation_id)
        if row['feature_eligibility'] != 'ELIGIBLE':
            raise FeatureV2Error('full-baseline evidence rejects feature-ineligible rows')
        maturity = _mapping(row['target_maturity'], f'evidence_rows[{position}].target_maturity')
        if maturity.get(target) != 'MATURE':
            raise FeatureV2Error('full-baseline evidence rejects target-ineligible rows')
        features = _mapping(row['features'], f'evidence_rows[{position}].features')
        targets = _mapping(row['targets'], f'evidence_rows[{position}].targets')
        flat = {
            'observation_id': observation_id,
            'batch_id': _text(row['batch_id'], f'evidence_rows[{position}].batch_id'),
            'dependence_cluster': _text(row['dependence_cluster'], f'evidence_rows[{position}].dependence_cluster'),
            target: _finite(targets.get(target), f'evidence_rows[{position}].targets.{target}'),
        }
        for name in names:
            flat[name] = _finite(features.get(name), f'evidence_rows[{position}].features.{name}')
        out.append(flat)
    if len({row['dependence_cluster'] for row in out}) < 2:
        raise FeatureV2Error('full-baseline evidence requires at least two dependence clusters')
    return out


def _loo_incremental(rows: Sequence[Mapping[str, Any]], feature: str, baseline: Sequence[str], target: str, policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for cluster in sorted({str(row['dependence_cluster']) for row in rows}):
        subset = [row for row in rows if str(row['dependence_cluster']) != cluster]
        try:
            result = incremental_information(
                subset, feature=feature, baseline=list(baseline), target=target,
                cluster='dependence_cluster', resamples=int(policy['resamples']),
                confidence=float(policy['confidence']), seed=int(policy['seed']),
            )
            output.append({
                'omitted_dependence_cluster': cluster,
                'observations': len(subset),
                'delta_r2_rank': result['delta_r2_rank'],
                'partial_rank_ic': result['partial_rank_ic'],
                'bootstrap_status': result['delta_r2_rank_interval']['status'],
            })
        except OrthogonalityError as exc:
            output.append({
                'omitted_dependence_cluster': cluster,
                'observations': len(subset),
                'delta_r2_rank': None,
                'partial_rank_ic': None,
                'bootstrap_status': 'UNDEFINED_AFTER_OMISSION',
                'reason': str(exc),
            })
    return output


def build_full_baseline_orthogonality_v2(
    evidence_rows: Sequence[Mapping[str, Any]],
    *,
    target: str,
    source_set: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    '''Evaluate every admitted candidate against the complete frozen target baseline.'''
    normalized_policy = validate_orthogonality_policy_v2(policy)
    if normalized_policy['lifecycle'] != 'FROZEN_FOR_NEW_EVIDENCE':
        raise FeatureV2Error('orthogonality evaluation requires a caller-declared FROZEN_FOR_NEW_EVIDENCE policy')
    sources = _source_set(source_set)
    target_id = _text(target, 'target')
    if target_id not in normalized_policy['target_baselines']:
        raise FeatureV2Error('target has no caller-declared baseline/admission order')
    baseline = list(normalized_policy['target_baselines'][target_id])
    candidates = list(normalized_policy['candidate_admission_order'][target_id])
    rows = _orthogonality_rows(evidence_rows, target_id, baseline, candidates)
    reports: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            report = build_orthogonality_report(
                rows, feature=candidate, baseline=baseline, target=target_id,
                redundancy_threshold=float(normalized_policy['redundancy_threshold']),
                cluster='dependence_cluster', group_key='batch_id',
                resamples=int(normalized_policy['resamples']), confidence=float(normalized_policy['confidence']),
                seed=int(normalized_policy['seed']),
            )
        except OrthogonalityError as exc:
            raise FeatureV2Error(f'candidate {candidate} cannot be evaluated: {exc}') from exc
        reports.append({
            'candidate': candidate,
            'complete_baseline': baseline,
            'incremental_information': report['incremental_information'],
            'pairwise_redundancy_diagnostic': report['redundancy'],
            'leave_one_dependence_cluster_out': _loo_incremental(rows, candidate, baseline, target_id, normalized_policy),
            'human_review_required': True,
            'automatic_admission': False,
        })
    unsigned = {
        'schema': ORTHOGONALITY_SCHEMA,
        'analysis': 'full_baseline_dependence_aware_incremental_information',
        'source_set': sources,
        'policy_sha256': normalized_policy['policy_sha256'],
        'target': target_id,
        'complete_baseline': baseline,
        'candidate_admission_order': candidates,
        'evidence_table_sha256': canonical_json_sha256(rows),
        'observations': len(rows),
        'dependence_cluster_count': len({row['dependence_cluster'] for row in rows}),
        'candidate_reports': reports,
        'review_status': 'DESCRIPTIVE_HUMAN_REVIEW_REQUIRED',
        'claims': {
            'strategy_pnl_read': False,
            'pairwise_cluster_can_bypass_full_baseline': False,
            'automatic_feature_admission': False,
            'promotion_authorized': False,
        },
        'non_authority_claims': non_authority_claims(),
    }
    return _result(unsigned, 'orthogonality_sha256')


def build_btc_correlation_policy_v2(declaration: Mapping[str, Any]) -> dict[str, Any]:
    '''Build the caller-declared closed-bar/cadence and PnL-free panel policy.'''
    raw = _mapping(declaration, 'btc policy declaration')
    _exact_keys(raw, {
        'policy_id', 'frozen_at_utc', 'evidence_start_utc', 'lifecycle', 'freeze_evidence_sha256',
        'context_symbol', 'cadence_ns', 'min_samples', 'panel_size', 'high_positive_min',
        'low_absolute_max', 'high_target', 'low_target',
    }, 'btc policy declaration')
    frozen, start, lifecycle, freeze_hash = _validate_lifecycle(
        raw['frozen_at_utc'], raw['evidence_start_utc'], raw['lifecycle'], raw['freeze_evidence_sha256'], 'btc policy'
    )
    high = _finite(raw['high_positive_min'], 'btc policy.high_positive_min')
    low = _finite(raw['low_absolute_max'], 'btc policy.low_absolute_max')
    if not -1 <= high <= 1 or not 0 <= low <= 1:
        raise FeatureV2Error('btc correlation thresholds must be within correlation bounds')
    panel_size = _int(raw['panel_size'], 'btc policy.panel_size', minimum=1)
    high_target = _int(raw['high_target'], 'btc policy.high_target', minimum=0)
    low_target = _int(raw['low_target'], 'btc policy.low_target', minimum=0)
    if high_target + low_target > panel_size:
        raise FeatureV2Error('btc high/low targets exceed panel_size')
    unsigned = {
        'schema': BTC_POLICY_SCHEMA,
        'analysis': 'caller_declared_closed_bar_cadence_policy',
        'policy_id': _text(raw['policy_id'], 'btc policy.policy_id'),
        'frozen_at_utc': frozen,
        'evidence_start_utc': start,
        'lifecycle': lifecycle,
        'freeze_evidence_sha256': freeze_hash,
        'freeze_verification': 'CALLER_DECLARED_LOCAL_IDENTITY_ONLY',
        'context_symbol': _text(raw['context_symbol'], 'btc policy.context_symbol'),
        'cadence_ns': _int(raw['cadence_ns'], 'btc policy.cadence_ns', minimum=1),
        'min_samples': _int(raw['min_samples'], 'btc policy.min_samples', minimum=2),
        'panel_size': panel_size,
        'high_positive_min': high,
        'low_absolute_max': low,
        'high_target': high_target,
        'low_target': low_target,
        'non_authority_claims': non_authority_claims(),
    }
    return _result(unsigned, 'policy_sha256')


def validate_btc_correlation_policy_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _validate_result_hash(value, 'policy_sha256', 'btc policy')
    required = {
        'schema', 'analysis', 'policy_id', 'frozen_at_utc', 'evidence_start_utc', 'lifecycle',
        'freeze_evidence_sha256', 'freeze_verification', 'context_symbol', 'cadence_ns', 'min_samples',
        'panel_size', 'high_positive_min', 'low_absolute_max', 'high_target', 'low_target',
        'non_authority_claims', 'policy_sha256',
    }
    _exact_keys(raw, required, 'btc policy')
    if raw['schema'] != BTC_POLICY_SCHEMA or raw['analysis'] != 'caller_declared_closed_bar_cadence_policy':
        raise FeatureV2Error('btc policy schema/analysis is unsupported')
    if raw['freeze_verification'] != 'CALLER_DECLARED_LOCAL_IDENTITY_ONLY':
        raise FeatureV2Error('btc policy may not claim external freeze verification')
    rebuilt = build_btc_correlation_policy_v2({
        'policy_id': raw['policy_id'], 'frozen_at_utc': raw['frozen_at_utc'], 'evidence_start_utc': raw['evidence_start_utc'],
        'lifecycle': raw['lifecycle'], 'freeze_evidence_sha256': raw['freeze_evidence_sha256'],
        'context_symbol': raw['context_symbol'], 'cadence_ns': raw['cadence_ns'], 'min_samples': raw['min_samples'],
        'panel_size': raw['panel_size'], 'high_positive_min': raw['high_positive_min'],
        'low_absolute_max': raw['low_absolute_max'], 'high_target': raw['high_target'], 'low_target': raw['low_target'],
    })
    if rebuilt != raw:
        raise FeatureV2Error('btc policy is not normalized canonical content')
    _claims(raw['non_authority_claims'])
    return raw


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    lmean = sum(left) / len(left)
    rmean = sum(right) / len(right)
    denominator = math.sqrt(sum((item - lmean) ** 2 for item in left) * sum((item - rmean) ** 2 for item in right))
    if denominator == 0:
        return None
    return max(-1.0, min(1.0, sum((a - lmean) * (b - rmean) for a, b in zip(left, right)) / denominator))


def _validate_bar_series(rows: object, *, as_of_ns: int, cadence_ns: int, symbol: str) -> tuple[dict[int, float], dict[str, int], str | None]:
    if not isinstance(rows, list) or not rows:
        return {}, {'raw_bars': 0, 'valid_closed_bars': 0, 'dropped_unclosed': 0, 'dropped_invalid': 0, 'duplicate': 0, 'out_of_order': 0, 'cadence_gaps': 0}, 'NO_BARS'
    previous = -1
    seen: set[int] = set()
    valid: dict[int, float] = {}
    counts: Counter[str] = Counter()
    invalid_order = False
    for position, value in enumerate(rows):
        counts['raw_bars'] += 1
        row = _mapping(value, f'bars.{symbol}[{position}]')
        _exact_keys(row, {'open_time_ns', 'close', 'closed'}, f'bars.{symbol}[{position}]')
        stamp = _int(row['open_time_ns'], f'bars.{symbol}[{position}].open_time_ns', minimum=0)
        if stamp in seen:
            counts['duplicate'] += 1
            invalid_order = True
            continue
        seen.add(stamp)
        if stamp <= previous:
            counts['out_of_order'] += 1
            invalid_order = True
        previous = stamp
        close = _number_or_none(row['close'])
        if close is None or close <= 0:
            counts['dropped_invalid'] += 1
            continue
        if row['closed'] is not True or stamp + cadence_ns > as_of_ns:
            counts['dropped_unclosed'] += 1
            continue
        valid[stamp] = close
    ordered = sorted(valid)
    counts['valid_closed_bars'] = len(ordered)
    counts['cadence_gaps'] = sum((right - left) != cadence_ns for left, right in zip(ordered, ordered[1:]))
    normalized = {key: valid[key] for key in ordered}
    for key in ('raw_bars', 'valid_closed_bars', 'dropped_unclosed', 'dropped_invalid', 'duplicate', 'out_of_order', 'cadence_gaps'):
        counts.setdefault(key, 0)
    return normalized, dict(counts), 'INVALID_BAR_ORDER_OR_DUPLICATE' if invalid_order else None


def _consecutive_returns(left: Mapping[int, float], right: Mapping[int, float], cadence_ns: int) -> tuple[list[float], list[float], int]:
    common = sorted(set(left).intersection(right))
    out_left: list[float] = []
    out_right: list[float] = []
    dropped = 0
    for previous, current in zip(common, common[1:]):
        if current - previous != cadence_ns:
            dropped += 1
            continue
        left_return = left[current] / left[previous] - 1.0
        right_return = right[current] / right[previous] - 1.0
        if math.isfinite(left_return) and math.isfinite(right_return):
            out_left.append(left_return)
            out_right.append(right_return)
    return out_left, out_right, dropped


def build_btc_correlation_input_v2(
    bars_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    source_set: Mapping[str, Any],
    policy: Mapping[str, Any],
    as_of_utc: str,
) -> dict[str, Any]:
    '''Validate immutable-as-of bars and form returns only on consecutive common closed bars.'''
    normalized_policy = validate_btc_correlation_policy_v2(policy)
    if normalized_policy['lifecycle'] != 'FROZEN_FOR_NEW_EVIDENCE':
        raise FeatureV2Error('btc input evaluation requires a caller-declared FROZEN_FOR_NEW_EVIDENCE policy')
    sources = _source_set(source_set)
    bars = _mapping(bars_by_symbol, 'bars_by_symbol')
    as_of = _format_utc(_utc(as_of_utc, 'as_of_utc'))
    as_of_ns = _utc_to_ns(as_of, 'as_of_utc')
    if as_of_ns < _utc_to_ns(normalized_policy['evidence_start_utc'], 'policy.evidence_start_utc'):
        raise FeatureV2Error('as_of_utc precedes the caller-declared evidence start')
    normalized: dict[str, dict[int, float]] = {}
    ledgers: dict[str, dict[str, Any]] = {}
    for symbol in sorted(bars):
        name = _text(symbol, 'bars_by_symbol symbol')
        series, counts, invalid = _validate_bar_series(
            bars[symbol], as_of_ns=as_of_ns, cadence_ns=int(normalized_policy['cadence_ns']), symbol=name
        )
        normalized[name] = series
        ledgers[name] = {**counts, 'status': 'INVALID' if invalid else 'VALID', 'reason': invalid}
    context = normalized_policy['context_symbol']
    if context not in normalized:
        raise FeatureV2Error('bars_by_symbol must include the caller-declared context_symbol')
    correlations: list[dict[str, Any]] = []
    for symbol in sorted(normalized):
        if symbol == context:
            continue
        left, right, dropped = _consecutive_returns(normalized[symbol], normalized[context], int(normalized_policy['cadence_ns']))
        invalid = ledgers[symbol]['status'] != 'VALID' or ledgers[context]['status'] != 'VALID'
        correlation = None if invalid else _pearson(left, right)
        status = 'INVALID' if invalid else ('ELIGIBLE' if correlation is not None and len(left) >= normalized_policy['min_samples'] else 'INSUFFICIENT')
        correlations.append({
            'symbol': symbol,
            'context_symbol': context,
            'correlation': correlation,
            'valid_consecutive_pair_count': len(left),
            'dropped_nonconsecutive_common_pair_count': dropped,
            'status': status,
        })
    unsigned = {
        'schema': BTC_INPUT_SCHEMA,
        'analysis': 'closed_bar_cadence_qualified_btc_correlation_input',
        'source_set': sources,
        'policy_sha256': normalized_policy['policy_sha256'],
        'as_of_utc': as_of,
        'as_of_ns': as_of_ns,
        'cadence_ns': normalized_policy['cadence_ns'],
        'input_payload_sha256': canonical_json_sha256(bars),
        'coverage_ledger': ledgers,
        'correlations': correlations,
        'claims': {
            'strategy_pnl_read': False,
            'open_or_gapped_bars_make_long_duration_returns': False,
            'automatic_panel_promotion': False,
        },
        'non_authority_claims': non_authority_claims(),
    }
    return _result(unsigned, 'btc_input_sha256')


def build_btc_correlation_panel_v2(
    correlation_input: Mapping[str, Any],
    *,
    candidates: Sequence[Mapping[str, Any]],
    source_set: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    '''Select only from caller-supplied PnL-free candidates using qualified v2 correlation evidence.'''
    normalized_policy = validate_btc_correlation_policy_v2(policy)
    input_raw = _validate_result_hash(correlation_input, 'btc_input_sha256', 'btc correlation input')
    if input_raw.get('schema') != BTC_INPUT_SCHEMA or input_raw.get('policy_sha256') != normalized_policy['policy_sha256']:
        raise FeatureV2Error('btc correlation input schema/policy does not match')
    sources = _source_set(source_set)
    _same_source(input_raw['source_set'], sources, 'btc correlation input')
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise FeatureV2Error('candidates must be a sequence')
    correlation = {str(item['symbol']): item for item in input_raw['correlations'] if isinstance(item, Mapping)}
    prepared: list[dict[str, Any]] = []
    for position, item in enumerate(candidates):
        row = _mapping(item, f'candidates[{position}]')
        _exact_keys(row, {'symbol', 'compatibility_rank', 'strategy_pnl_used'}, f'candidates[{position}]')
        if row['strategy_pnl_used'] is not False:
            raise FeatureV2Error('candidate compatibility screen must be PnL-free')
        symbol = _text(row['symbol'], f'candidates[{position}].symbol')
        evidence = correlation.get(symbol)
        if evidence is None:
            continue
        if evidence['status'] != 'ELIGIBLE':
            prepared.append({**dict(row), 'correlation_status': evidence['status'], 'eligible': False})
            continue
        corr = float(evidence['correlation'])
        bucket = 'high_positive' if corr >= normalized_policy['high_positive_min'] else (
            'low_absolute' if abs(corr) <= normalized_policy['low_absolute_max'] else 'other'
        )
        prepared.append({**dict(row), 'correlation_status': 'ELIGIBLE', 'correlation': corr, 'bucket': bucket, 'eligible': True})
    if len({item['symbol'] for item in prepared}) != len(prepared):
        raise FeatureV2Error('candidate symbols must be unique')
    eligible = [item for item in prepared if item['eligible']]
    order = lambda item: (int(item['compatibility_rank']), str(item['symbol']))
    high = sorted([item for item in eligible if item.get('bucket') == 'high_positive'], key=order)
    low = sorted([item for item in eligible if item.get('bucket') == 'low_absolute'], key=order)
    selected: list[dict[str, Any]] = []
    for rows, limit, reason in ((high, normalized_policy['high_target'], 'high_positive_target'), (low, normalized_policy['low_target'], 'low_absolute_target')):
        for item in rows[: int(limit)]:
            selected.append({**item, 'selection_reason': reason})
    remaining = [item for item in eligible if item['symbol'] not in {entry['symbol'] for entry in selected}]
    remaining.sort(key=lambda item: (abs(float(item['correlation'])), *order(item)))
    for item in remaining:
        if len(selected) >= normalized_policy['panel_size']:
            break
        selected.append({**item, 'selection_reason': 'pnl_free_correlation_diversity_fallback'})
    unsigned = {
        'schema': BTC_PANEL_SCHEMA,
        'analysis': 'pnl_free_btc_correlation_panel_selection',
        'source_set': sources,
        'policy_sha256': normalized_policy['policy_sha256'],
        'btc_input_sha256': input_raw['btc_input_sha256'],
        'selected': selected,
        'candidate_ledger': sorted(prepared, key=lambda item: str(item['symbol'])),
        'claims': {
            'strategy_pnl_read': False,
            'selection_is_descriptive_only': True,
            'promotion_authorized': False,
        },
        'non_authority_claims': non_authority_claims(),
    }
    return _result(unsigned, 'btc_panel_sha256')


def build_state_discovery_v2(
    scan: Mapping[str, Any],
    *,
    orthogonality: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    '''Build a canonical PnL-free discovery artifact from quality-qualified scan evidence.'''
    scan_raw = validate_scan_market_state_v2(scan)
    source_set = _source_set(scan_raw['source_set'], 'scan.source_set')
    orthogonality_hash = None
    candidate_review_order: list[dict[str, str]] = []
    if orthogonality is not None:
        orth = _validate_result_hash(orthogonality, 'orthogonality_sha256', 'orthogonality')
        if orth.get('schema') != ORTHOGONALITY_SCHEMA or orth.get('analysis') != 'full_baseline_dependence_aware_incremental_information':
            raise FeatureV2Error('orthogonality schema/analysis is unsupported')
        _same_source(orth['source_set'], source_set, 'orthogonality')
        orthogonality_hash = orth['orthogonality_sha256']
        candidate_review_order = [
            {'target': str(orth['target']), 'candidate': str(item['candidate'])}
            for item in orth['candidate_reports']
        ]
    state_order = sorted(set(scan_raw['observations'][0]['targets'])) if scan_raw['observations'] else []
    status = 'DESCRIPTIVE_REVIEW_ONLY' if scan_raw['manifest']['outcome'] == 'COMPLETE' else 'INCOMPLETE_QUALITY_COVERAGE'
    unsigned = {
        'schema': STATE_DISCOVERY_SCHEMA,
        'analysis': 'pnl_free_market_state_discovery',
        'source_set': source_set,
        'feature_policy_sha256': scan_raw['policy_sha256'],
        'scan_sha256': scan_raw['scan_sha256'],
        'orthogonality_sha256': orthogonality_hash,
        'status': status,
        'canonical_target_order': state_order,
        'canonical_candidate_review_order': candidate_review_order,
        'quality_manifest_sha256': scan_raw['manifest']['manifest_sha256'],
        'claims': {
            'strategy_pnl_read': False,
            'profit_factor_ranking_present': False,
            'state_hypothesis_eligible': False,
            'promotion_authorized': False,
        },
        'non_authority_claims': non_authority_claims(),
    }
    return _result(unsigned, 'state_discovery_sha256')


def _validate_lineage(
    value: Mapping[str, Any],
    *,
    discovery: Mapping[str, Any],
    feature_policy: Mapping[str, Any],
    pnl_source_set: Mapping[str, Any],
) -> dict[str, Any]:
    raw = _validate_result_hash(value, 'lineage_sha256', 'lineage')
    required = {
        'schema', 'analysis', 'state_hypothesis_id', 'state_hypothesis_sha256', 'state_discovery_sha256',
        'feature_policy_sha256', 'threshold_mapping_sha256', 'trial_accounting_id', 'trial_accounting_sha256',
        'outcome_maturity_sha256', 'frozen_effective_utc', 'pnl_source_set', 'freeze_verification',
        'non_authority_claims', 'lineage_sha256',
    }
    _exact_keys(raw, required, 'lineage')
    if raw['schema'] != LINEAGE_SCHEMA or raw['analysis'] != 'caller_declared_frozen_state_hypothesis_trial_lineage':
        raise FeatureV2Error('lineage schema/analysis is unsupported')
    if raw['freeze_verification'] != 'CALLER_DECLARED_LOCAL_IDENTITY_ONLY':
        raise FeatureV2Error('lineage may not claim externally verified freeze')
    _text(raw['state_hypothesis_id'], 'lineage.state_hypothesis_id')
    for key in ('state_hypothesis_sha256', 'state_discovery_sha256', 'feature_policy_sha256', 'threshold_mapping_sha256', 'trial_accounting_sha256', 'outcome_maturity_sha256'):
        _sha(raw[key], f'lineage.{key}')
    _text(raw['trial_accounting_id'], 'lineage.trial_accounting_id')
    frozen = _format_utc(_utc(raw['frozen_effective_utc'], 'lineage.frozen_effective_utc'))
    if raw['state_discovery_sha256'] != discovery['state_discovery_sha256']:
        raise FeatureV2Error('lineage does not bind this state discovery artifact')
    if raw['feature_policy_sha256'] != feature_policy['policy_sha256']:
        raise FeatureV2Error('lineage does not bind this feature policy')
    lineage_sources = _source_set(raw['pnl_source_set'], 'lineage.pnl_source_set')
    _same_source(lineage_sources, pnl_source_set, 'lineage')
    _claims(raw['non_authority_claims'])
    return {**raw, 'frozen_effective_utc': frozen, 'pnl_source_set': lineage_sources}


def _normalize_pnl_rows(rows: Sequence[Mapping[str, Any]], frozen_effective_utc: str) -> list[dict[str, Any]]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or not rows:
        raise FeatureV2Error('pnl_rows must be a nonempty sequence after lineage is supplied')
    frozen = _utc(frozen_effective_utc, 'lineage.frozen_effective_utc')
    output: list[dict[str, Any]] = []
    expected = {'condition_id', 'arm', 'observed_at_utc', 'net_bps', 'fee_bps_round_trip', 'gate_identity'}
    for index, value in enumerate(rows):
        row = _mapping(value, f'pnl_rows[{index}]')
        _exact_keys(row, expected, f'pnl_rows[{index}]')
        arm = _text(row['arm'], f'pnl_rows[{index}].arm')
        if arm not in {'baseline', 'conditioned'}:
            raise FeatureV2Error('pnl row arm must be baseline or conditioned')
        observed = _format_utc(_utc(row['observed_at_utc'], f'pnl_rows[{index}].observed_at_utc'))
        if _utc(observed, f'pnl_rows[{index}].observed_at_utc') < frozen:
            raise FeatureV2Error('pnl rows before frozen_effective_utc are prohibited')
        output.append({
            'condition_id': _text(row['condition_id'], f'pnl_rows[{index}].condition_id'),
            'arm': arm,
            'observed_at_utc': observed,
            'net_bps': _finite(row['net_bps'], f'pnl_rows[{index}].net_bps'),
            'fee_bps_round_trip': _finite(row['fee_bps_round_trip'], f'pnl_rows[{index}].fee_bps_round_trip'),
            'gate_identity': _text(row['gate_identity'], f'pnl_rows[{index}].gate_identity'),
        })
    return output


def build_pnl_stratification_v2(
    state_discovery: Mapping[str, Any],
    pnl_rows: Sequence[Mapping[str, Any]] | None,
    *,
    pnl_source_set: Mapping[str, Any],
    feature_policy: Mapping[str, Any],
    lineage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    '''Gate PnL summaries on frozen state/trial lineage; output is never a ranking or promotion verdict.'''
    discovery = _validate_result_hash(state_discovery, 'state_discovery_sha256', 'state_discovery')
    if discovery.get('schema') != STATE_DISCOVERY_SCHEMA or discovery.get('analysis') != 'pnl_free_market_state_discovery':
        raise FeatureV2Error('state_discovery schema/analysis is unsupported')
    policy = validate_feature_policy_v2(feature_policy)
    sources = _source_set(pnl_source_set)
    _source_set(discovery['source_set'], 'state_discovery.source_set')
    if discovery['feature_policy_sha256'] != policy['policy_sha256']:
        raise FeatureV2Error('state_discovery does not bind feature_policy')
    common = {
        'schema': PNL_REPORT_SCHEMA,
        'analysis': 'frozen_lineage_gated_descriptive_pnl_stratification',
        'state_discovery_sha256': discovery['state_discovery_sha256'],
        'feature_policy_sha256': policy['policy_sha256'],
        'pnl_source_set': sources,
        'canonical_state_order': discovery['canonical_target_order'],
        'claims': {
            'state_selection_uses_strategy_pnl': False,
            'profit_factor_ranking_present': False,
            'promotion_authorized': False,
            'live_order_transmission_supported': False,
        },
        'non_authority_claims': non_authority_claims(),
    }
    if lineage is None:
        return _result({
            **common,
            'status': 'WAITING_FOR_FROZEN_STATE_HYPOTHESIS',
            'lineage_sha256': None,
            'descriptive_rows': [],
            'waiting_reason': 'state_hypothesis_threshold_trial_and_outcome_maturity_lineage_required_before_pnl',
        }, 'pnl_report_sha256')
    if discovery.get('status') != 'DESCRIPTIVE_REVIEW_ONLY':
        raise FeatureV2Error('incomplete state discovery cannot unlock conditioned PnL output')
    if policy['lifecycle'] != 'FROZEN_FOR_NEW_EVIDENCE':
        raise FeatureV2Error('conditioned PnL requires a frozen feature policy')
    bound = _validate_lineage(lineage, discovery=discovery, feature_policy=policy, pnl_source_set=sources)
    normalized_rows = _normalize_pnl_rows(pnl_rows or [], bound['frozen_effective_utc'])
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in normalized_rows:
        grouped[(row['condition_id'], row['arm'])].append(row)
    condition_ids = sorted({key[0] for key in grouped})
    descriptive: list[dict[str, Any]] = []
    for condition_id in condition_ids:
        baseline = grouped.get((condition_id, 'baseline'), [])
        conditioned = grouped.get((condition_id, 'conditioned'), [])
        if not baseline or not conditioned:
            raise FeatureV2Error('every conditioned PnL condition requires baseline and conditioned arms')
        base_fee = {row['fee_bps_round_trip'] for row in baseline}
        conditioned_fee = {row['fee_bps_round_trip'] for row in conditioned}
        base_gates = {row['gate_identity'] for row in baseline}
        conditioned_gates = {row['gate_identity'] for row in conditioned}
        if base_fee != conditioned_fee or base_gates != conditioned_gates:
            raise FeatureV2Error('baseline and conditioned arms must use identical fee and gate identities')
        for arm, arm_rows in (('baseline', baseline), ('conditioned', conditioned)):
            descriptive.append({
                'condition_id': condition_id,
                'arm': arm,
                'observations': len(arm_rows),
                'net_bps_total': sum(row['net_bps'] for row in arm_rows),
                'net_bps_mean': sum(row['net_bps'] for row in arm_rows) / len(arm_rows),
                'fee_bps_round_trip': sorted(base_fee),
                'gate_identity': sorted(base_gates),
            })
    return _result({
        **common,
        'status': 'DESCRIPTIVE_NON_PROMOTING',
        'lineage_sha256': bound['lineage_sha256'],
        'descriptive_rows': descriptive,
        'waiting_reason': None,
    }, 'pnl_report_sha256')


def _load_json_file(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise FeatureV2Error(f'cannot read JSON from {path}') from exc


def _load_json_object(path: str) -> Mapping[str, Any]:
    return _mapping(_load_json_file(path), f'JSON at {path}')


def _load_jsonl_events(path: str) -> list[dict[str, Any]]:
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()
    except OSError as exc:
        raise FeatureV2Error(f'cannot read events from {path}') from exc
    out: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            out.append(dict(_mapping(json.loads(line), f'events line {line_number}')))
        except json.JSONDecodeError as exc:
            raise FeatureV2Error(f'events line {line_number} is not valid JSON') from exc
    return out


def _source_set_for_file(path: str, source_id: str) -> dict[str, Any]:
    try:
        return build_canonical_source_set([build_source_record(source_id, build_file_identity(path, logical_name=source_id))])
    except ContractValidationError as exc:
        raise FeatureV2Error(str(exc)) from exc


def _write_json(path: str, value: Mapping[str, Any]) -> None:
    try:
        Path(path).write_bytes(canonical_json_bytes(value) + b'\n')
    except (OSError, ContractValidationError) as exc:
        raise FeatureV2Error(f'cannot write JSON to {path}: {exc}') from exc


def main(argv: Sequence[str] | None = None) -> int:
    '''Run offline successor commands. No command opens a network connection.'''
    parser = argparse.ArgumentParser(description='Run opt-in offline causal-feature v2 contracts.')
    sub = parser.add_subparsers(dest='command', required=True)
    for name, help_text in (
        ('feature-policy', 'build a caller-declared feature policy'),
        ('orthogonality-policy', 'build a caller-declared full-baseline policy'),
        ('btc-policy', 'build a caller-declared closed-bar BTC policy'),
    ):
        item = sub.add_parser(name, help=help_text)
        item.add_argument('declaration')
        item.add_argument('--output', required=True)
    scan_parser = sub.add_parser('scan', help='run the quote-provenance/mature-target state scan')
    scan_parser.add_argument('events_jsonl')
    scan_parser.add_argument('--source-id', required=True)
    scan_parser.add_argument('--policy', required=True)
    scan_parser.add_argument('--capture-pair', required=True)
    scan_parser.add_argument('--symbol', required=True)
    scan_parser.add_argument('--context-symbol', required=True)
    scan_parser.add_argument('--output', required=True)
    ortho_parser = sub.add_parser('orthogonality', help='run full-baseline candidate diagnostics')
    ortho_parser.add_argument('evidence_json')
    ortho_parser.add_argument('--source-id', required=True)
    ortho_parser.add_argument('--policy', required=True)
    ortho_parser.add_argument('--target', required=True)
    ortho_parser.add_argument('--output', required=True)
    btc_parser = sub.add_parser('btc-input', help='validate closed-bar cadence and build BTC correlation input')
    btc_parser.add_argument('bars_json')
    btc_parser.add_argument('--source-id', required=True)
    btc_parser.add_argument('--policy', required=True)
    btc_parser.add_argument('--as-of-utc', required=True)
    btc_parser.add_argument('--output', required=True)
    discovery_parser = sub.add_parser('discovery', help='build PnL-free state discovery artifact')
    discovery_parser.add_argument('scan_json')
    discovery_parser.add_argument('--orthogonality')
    discovery_parser.add_argument('--output', required=True)
    pnl_parser = sub.add_parser('pnl-stratification', help='build frozen-lineage-gated descriptive PnL artifact')
    pnl_parser.add_argument('state_discovery_json')
    pnl_parser.add_argument('pnl_rows_json')
    pnl_parser.add_argument('--pnl-source-id', required=True)
    pnl_parser.add_argument('--feature-policy', required=True)
    pnl_parser.add_argument('--lineage')
    pnl_parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'feature-policy':
            result = build_feature_policy_v2(_load_json_object(args.declaration))
        elif args.command == 'orthogonality-policy':
            result = build_orthogonality_policy_v2(_load_json_object(args.declaration))
        elif args.command == 'btc-policy':
            result = build_btc_correlation_policy_v2(_load_json_object(args.declaration))
        elif args.command == 'scan':
            sources = _source_set_for_file(args.events_jsonl, args.source_id)
            result = scan_market_state_v2(
                _load_jsonl_events(args.events_jsonl), source_set=sources,
                capture_pair=_load_json_object(args.capture_pair), policy=_load_json_object(args.policy),
                symbol=args.symbol, context_symbol=args.context_symbol,
            )
        elif args.command == 'orthogonality':
            evidence = _load_json_file(args.evidence_json)
            if not isinstance(evidence, list):
                raise FeatureV2Error('orthogonality evidence JSON must be an array')
            result = build_full_baseline_orthogonality_v2(
                evidence, target=args.target, source_set=_source_set_for_file(args.evidence_json, args.source_id),
                policy=_load_json_object(args.policy),
            )
        elif args.command == 'btc-input':
            result = build_btc_correlation_input_v2(
                _load_json_object(args.bars_json), source_set=_source_set_for_file(args.bars_json, args.source_id),
                policy=_load_json_object(args.policy), as_of_utc=args.as_of_utc,
            )
        elif args.command == 'discovery':
            result = build_state_discovery_v2(
                _load_json_object(args.scan_json),
                orthogonality=None if args.orthogonality is None else _load_json_object(args.orthogonality),
            )
        elif args.command == 'pnl-stratification':
            rows = _load_json_file(args.pnl_rows_json)
            if not isinstance(rows, list):
                raise FeatureV2Error('pnl rows JSON must be an array')
            result = build_pnl_stratification_v2(
                _load_json_object(args.state_discovery_json), rows,
                pnl_source_set=_source_set_for_file(args.pnl_rows_json, args.pnl_source_id),
                feature_policy=_load_json_object(args.feature_policy),
                lineage=None if args.lineage is None else _load_json_object(args.lineage),
            )
        else:
            raise AssertionError('unreachable command')
        _write_json(args.output, result)
        return 0
    except (FeatureV2Error, OrthogonalityError, ContractValidationError, OSError, ValueError) as exc:
        print(json.dumps({'status': 'INVALID', 'error': str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
