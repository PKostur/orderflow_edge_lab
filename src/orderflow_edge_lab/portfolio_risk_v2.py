'''Offline, opt-in v2 portfolio-risk accounting and scenario models.'''

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import sys
from typing import Any, Mapping, Sequence

from orderflow_edge_lab.contracts_v2 import (
    ContractValidationError,
    canonical_json_bytes,
    canonical_json_sha256,
    non_authority_claims,
    source_sets_equal,
    validate_canonical_source_set,
)

SCHEMA = 'orderflow_edge_lab.portfolio_risk_v2'
POLICY_SCHEMA = 'orderflow_edge_lab.portfolio_risk_policy.v2'
TERMS_SCHEMA = 'orderflow_edge_lab.prop_firm_terms_snapshot.v2'
_POLICY_KINDS = {
    'STOP_LOSS_RECONCILIATION',
    'SELF_FINANCING_LEDGER',
    'PORTFOLIO_RISK_OVERLAY',
    'PROP_FIRM_SCENARIO',
}
_ACTIVATION_STATES = {'INERT_TEMPLATE', 'PROSPECTIVE_REPORT_ONLY'}
_SHA256_CHARS = frozenset('0123456789abcdef')


class PortfolioRiskV2Error(ContractValidationError):
    '''Raised when a successor risk input is malformed or unsafe to interpret.'''


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise PortfolioRiskV2Error(f'{field} must be an object with string keys')
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = ','.join(sorted(expected - actual))
        extra = ','.join(sorted(actual - expected))
        bits = []
        if missing:
            bits.append(f'missing={missing}')
        if extra:
            bits.append(f'extra={extra}')
        raise PortfolioRiskV2Error(f"{field} has unsupported shape ({'; '.join(bits)})")


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PortfolioRiskV2Error(f'{field} must be a nonempty string')
    return value.strip()


def _number(value: object, field: str, *, minimum: float | None = None, strictly_positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise PortfolioRiskV2Error(f'{field} must be a finite number')
    result = float(value)
    if strictly_positive and result <= 0:
        raise PortfolioRiskV2Error(f'{field} must be positive')
    if minimum is not None and result < minimum:
        raise PortfolioRiskV2Error(f'{field} must be at least {minimum}')
    return result


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise PortfolioRiskV2Error(f'{field} must be an integer >= {minimum}')
    return value


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in _SHA256_CHARS for ch in value.lower()):
        raise PortfolioRiskV2Error(f'{field} must be a 64-character hexadecimal SHA-256')
    return value.lower()


def _json_copy(value: object, field: str) -> Any:
    try:
        return json.loads(canonical_json_bytes(value).decode('utf-8'))
    except ContractValidationError as exc:
        raise PortfolioRiskV2Error(f'{field} must contain ordinary finite JSON') from exc


def _utc_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PortfolioRiskV2Error(f'{field} must be a timezone-aware ISO-8601 timestamp')
    try:
        result = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError as exc:
        raise PortfolioRiskV2Error(f'{field} must be ISO-8601') from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise PortfolioRiskV2Error(f'{field} must include a timezone')
    return result.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _finite_mapping(value: object, field: str, *, allow_empty: bool = False) -> dict[str, float]:
    raw = _mapping(value, field)
    if not raw and not allow_empty:
        raise PortfolioRiskV2Error(f'{field} must not be empty')
    return {key: _number(item, f'{field}.{key}') for key, item in sorted(raw.items())}


def build_risk_policy_v2(policy_id: str, policy_kind: str, limits: Mapping[str, Any], *, activation_state: str) -> dict[str, Any]:
    '''Hash caller-declared limits without selecting a limit or activating a policy.'''
    if policy_kind not in _POLICY_KINDS:
        raise PortfolioRiskV2Error('policy_kind is unsupported')
    if activation_state not in _ACTIVATION_STATES:
        raise PortfolioRiskV2Error('activation_state must be INERT_TEMPLATE or PROSPECTIVE_REPORT_ONLY')
    unsigned = {
        'schema': POLICY_SCHEMA,
        'policy_id': _string(policy_id, 'policy_id'),
        'policy_kind': policy_kind,
        'status': 'FROZEN',
        'activation_state': activation_state,
        'limits': _json_copy(dict(_mapping(limits, 'limits')), 'limits'),
    }
    return {**unsigned, 'policy_sha256': canonical_json_sha256(unsigned)}


def _validate_policy(value: Mapping[str, Any], kind: str) -> dict[str, Any]:
    raw = _mapping(value, 'policy')
    _exact_keys(raw, {'schema', 'policy_id', 'policy_kind', 'status', 'activation_state', 'limits', 'policy_sha256'}, 'policy')
    if raw.get('schema') != POLICY_SCHEMA or raw.get('policy_kind') != kind:
        raise PortfolioRiskV2Error('policy schema or policy_kind is unsupported for this model')
    if raw.get('status') != 'FROZEN' or raw.get('activation_state') not in _ACTIVATION_STATES:
        raise PortfolioRiskV2Error('policy must be caller-declared FROZEN and inactive/report-only')
    unsigned = {
        'schema': POLICY_SCHEMA,
        'policy_id': _string(raw.get('policy_id'), 'policy.policy_id'),
        'policy_kind': kind,
        'status': 'FROZEN',
        'activation_state': raw['activation_state'],
        'limits': _json_copy(dict(_mapping(raw.get('limits'), 'policy.limits')), 'policy.limits'),
    }
    if _sha256(raw.get('policy_sha256'), 'policy.policy_sha256') != canonical_json_sha256(unsigned):
        raise PortfolioRiskV2Error('policy_sha256 does not bind the declared policy bytes')
    return {**unsigned, 'policy_sha256': canonical_json_sha256(unsigned)}


def _limits(policy: Mapping[str, Any], expected: set[str], field: str) -> Mapping[str, Any]:
    values = _mapping(policy['limits'], field)
    _exact_keys(values, expected, field)
    return values


def _qualified_inputs(value: Mapping[str, Any], source_set: Mapping[str, Any], required: set[str]) -> dict[str, Any]:
    raw = _mapping(value, 'qualified_inputs')
    _exact_keys(raw, required, 'qualified_inputs')
    result: dict[str, Any] = {}
    for name in sorted(required):
        item = _mapping(raw[name], f'qualified_inputs.{name}')
        _exact_keys(item, {'stage', 'qualification', 'source_set', 'identity_sha256'}, f'qualified_inputs.{name}')
        if item.get('qualification') != 'QUALIFIED':
            raise PortfolioRiskV2Error(f'qualified_inputs.{name} must be QUALIFIED')
        item_set = validate_canonical_source_set(item.get('source_set'))
        if not source_sets_equal(source_set, item_set):
            raise PortfolioRiskV2Error(f'qualified_inputs.{name}.source_set must exactly match source_set')
        result[name] = {
            'stage': _string(item.get('stage'), f'qualified_inputs.{name}.stage'),
            'qualification': 'QUALIFIED',
            'source_set': item_set,
            'identity_sha256': _sha256(item.get('identity_sha256'), f'qualified_inputs.{name}.identity_sha256'),
        }
    return result


def _result(analysis: str, source_set: Mapping[str, Any], policy: Mapping[str, Any], qualified: Mapping[str, Any], analysis_status: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    unsigned = {
        'schema': SCHEMA,
        'analysis': analysis,
        'analysis_status': _string(analysis_status, 'analysis_status'),
        'source_set': validate_canonical_source_set(source_set),
        'policy_sha256': policy['policy_sha256'],
        'policy_activation_state': policy['activation_state'],
        'upstream_qualification': _json_copy(dict(qualified), 'qualified_inputs'),
        'payload': _json_copy(dict(payload), 'payload'),
        'activation_blockers': [
            'caller_declared_policy_is_inert_or_report_only',
            'external_durable_storage_not_verified',
            'provider_completeness_not_verified',
            'independent_engine_calibration_not_verified',
            'no_live_order_transmission_capability',
        ],
        'non_authority_claims': non_authority_claims(),
    }
    return {**unsigned, 'analysis_sha256': canonical_json_sha256(unsigned)}


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _stop_row(row: Mapping[str, Any], limits: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(row, 'execution')
    expected = {
        'trade_id', 'family', 'direction', 'quantity', 'entry_price', 'stop_price',
        'entry_fee_cash', 'planned_exit_fee_cash', 'actual_exit_fee_cash',
        'exit_price', 'exit_quote_age_ms', 'exit_status', 'exit_reason',
        'equity_before', 'depth_status', 'risk_bucket', 'volatility_bucket',
        'liquidity_bucket', 'exposure_multiple',
    }
    _exact_keys(raw, expected, 'execution')
    direction = _string(raw.get('direction'), 'execution.direction')
    if direction not in {'LONG', 'SHORT'}:
        raise PortfolioRiskV2Error('execution.direction must be LONG or SHORT')
    quantity = _number(raw.get('quantity'), 'execution.quantity', strictly_positive=True)
    entry = _number(raw.get('entry_price'), 'execution.entry_price', strictly_positive=True)
    stop = _number(raw.get('stop_price'), 'execution.stop_price', strictly_positive=True)
    if (direction == 'LONG' and stop > entry) or (direction == 'SHORT' and stop < entry):
        raise PortfolioRiskV2Error('execution.stop_price must be adverse to entry')
    equity_before = _number(raw.get('equity_before'), 'execution.equity_before', strictly_positive=True)
    entry_fee = _number(raw.get('entry_fee_cash'), 'execution.entry_fee_cash', minimum=0.0)
    planned_exit_fee = _number(raw.get('planned_exit_fee_cash'), 'execution.planned_exit_fee_cash', minimum=0.0)
    status = _string(raw.get('exit_status'), 'execution.exit_status')
    if status not in {'OBSERVED', 'MISSING'}:
        raise PortfolioRiskV2Error('execution.exit_status must be OBSERVED or MISSING')
    depth_status = _string(raw.get('depth_status'), 'execution.depth_status')
    if depth_status not in {'NOT_SUPPLIED', 'OBSERVED', 'MISSING'}:
        raise PortfolioRiskV2Error('execution.depth_status must state NOT_SUPPLIED, OBSERVED, or MISSING')
    signed = 1.0 if direction == 'LONG' else -1.0
    planned_loss_cash = quantity * abs(entry - stop) + entry_fee + planned_exit_fee
    planned_fraction = planned_loss_cash / equity_before
    base = {
        'trade_id': _string(raw.get('trade_id'), 'execution.trade_id'),
        'family': _string(raw.get('family'), 'execution.family'),
        'direction': direction,
        'quantity': quantity,
        'entry_price': entry,
        'stop_price': stop,
        'entry_fee_cash': entry_fee,
        'planned_exit_fee_cash': planned_exit_fee,
        'equity_before': equity_before,
        'planned_stop_loss_cash': planned_loss_cash,
        'planned_stop_risk_fraction': planned_fraction,
        'risk_bucket': _string(raw.get('risk_bucket'), 'execution.risk_bucket'),
        'volatility_bucket': _string(raw.get('volatility_bucket'), 'execution.volatility_bucket'),
        'liquidity_bucket': _string(raw.get('liquidity_bucket'), 'execution.liquidity_bucket'),
        'exposure_multiple': _number(raw.get('exposure_multiple'), 'execution.exposure_multiple', minimum=0.0),
        'exit_status': status,
        'exit_reason': _string(raw.get('exit_reason'), 'execution.exit_reason'),
        'depth_status': depth_status,
    }
    if status == 'MISSING':
        if any(raw.get(name) is not None for name in ('actual_exit_fee_cash', 'exit_price', 'exit_quote_age_ms')):
            raise PortfolioRiskV2Error('MISSING exit must not carry a fabricated price, age, or actual fee')
        conservative = max(planned_fraction, _number(limits['unresolved_loss_fraction'], 'limits.unresolved_loss_fraction', minimum=0.0))
        return {
            **base,
            'resolution': 'UNRESOLVED_MISSING_EXIT',
            'actual_executable_bbo_gap_bps': None,
            'realized_loss_cash': None,
            'realized_loss_fraction': None,
            'risk_overshoot_fraction': None,
            'realized_loss_exceeded_planned_risk': None,
            'conservative_tail_loss_fraction': conservative,
            'conservative_scenario': 'CALLER_DECLARED_UNRESOLVED_EXIT',
            'equity_after_stop_loss': None,
            'ruin_under_reported_loss': None,
        }
    exit_price = _number(raw.get('exit_price'), 'execution.exit_price', strictly_positive=True)
    exit_fee = _number(raw.get('actual_exit_fee_cash'), 'execution.actual_exit_fee_cash', minimum=0.0)
    age = _number(raw.get('exit_quote_age_ms'), 'execution.exit_quote_age_ms', minimum=0.0)
    raw_gap_bps = max(0.0, signed * (stop - exit_price) / stop * 10_000.0)
    stale = age > _number(limits['max_exit_quote_age_ms'], 'limits.max_exit_quote_age_ms', minimum=0.0)
    actual_loss_cash = max(0.0, quantity * signed * (entry - exit_price) + entry_fee + exit_fee)
    actual_fraction = actual_loss_cash / equity_before
    if stale:
        conservative = max(planned_fraction, _number(limits['unresolved_loss_fraction'], 'limits.unresolved_loss_fraction', minimum=0.0))
        return {
            **base,
            'exit_price': exit_price,
            'actual_exit_fee_cash': exit_fee,
            'exit_quote_age_ms': age,
            'resolution': 'UNRESOLVED_STALE_EXIT',
            'actual_executable_bbo_gap_bps': raw_gap_bps,
            'observed_exit_loss_cash_not_qualified': actual_loss_cash,
            'observed_exit_loss_fraction_not_qualified': actual_fraction,
            'realized_loss_cash': None,
            'realized_loss_fraction': None,
            'risk_overshoot_fraction': None,
            'realized_loss_exceeded_planned_risk': None,
            'conservative_tail_loss_fraction': conservative,
            'conservative_scenario': 'CALLER_DECLARED_STALE_EXIT',
            'equity_after_stop_loss': None,
            'ruin_under_reported_loss': None,
        }
    overshoot = max(0.0, actual_fraction - planned_fraction)
    equity_after = equity_before - actual_loss_cash
    return {
        **base,
        'exit_price': exit_price,
        'actual_exit_fee_cash': exit_fee,
        'exit_quote_age_ms': age,
        'resolution': 'RECONCILED_OBSERVED_EXIT',
        'actual_executable_bbo_gap_bps': raw_gap_bps,
        'realized_loss_cash': actual_loss_cash,
        'realized_loss_fraction': actual_fraction,
        'risk_overshoot_fraction': overshoot,
        'realized_loss_exceeded_planned_risk': actual_fraction > planned_fraction,
        'conservative_tail_loss_fraction': actual_fraction,
        'conservative_scenario': 'OBSERVED_EXECUTABLE_BBO',
        'equity_after_stop_loss': equity_after,
        'ruin_under_reported_loss': equity_after <= _number(limits['ruin_equity_floor'], 'limits.ruin_equity_floor', minimum=0.0),
    }


def build_stop_loss_reconciliation_v2(
    source_set: Mapping[str, Any],
    policy: Mapping[str, Any],
    executions: Sequence[Mapping[str, Any]],
    *,
    qualified_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    '''Reconcile planned sizing loss to observed executable BBO loss, never a stop fill assumption.'''
    sources = validate_canonical_source_set(source_set)
    declared_policy = _validate_policy(policy, 'STOP_LOSS_RECONCILIATION')
    limits = _limits(declared_policy, {'max_exit_quote_age_ms', 'ruin_equity_floor', 'unresolved_loss_fraction'}, 'stop policy limits')
    qualified = _qualified_inputs(qualified_inputs, sources, {'price', 'execution'})
    if not isinstance(executions, Sequence) or isinstance(executions, (str, bytes)) or not executions:
        raise PortfolioRiskV2Error('executions must be a nonempty array')
    rows = [_stop_row(item, limits) for item in executions]
    rows.sort(key=lambda item: item['trade_id'])
    ids = [item['trade_id'] for item in rows]
    if len(ids) != len(set(ids)):
        raise PortfolioRiskV2Error('execution.trade_id values must be unique')
    resolved = [row for row in rows if row['resolution'] == 'RECONCILED_OBSERVED_EXIT']
    tail = [float(row['conservative_tail_loss_fraction']) for row in rows]
    groups: list[dict[str, Any]] = []
    group_keys = {
        (row['family'], row['direction'], row['risk_bucket'], row['volatility_bucket'], row['liquidity_bucket'], row['exposure_multiple'])
        for row in rows
    }
    for family, direction, risk_bucket, volatility_bucket, liquidity_bucket, exposure_multiple in sorted(group_keys):
        subset = [
            row for row in rows
            if (row['family'], row['direction'], row['risk_bucket'], row['volatility_bucket'], row['liquidity_bucket'], row['exposure_multiple'])
            == (family, direction, risk_bucket, volatility_bucket, liquidity_bucket, exposure_multiple)
        ]
        groups.append({
            'family': family,
            'direction': direction,
            'risk_bucket': risk_bucket,
            'volatility_bucket': volatility_bucket,
            'liquidity_bucket': liquidity_bucket,
            'exposure_multiple': exposure_multiple,
            'trades': len(subset),
            'resolved_trades': sum(row['resolution'] == 'RECONCILED_OBSERVED_EXIT' for row in subset),
            'unresolved_trades': sum(row['resolution'] != 'RECONCILED_OBSERVED_EXIT' for row in subset),
            'tail_loss_fraction_sum': sum(float(row['conservative_tail_loss_fraction']) for row in subset),
            'breach_count': sum(bool(row['realized_loss_exceeded_planned_risk']) for row in subset if row['realized_loss_exceeded_planned_risk'] is not None),
        })
    payload = {
        'ledger': rows,
        'summary': {
            'trades': len(rows),
            'resolved_observed_exits': len(resolved),
            'unresolved_missing_exits': sum(row['resolution'] == 'UNRESOLVED_MISSING_EXIT' for row in rows),
            'unresolved_stale_exits': sum(row['resolution'] == 'UNRESOLVED_STALE_EXIT' for row in rows),
            'planned_loss_cash_sum': sum(float(row['planned_stop_loss_cash']) for row in rows),
            'resolved_realized_loss_cash_sum': sum(float(row['realized_loss_cash']) for row in resolved),
            'conservative_tail_loss_fraction_sum': sum(tail),
            'worst_conservative_tail_loss_fraction': max(tail),
            'p95_conservative_tail_loss_fraction': _percentile(tail, 0.95),
            'p99_conservative_tail_loss_fraction': _percentile(tail, 0.99),
            'realized_overshoot_count': sum(bool(row['realized_loss_exceeded_planned_risk']) for row in resolved),
            'ruin_count_on_resolved_stop_loss': sum(bool(row['ruin_under_reported_loss']) for row in resolved),
            'depth_not_supplied_count': sum(row['depth_status'] == 'NOT_SUPPLIED' for row in rows),
            'groups': groups,
            'ledger_tail_loss_reconciliation': sum(float(row['conservative_tail_loss_fraction']) for row in rows),
        },
        'labels': {
            'planned_stop_risk': 'technical_stop_plus_declared_planned_fees',
            'realized_loss': 'only_fresh_observed_executable_BBO_plus_actual_fees',
            'actual_executable_bbo_gap': 'gap_from_stop_to_observed_executable_BBO_not_a_fill_assumption',
        },
    }
    status = 'RECONCILED_WITH_UNRESOLVED_EXITS' if len(resolved) != len(rows) else 'RECONCILED_OBSERVED_EXITS'
    return _result('stop_loss_reconciliation_v2', sources, declared_policy, qualified, status, payload)


def _positions(value: object, field: str) -> dict[str, float]:
    return {key: number for key, number in _finite_mapping(value, field, allow_empty=True).items() if number != 0.0}


def _book(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    raw = _mapping(value, field)
    _exact_keys(raw, {'equity', 'cash', 'positions'}, field)
    equity = _number(raw.get('equity'), f'{field}.equity', strictly_positive=True)
    cash = _number(raw.get('cash'), f'{field}.cash')
    positions = _positions(raw.get('positions'), f'{field}.positions')
    residual = equity - (cash + sum(positions.values()))
    if abs(residual) > 1e-12:
        raise PortfolioRiskV2Error(f'{field} must satisfy equity = cash + signed positions')
    return {'equity': equity, 'cash': cash, 'positions': positions}


def _ledger_interval(item: Mapping[str, Any], previous: Mapping[str, Any], limits: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(item, 'interval')
    _exact_keys(raw, {'interval_id', 'target_weights', 'asset_returns', 'funding_cash'}, 'interval')
    target_weights = _finite_mapping(raw.get('target_weights'), 'interval.target_weights', allow_empty=True)
    if any(abs(weight) > 1.0 + 1e-12 for weight in target_weights.values()):
        raise PortfolioRiskV2Error('interval.target_weights may not exceed one unit per named target')
    active = {symbol for symbol, weight in target_weights.items() if weight != 0.0}
    asset_returns = _finite_mapping(raw.get('asset_returns'), 'interval.asset_returns', allow_empty=True)
    funding = _finite_mapping(raw.get('funding_cash'), 'interval.funding_cash', allow_empty=True)
    if set(asset_returns) != active or set(funding) != active:
        raise PortfolioRiskV2Error('asset_returns and funding_cash must explicitly cover exactly every nonzero target; observed zero is valid')
    equity_start = float(previous['equity'])
    pre_positions = dict(previous['positions'])
    target_positions = {symbol: equity_start * target_weights.get(symbol, 0.0) for symbol in sorted(set(pre_positions) | set(target_weights))}
    target_positions = {symbol: value for symbol, value in target_positions.items() if value != 0.0}
    trade_symbols = sorted(set(pre_positions) | set(target_positions))
    trades = {symbol: target_positions.get(symbol, 0.0) - pre_positions.get(symbol, 0.0) for symbol in trade_symbols}
    turnover = sum(abs(value) for value in trades.values())
    turnover_rate = _number(limits['turnover_cost_rate'], 'limits.turnover_cost_rate', minimum=0.0)
    trading_cost = turnover * turnover_rate
    cash_post_trade = equity_start - sum(target_positions.values())
    cash_end = cash_post_trade - trading_cost + sum(funding.values())
    price_pnl = sum(target_positions[symbol] * asset_returns[symbol] for symbol in active)
    positions_end = {symbol: target_positions[symbol] * (1.0 + asset_returns[symbol]) for symbol in active}
    positions_end = {symbol: value for symbol, value in positions_end.items() if value != 0.0}
    equity_end = cash_end + sum(positions_end.values())
    accounting_equity_end = equity_start + price_pnl + sum(funding.values()) - trading_cost
    residual = equity_end - accounting_equity_end
    tolerance = _number(limits['accounting_tolerance'], 'limits.accounting_tolerance', minimum=0.0)
    if abs(residual) > tolerance:
        raise PortfolioRiskV2Error('self-financing interval accounting residual exceeds caller-declared tolerance')
    pre_gross = sum(abs(value) for value in pre_positions.values()) / equity_start
    post_trade_gross = sum(abs(value) for value in target_positions.values()) / equity_start
    post_mark_gross = sum(abs(value) for value in positions_end.values()) / equity_end if equity_end > 0 else None
    cap = _number(limits['max_post_trade_gross'], 'limits.max_post_trade_gross', minimum=0.0)
    if post_trade_gross > cap + tolerance:
        raise PortfolioRiskV2Error('target weights violate the caller-declared post-trade gross cap')
    return {
        'interval_id': _string(raw.get('interval_id'), 'interval.interval_id'),
        'equity_start': equity_start,
        'cash_start': float(previous['cash']),
        'pre_trade_positions': pre_positions,
        'target_weights': {symbol: target_weights[symbol] for symbol in sorted(target_weights)},
        'target_positions': target_positions,
        'trades_from_marked_positions': {symbol: trades[symbol] for symbol in trade_symbols if trades[symbol] != 0.0},
        'turnover_notional': turnover,
        'turnover_cost_rate': turnover_rate,
        'trading_cost_cash': trading_cost,
        'cash_post_trade_before_flows': cash_post_trade,
        'price_pnl_cash': price_pnl,
        'funding_cash_by_symbol': funding,
        'funding_pnl_cash': sum(funding.values()),
        'post_mark_positions': positions_end,
        'cash_end': cash_end,
        'equity_end': equity_end,
        'equity_return_fraction': equity_end / equity_start - 1.0,
        'pre_trade_gross': pre_gross,
        'post_trade_gross': post_trade_gross,
        'post_mark_gross': post_mark_gross,
        'gross_cap': cap,
        'gross_cap_status': 'WITHIN_CAP',
        'equity_reconciliation_rhs': accounting_equity_end,
        'equity_reconciliation_residual': residual,
        'accounting_status': 'RECONCILED',
    }


def build_self_financing_ledger_v2(
    source_set: Mapping[str, Any],
    policy: Mapping[str, Any],
    initial_book: Mapping[str, Any],
    intervals: Sequence[Mapping[str, Any]],
    *,
    qualified_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    '''Build a cash-and-notional book whose equity change is price PnL plus funding minus costs.'''
    sources = validate_canonical_source_set(source_set)
    declared_policy = _validate_policy(policy, 'SELF_FINANCING_LEDGER')
    limits = _limits(declared_policy, {'max_post_trade_gross', 'turnover_cost_rate', 'accounting_tolerance'}, 'ledger policy limits')
    qualified = _qualified_inputs(qualified_inputs, sources, {'price', 'funding', 'execution'})
    if not isinstance(intervals, Sequence) or isinstance(intervals, (str, bytes)) or not intervals:
        raise PortfolioRiskV2Error('intervals must be a nonempty array')
    prior = _book(initial_book, 'initial_book')
    initial = _json_copy(prior, 'initial_book')
    rows = []
    ids: set[str] = set()
    for item in intervals:
        row = _ledger_interval(item, prior, limits)
        if row['interval_id'] in ids:
            raise PortfolioRiskV2Error('interval.interval_id values must be unique')
        ids.add(row['interval_id'])
        rows.append(row)
        prior = {'equity': row['equity_end'], 'cash': row['cash_end'], 'positions': row['post_mark_positions']}
    total_price = sum(float(row['price_pnl_cash']) for row in rows)
    total_funding = sum(float(row['funding_pnl_cash']) for row in rows)
    total_cost = sum(float(row['trading_cost_cash']) for row in rows)
    terminal = rows[-1]['equity_end']
    summary = {
        'intervals': len(rows),
        'initial_equity': initial['equity'],
        'terminal_equity': terminal,
        'price_pnl_cash_sum': total_price,
        'funding_pnl_cash_sum': total_funding,
        'trading_cost_cash_sum': total_cost,
        'equity_change_cash': terminal - initial['equity'],
        'equity_change_reconciliation_rhs': total_price + total_funding - total_cost,
        'equity_change_reconciliation_residual': terminal - initial['equity'] - total_price - total_funding + total_cost,
        'gross_cap_excursion_count': sum(row['gross_cap_status'] != 'WITHIN_CAP' for row in rows),
        'max_post_trade_gross': max(float(row['post_trade_gross']) for row in rows),
        'max_post_mark_gross': max((float(row['post_mark_gross']) for row in rows if row['post_mark_gross'] is not None), default=None),
    }
    tolerance = _number(limits['accounting_tolerance'], 'limits.accounting_tolerance', minimum=0.0)
    if abs(float(summary['equity_change_reconciliation_residual'])) > tolerance:
        raise PortfolioRiskV2Error('terminal self-financing reconciliation exceeds caller-declared tolerance')
    status = 'RECONCILED_WITH_GROSS_CAP_EXCURSION' if summary['gross_cap_excursion_count'] else 'RECONCILED'
    return _result('self_financing_ledger_v2', sources, declared_policy, qualified, status, {'initial_book': initial, 'ledger': rows, 'summary': summary})


def _mat_vec(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(row[j] * vector[j] for j in range(len(vector))) for row in matrix]


def _quad(matrix: list[list[float]], vector: list[float]) -> float:
    return sum(vector[i] * value for i, value in enumerate(_mat_vec(matrix, vector)))


def _jacobi_eigenvalues(matrix: list[list[float]]) -> list[float]:
    '''Small dependency-free symmetric eigensolver used only for diagnostics.'''
    n = len(matrix)
    work = [row[:] for row in matrix]
    for _ in range(max(1, 50 * n * n)):
        p, q, largest = 0, 0, 0.0
        for i in range(n):
            for j in range(i + 1, n):
                if abs(work[i][j]) > largest:
                    p, q, largest = i, j, abs(work[i][j])
        if largest <= 1e-14:
            break
        angle = 0.5 * math.atan2(2.0 * work[p][q], work[q][q] - work[p][p])
        c, s = math.cos(angle), math.sin(angle)
        app, aqq, apq = work[p][p], work[q][q], work[p][q]
        work[p][p] = c * c * app - 2.0 * s * c * apq + s * s * aqq
        work[q][q] = s * s * app + 2.0 * s * c * apq + c * c * aqq
        work[p][q] = work[q][p] = 0.0
        for k in range(n):
            if k in (p, q):
                continue
            aik, akq = work[k][p], work[k][q]
            work[k][p] = work[p][k] = c * aik - s * akq
            work[k][q] = work[q][k] = s * aik + c * akq
    return [work[i][i] for i in range(n)]


def _sample_covariance(rows: list[list[float]], shrinkage: float) -> list[list[float]]:
    count = len(rows)
    width = len(rows[0])
    means = [sum(row[i] for row in rows) / count for i in range(width)]
    sample = [[sum((row[i] - means[i]) * (row[j] - means[j]) for row in rows) / (count - 1) for j in range(width)] for i in range(width)]
    return [[(1.0 - shrinkage) * sample[i][j] + (shrinkage * sample[i][i] if i == j else 0.0) for j in range(width)] for i in range(width)]


def _effective_names(weights: list[float]) -> float:
    gross = sum(abs(value) for value in weights)
    if gross == 0.0:
        return 0.0
    return 1.0 / sum((abs(value) / gross) ** 2 for value in weights)


def _empty_overlay(raw_targets: Mapping[str, float], reason: str, excluded_future: int = 0) -> dict[str, Any]:
    return {
        'state': 'NO_NEW_RISK_CASH',
        'fallback_reason': reason,
        'raw_targets': dict(sorted(raw_targets.items())),
        'proposed_covariance_targets': {symbol: 0.0 for symbol in sorted(raw_targets)},
        'cash_residual_gross': 1.0,
        'covariance_diagnostics': {'status': 'INSUFFICIENT_OR_UNSAFE', 'future_observations_excluded': excluded_future},
        'constraint_bindings': ['NO_NEW_RISK_CASH_FALLBACK'],
        'risk_contributions': {},
        'stress_losses': {},
    }


def _overlay_policy_limits(policy: Mapping[str, Any]) -> Mapping[str, Any]:
    expected = {
        'covariance_min_observations', 'covariance_shrinkage', 'max_condition_number',
        'max_gross', 'max_abs_net', 'max_name_abs', 'max_abs_factor_exposure',
        'max_tag_gross', 'max_covariance_contribution', 'min_effective_n',
        'max_expected_shortfall', 'expected_shortfall_tail_fraction', 'max_stress_loss',
        'target_annual_vol', 'max_leverage', 'max_scaled_gross', 'max_tail_loss',
        'max_drawdown', 'max_volatility_jump', 'turnover_cost_rate', 'accounting_tolerance',
    }
    values = _limits(policy, expected, 'overlay policy limits')
    _integer(values['covariance_min_observations'], 'limits.covariance_min_observations', minimum=2)
    shrink = _number(values['covariance_shrinkage'], 'limits.covariance_shrinkage', minimum=0.0)
    if shrink > 1.0:
        raise PortfolioRiskV2Error('limits.covariance_shrinkage must be <= 1')
    for name in ('max_condition_number', 'max_gross', 'max_abs_net', 'max_name_abs', 'max_covariance_contribution', 'max_expected_shortfall', 'max_stress_loss', 'target_annual_vol', 'max_leverage', 'max_scaled_gross', 'max_tail_loss', 'max_drawdown', 'max_volatility_jump'):
        _number(values[name], f'limits.{name}', minimum=0.0)
    _number(values['max_condition_number'], 'limits.max_condition_number', strictly_positive=True)
    _number(values['max_gross'], 'limits.max_gross', minimum=0.0)
    _number(values['max_name_abs'], 'limits.max_name_abs', minimum=0.0)
    _number(values['min_effective_n'], 'limits.min_effective_n', strictly_positive=True)
    tail_fraction = _number(values['expected_shortfall_tail_fraction'], 'limits.expected_shortfall_tail_fraction', strictly_positive=True)
    if tail_fraction > 1.0:
        raise PortfolioRiskV2Error('limits.expected_shortfall_tail_fraction must be <= 1')
    _number(values['turnover_cost_rate'], 'limits.turnover_cost_rate', minimum=0.0)
    _number(values['accounting_tolerance'], 'limits.accounting_tolerance', minimum=0.0)
    return values


def _prior_covariance_overlay(raw_targets_value: Mapping[str, Any], risk_model_value: Mapping[str, Any], limits: Mapping[str, Any]) -> dict[str, Any]:
    raw_targets = _finite_mapping(raw_targets_value, 'raw_targets')
    raw_targets = {symbol: value for symbol, value in raw_targets.items() if value != 0.0}
    if not raw_targets:
        raise PortfolioRiskV2Error('raw_targets must contain at least one nonzero target')
    model = _mapping(risk_model_value, 'risk_model')
    _exact_keys(model, {'status', 'decision_time_utc', 'input_basis', 'returns', 'factor_loadings', 'asset_tags', 'stress_scenarios'}, 'risk_model')
    if model.get('status') != 'OBSERVED':
        return _empty_overlay(raw_targets, 'risk_model_status_not_observed')
    if model.get('input_basis') != 'CALLER_DECLARED_PNL_INDEPENDENT':
        return _empty_overlay(raw_targets, 'risk_panel_not_declared_pnl_independent')
    decision = _utc_timestamp(model.get('decision_time_utc'), 'risk_model.decision_time_utc')
    if not isinstance(model.get('returns'), Sequence) or isinstance(model.get('returns'), (str, bytes)):
        raise PortfolioRiskV2Error('risk_model.returns must be an array')
    symbols = sorted(raw_targets)
    prior_rows: list[tuple[datetime, list[float]]] = []
    future_rows = 0
    seen_times: set[datetime] = set()
    for index, item in enumerate(model['returns']):
        row = _mapping(item, f'risk_model.returns[{index}]')
        _exact_keys(row, {'timestamp_utc', 'returns'}, f'risk_model.returns[{index}]')
        moment = _utc_timestamp(row.get('timestamp_utc'), f'risk_model.returns[{index}].timestamp_utc')
        if moment in seen_times:
            raise PortfolioRiskV2Error('risk_model.returns timestamps must be unique')
        seen_times.add(moment)
        values = _finite_mapping(row.get('returns'), f'risk_model.returns[{index}].returns')
        if set(values) != set(symbols):
            return _empty_overlay(raw_targets, 'return_panel_has_missing_or_extra_assets', future_rows)
        if moment >= decision:
            future_rows += 1
            continue
        prior_rows.append((moment, [values[symbol] for symbol in symbols]))
    prior_rows.sort(key=lambda item: item[0])
    min_obs = _integer(limits['covariance_min_observations'], 'limits.covariance_min_observations', minimum=2)
    if len(prior_rows) < min_obs:
        return _empty_overlay(raw_targets, 'insufficient_strictly_prior_return_coverage', future_rows)
    factor_loadings_raw = _mapping(model.get('factor_loadings'), 'risk_model.factor_loadings')
    if set(factor_loadings_raw) != set(symbols):
        return _empty_overlay(raw_targets, 'factor_loading_coverage_incomplete', future_rows)
    factor_loadings = {symbol: _finite_mapping(factor_loadings_raw[symbol], f'risk_model.factor_loadings.{symbol}') for symbol in symbols}
    factors = sorted(set(next(iter(factor_loadings.values()))))
    if not factors or any(set(factor_loadings[symbol]) != set(factors) for symbol in symbols):
        return _empty_overlay(raw_targets, 'factor_loading_factor_set_incomplete', future_rows)
    tags_raw = _mapping(model.get('asset_tags'), 'risk_model.asset_tags')
    if set(tags_raw) != set(symbols):
        return _empty_overlay(raw_targets, 'asset_tag_coverage_incomplete', future_rows)
    tags: dict[str, list[str]] = {}
    for symbol in symbols:
        value = tags_raw[symbol]
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value or any(not isinstance(x, str) or not x.strip() for x in value):
            return _empty_overlay(raw_targets, 'asset_tags_missing_or_invalid', future_rows)
        tags[symbol] = sorted(set(item.strip() for item in value))
    max_factor = _finite_mapping(limits['max_abs_factor_exposure'], 'limits.max_abs_factor_exposure')
    all_tags = sorted({tag for values in tags.values() for tag in values})
    max_tag = _finite_mapping(limits['max_tag_gross'], 'limits.max_tag_gross')
    if set(max_factor) != set(factors) or set(max_tag) != set(all_tags):
        return _empty_overlay(raw_targets, 'policy_factor_or_tag_limits_do_not_cover_model', future_rows)
    stress_raw = _mapping(model.get('stress_scenarios'), 'risk_model.stress_scenarios')
    if not stress_raw:
        return _empty_overlay(raw_targets, 'missing_declared_stress_scenarios', future_rows)
    stresses = {name: _finite_mapping(values, f'risk_model.stress_scenarios.{name}') for name, values in sorted(stress_raw.items())}
    if any(set(values) != set(symbols) for values in stresses.values()):
        return _empty_overlay(raw_targets, 'stress_scenario_coverage_incomplete', future_rows)
    covariance = _sample_covariance([values for _, values in prior_rows], _number(limits['covariance_shrinkage'], 'limits.covariance_shrinkage', minimum=0.0))
    eigenvalues = _jacobi_eigenvalues(covariance)
    min_eigen, max_eigen = min(eigenvalues), max(eigenvalues)
    if min_eigen <= 1e-16 or max_eigen / min_eigen > _number(limits['max_condition_number'], 'limits.max_condition_number', strictly_positive=True):
        return _empty_overlay(raw_targets, 'covariance_ill_conditioned_or_nonpositive', future_rows)
    volatilities = [math.sqrt(covariance[i][i]) for i in range(len(symbols))]
    if any(value <= 0.0 or not math.isfinite(value) for value in volatilities):
        return _empty_overlay(raw_targets, 'covariance_has_nonpositive_variance', future_rows)
    raw_gross = sum(abs(value) for value in raw_targets.values())
    gross_budget = min(raw_gross, _number(limits['max_gross'], 'limits.max_gross', minimum=0.0))
    # Preserve the caller's eligible signed signal set, but redistribute its
    # risk budget across those names.  Retaining raw magnitudes here would
    # merely reproduce a concentrated book when every sleeve is correlated.
    inverse_vol = [1.0 / volatilities[i] for i, _symbol in enumerate(symbols)]
    if sum(inverse_vol) == 0.0 or gross_budget == 0.0:
        return _empty_overlay(raw_targets, 'zero_risk_budget_or_raw_weight', future_rows)
    weights = [math.copysign(gross_budget * inverse_vol[i] / sum(inverse_vol), raw_targets[symbol]) for i, symbol in enumerate(symbols)]
    bindings: list[str] = []
    name_cap = _number(limits['max_name_abs'], 'limits.max_name_abs', minimum=0.0)
    capped = [max(-name_cap, min(name_cap, value)) for value in weights]
    if capped != weights:
        bindings.append('NAME_CAP')
        weights = capped
    def scale_all(ratio: float, label: str) -> None:
        nonlocal weights
        if ratio < 1.0:
            weights = [value * max(0.0, ratio) for value in weights]
            bindings.append(label)
    net = sum(weights)
    max_net = _number(limits['max_abs_net'], 'limits.max_abs_net', minimum=0.0)
    if abs(net) > 0.0:
        scale_all(max_net / abs(net), 'NET_CAP')
    for factor in factors:
        exposure = sum(weights[i] * factor_loadings[symbol][factor] for i, symbol in enumerate(symbols))
        bound = max_factor[factor]
        if abs(exposure) > 0.0:
            scale_all(bound / abs(exposure), f'FACTOR_CAP:{factor}')
    for tag in all_tags:
        exposure = sum(abs(weights[i]) for i, symbol in enumerate(symbols) if tag in tags[symbol])
        bound = max_tag[tag]
        if exposure > 0.0:
            scale_all(bound / exposure, f'TAG_GROSS_CAP:{tag}')
    port_returns = [sum(weights[i] * values[i] for i in range(len(symbols))) for _, values in prior_rows]
    worst_count = max(1, math.ceil(len(port_returns) * _number(limits['expected_shortfall_tail_fraction'], 'limits.expected_shortfall_tail_fraction', strictly_positive=True)))
    expected_shortfall = max(0.0, sum(sorted((-value for value in port_returns), reverse=True)[:worst_count]) / worst_count)
    if expected_shortfall > 0.0:
        scale_all(_number(limits['max_expected_shortfall'], 'limits.max_expected_shortfall', minimum=0.0) / expected_shortfall, 'EXPECTED_SHORTFALL_CAP')
    stress_losses = {name: max(0.0, -sum(weights[i] * values[symbol] for i, symbol in enumerate(symbols))) for name, values in stresses.items()}
    worst_stress = max(stress_losses.values())
    if worst_stress > 0.0:
        scale_all(_number(limits['max_stress_loss'], 'limits.max_stress_loss', minimum=0.0) / worst_stress, 'STRESS_LOSS_CAP')
    # Recompute all diagnostics after the monotonic cash-de-risking projection.
    covariance_vector = _mat_vec(covariance, weights)
    contributions_raw = [weights[i] * covariance_vector[i] for i in range(len(symbols))]
    contribution_total = sum(abs(value) for value in contributions_raw)
    contributions = {symbol: (abs(contributions_raw[i]) / contribution_total if contribution_total else 0.0) for i, symbol in enumerate(symbols)}
    max_contribution = max(contributions.values()) if contributions else 0.0
    effective_n = _effective_names(weights)
    if effective_n < _number(limits['min_effective_n'], 'limits.min_effective_n', strictly_positive=True) or max_contribution > _number(limits['max_covariance_contribution'], 'limits.max_covariance_contribution', minimum=0.0):
        return _empty_overlay(raw_targets, 'concentration_constraint_infeasible', future_rows)
    stress_losses = {name: max(0.0, -sum(weights[i] * values[symbol] for i, symbol in enumerate(symbols))) for name, values in stresses.items()}
    final_gross = sum(abs(value) for value in weights)
    return {
        'state': 'COVARIANCE_CONSTRAINED_REPORT_ONLY',
        'fallback_reason': None,
        'raw_targets': dict(sorted(raw_targets.items())),
        'proposed_covariance_targets': {symbol: weights[i] for i, symbol in enumerate(symbols)},
        'cash_residual_gross': max(0.0, 1.0 - final_gross),
        'constraint_bindings': bindings,
        'risk_contributions': contributions,
        'stress_losses': stress_losses,
        'covariance_diagnostics': {
            'status': 'STRICTLY_PRIOR_SHRUNK_COVARIANCE',
            'decision_time_utc': _format_utc(decision),
            'prior_observations_used': len(prior_rows),
            'future_observations_excluded': future_rows,
            'condition_number': max_eigen / min_eigen,
            'eigenvalues': sorted(eigenvalues),
            'effective_n': effective_n,
            'max_covariance_contribution': max_contribution,
            'expected_shortfall': max(0.0, sum(sorted((-value for value in [sum(weights[i] * values[i] for i in range(len(symbols))) for _, values in prior_rows]), reverse=True)[:worst_count]) / worst_count),
            'raw_gross': raw_gross,
            'final_gross': final_gross,
            'risk_panel_basis': 'CALLER_DECLARED_PNL_INDEPENDENT_NOT_EXTERNALLY_VERIFIED',
            'asset_tags': tags,
            'factor_exposure': {factor: sum(weights[i] * factor_loadings[symbol][factor] for i, symbol in enumerate(symbols)) for factor in factors},
        },
    }


def _risk_envelope(value: Mapping[str, Any], covariance_overlay: Mapping[str, Any], limits: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(value, 'envelope')
    _exact_keys(raw, {'status', 'decision_time_utc', 'realized_vol_annual', 'current_gross', 'tail_loss_estimate', 'recent_drawdown', 'volatility_jump', 'prior_scale'}, 'envelope')
    if raw.get('status') != 'OBSERVED':
        return {'state': 'NO_NEW_RISK_CASH', 'reason': 'envelope_input_status_not_observed', 'proposed_risk_scale': 0.0, 'scaled_gross': 0.0, 'scale_change_cost': 0.0, 'diagnostics': {'input_status': raw.get('status')}}
    decision = _utc_timestamp(raw.get('decision_time_utc'), 'envelope.decision_time_utc')
    covariance_time = covariance_overlay.get('covariance_diagnostics', {}).get('decision_time_utc')
    if covariance_time is not None and _format_utc(decision) != covariance_time:
        return {'state': 'NO_NEW_RISK_CASH', 'reason': 'envelope_and_covariance_decision_times_differ', 'proposed_risk_scale': 0.0, 'scaled_gross': 0.0, 'scale_change_cost': 0.0, 'diagnostics': {'decision_time_utc': _format_utc(decision)}}
    if covariance_overlay['state'] == 'NO_NEW_RISK_CASH':
        return {'state': 'NO_NEW_RISK_CASH', 'reason': 'covariance_overlay_failed_closed', 'proposed_risk_scale': 0.0, 'scaled_gross': 0.0, 'scale_change_cost': 0.0, 'diagnostics': {'decision_time_utc': _format_utc(decision)}}
    realized_vol = _number(raw.get('realized_vol_annual'), 'envelope.realized_vol_annual', strictly_positive=True)
    gross = _number(raw.get('current_gross'), 'envelope.current_gross', minimum=0.0)
    tail_loss = _number(raw.get('tail_loss_estimate'), 'envelope.tail_loss_estimate', minimum=0.0)
    drawdown = _number(raw.get('recent_drawdown'), 'envelope.recent_drawdown', minimum=0.0)
    vol_jump = _number(raw.get('volatility_jump'), 'envelope.volatility_jump', minimum=0.0)
    prior = _number(raw.get('prior_scale'), 'envelope.prior_scale', minimum=0.0)
    if gross == 0.0:
        return {'state': 'NO_NEW_RISK_CASH', 'reason': 'current_gross_is_zero', 'proposed_risk_scale': 0.0, 'scaled_gross': 0.0, 'scale_change_cost': prior * gross * _number(limits['turnover_cost_rate'], 'limits.turnover_cost_rate', minimum=0.0), 'diagnostics': {'decision_time_utc': _format_utc(decision)}}
    candidates = {
        'VOL_TARGET': _number(limits['target_annual_vol'], 'limits.target_annual_vol', minimum=0.0) / realized_vol,
        'MAX_LEVERAGE': _number(limits['max_leverage'], 'limits.max_leverage', minimum=0.0),
        'MAX_SCALED_GROSS': _number(limits['max_scaled_gross'], 'limits.max_scaled_gross', minimum=0.0) / gross,
        'TAIL_LOSS': (_number(limits['max_tail_loss'], 'limits.max_tail_loss', minimum=0.0) / tail_loss if tail_loss > 0.0 else _number(limits['max_leverage'], 'limits.max_leverage', minimum=0.0)),
    }
    gates = []
    if drawdown > _number(limits['max_drawdown'], 'limits.max_drawdown', minimum=0.0):
        gates.append('DRAWDOWN_GATE')
    if vol_jump > _number(limits['max_volatility_jump'], 'limits.max_volatility_jump', minimum=0.0):
        gates.append('VOLATILITY_JUMP_GATE')
    scale = 0.0 if gates else max(0.0, min(candidates.values()))
    bindings = gates + [name for name, candidate in candidates.items() if not gates and abs(candidate - scale) <= 1e-15]
    scaled_gross = scale * gross
    if scaled_gross > _number(limits['max_scaled_gross'], 'limits.max_scaled_gross', minimum=0.0) + _number(limits['accounting_tolerance'], 'limits.accounting_tolerance', minimum=0.0):
        raise PortfolioRiskV2Error('risk envelope violates its caller-declared gross ceiling')
    return {
        'state': 'REPORT_ONLY_PROPOSED_SCALE' if scale > 0.0 else 'NO_NEW_RISK_CASH',
        'reason': None if scale > 0.0 else 'tail_or_path_gate_bound',
        'proposed_risk_scale': scale,
        'scaled_gross': scaled_gross,
        'scale_change_cost': abs(scale - prior) * gross * _number(limits['turnover_cost_rate'], 'limits.turnover_cost_rate', minimum=0.0),
        'constraint_bindings': bindings,
        'diagnostics': {
            'decision_time_utc': _format_utc(decision),
            'realized_vol_annual': realized_vol,
            'current_gross': gross,
            'tail_loss_estimate': tail_loss,
            'recent_drawdown': drawdown,
            'volatility_jump': vol_jump,
            'forecast_error_not_available_without_later_observation': True,
        },
    }


def build_risk_overlay_v2(
    source_set: Mapping[str, Any],
    policy: Mapping[str, Any],
    raw_targets: Mapping[str, Any],
    risk_model: Mapping[str, Any],
    envelope: Mapping[str, Any],
    *,
    qualified_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    '''Project raw targets with strictly-prior covariance and an opt-in gross-and-tail report envelope.'''
    sources = validate_canonical_source_set(source_set)
    declared_policy = _validate_policy(policy, 'PORTFOLIO_RISK_OVERLAY')
    limits = _overlay_policy_limits(declared_policy)
    qualified = _qualified_inputs(qualified_inputs, sources, {'risk_panel', 'metadata', 'portfolio_accounting'})
    covariance_overlay = _prior_covariance_overlay(raw_targets, risk_model, limits)
    envelope_overlay = _risk_envelope(envelope, covariance_overlay, limits)
    scale = float(envelope_overlay['proposed_risk_scale'])
    final_targets = {symbol: value * scale for symbol, value in covariance_overlay['proposed_covariance_targets'].items()}
    payload = {
        'covariance_overlay': covariance_overlay,
        'gross_tail_envelope': envelope_overlay,
        'proposed_final_targets_after_envelope': final_targets,
        'model_scope': 'caller_declared_policy_report_only_no_signal_redefinition_or_execution',
    }
    status = 'NO_NEW_RISK_CASH' if scale == 0.0 else 'REPORT_ONLY_CONSTRAINED_TARGETS'
    return _result('covariance_concentration_and_gross_tail_overlay_v2', sources, declared_policy, qualified, status, payload)


def build_prop_firm_terms_snapshot_v2(
    firm_id: str,
    source_snapshot_status: str,
    captured_at_utc: str,
    source_snapshot_reference: str,
    fields: Mapping[str, Mapping[str, Any]],
    material_fields: Sequence[str],
) -> dict[str, Any]:
    '''Bind caller-declared rule field status without claiming external firm-term verification.'''
    if source_snapshot_status not in {'VERIFIED', 'ASSUMED', 'UNKNOWN'}:
        raise PortfolioRiskV2Error('source_snapshot_status must be VERIFIED, ASSUMED, or UNKNOWN')
    if not isinstance(material_fields, Sequence) or isinstance(material_fields, (str, bytes)) or not material_fields:
        raise PortfolioRiskV2Error('material_fields must be a nonempty array')
    material = sorted({_string(item, 'material_fields item') for item in material_fields})
    fields_raw = _mapping(fields, 'fields')
    if set(material) - set(fields_raw):
        raise PortfolioRiskV2Error('every material field must occur in fields')
    normalized: dict[str, Any] = {}
    for name, item in sorted(fields_raw.items()):
        detail = _mapping(item, f'fields.{name}')
        _exact_keys(detail, {'status', 'value'}, f'fields.{name}')
        state = detail.get('status')
        if state not in {'VERIFIED', 'ASSUMED', 'UNKNOWN'}:
            raise PortfolioRiskV2Error(f'fields.{name}.status is unsupported')
        if state == 'UNKNOWN' and detail.get('value') is not None:
            raise PortfolioRiskV2Error(f'unknown field {name} must not fabricate a value')
        if state != 'UNKNOWN' and detail.get('value') is None:
            raise PortfolioRiskV2Error(f'known or assumed field {name} requires a caller-supplied value')
        normalized[name] = {'status': state, 'value': _json_copy(detail.get('value'), f'fields.{name}.value')}
    unsigned = {
        'schema': TERMS_SCHEMA,
        'firm_id': _string(firm_id, 'firm_id'),
        'source_snapshot_status': source_snapshot_status,
        'captured_at_utc': _format_utc(_utc_timestamp(captured_at_utc, 'captured_at_utc')),
        'source_snapshot_reference': _string(source_snapshot_reference, 'source_snapshot_reference'),
        'fields': normalized,
        'material_fields': material,
        'external_terms_verification': 'CALLER_DECLARED_STATUS_NOT_EXTERNALLY_VERIFIED',
    }
    return {**unsigned, 'terms_snapshot_sha256': canonical_json_sha256(unsigned)}


def _validate_terms(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(value, 'terms_snapshot')
    _exact_keys(raw, {'schema', 'firm_id', 'source_snapshot_status', 'captured_at_utc', 'source_snapshot_reference', 'fields', 'material_fields', 'external_terms_verification', 'terms_snapshot_sha256'}, 'terms_snapshot')
    candidate = build_prop_firm_terms_snapshot_v2(
        _string(raw.get('firm_id'), 'terms_snapshot.firm_id'),
        raw.get('source_snapshot_status'),
        _format_utc(_utc_timestamp(raw.get('captured_at_utc'), 'terms_snapshot.captured_at_utc')),
        _string(raw.get('source_snapshot_reference'), 'terms_snapshot.source_snapshot_reference'),
        _mapping(raw.get('fields'), 'terms_snapshot.fields'),
        raw.get('material_fields'),
    )
    if raw.get('external_terms_verification') != 'CALLER_DECLARED_STATUS_NOT_EXTERNALLY_VERIFIED':
        raise PortfolioRiskV2Error('terms_snapshot may not make an external verification claim')
    if _sha256(raw.get('terms_snapshot_sha256'), 'terms_snapshot.terms_snapshot_sha256') != candidate['terms_snapshot_sha256']:
        raise PortfolioRiskV2Error('terms_snapshot_sha256 does not bind the declared terms')
    return candidate


def _term_state(terms: Mapping[str, Any], name: str) -> tuple[str, Any]:
    field = terms['fields'].get(name)
    if field is None:
        return 'UNKNOWN', None
    return field['status'], field['value']


def _career_accounting(value: Mapping[str, Any], tolerance: float) -> dict[str, Any]:
    raw = _mapping(value, 'career')
    _exact_keys(raw, {'career_id', 'scenario_id', 'path_mode', 'event_ledger'}, 'career')
    mode = _string(raw.get('path_mode'), 'career.path_mode')
    if mode not in {'INTRADAY_OBSERVED', 'CONSERVATIVE_SCENARIO', 'DAILY_CLOSE_ONLY'}:
        raise PortfolioRiskV2Error('career.path_mode is unsupported')
    events_value = raw.get('event_ledger')
    if not isinstance(events_value, Sequence) or isinstance(events_value, (str, bytes)) or not events_value:
        raise PortfolioRiskV2Error('career.event_ledger must be a nonempty array')
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    prior_after: float | None = None
    prior_time: datetime | None = None
    for index, event_value in enumerate(events_value):
        event = _mapping(event_value, f'career.event_ledger[{index}]')
        _exact_keys(event, {'event_id', 'timestamp_utc', 'session_id', 'event_type', 'equity_before', 'trading_pnl_cash', 'cash_flow_cash', 'equity_after'}, f'career.event_ledger[{index}]')
        event_id = _string(event.get('event_id'), f'career.event_ledger[{index}].event_id')
        if event_id in seen:
            raise PortfolioRiskV2Error('career event_id values must be unique')
        seen.add(event_id)
        moment = _utc_timestamp(event.get('timestamp_utc'), f'career.event_ledger[{index}].timestamp_utc')
        if prior_time is not None and moment < prior_time:
            raise PortfolioRiskV2Error('career.event_ledger must be chronological')
        prior_time = moment
        event_type = _string(event.get('event_type'), f'career.event_ledger[{index}].event_type')
        if event_type not in {'MARK', 'FEE', 'PAYOUT', 'WITHDRAWAL'}:
            raise PortfolioRiskV2Error('career event_type is unsupported')
        before = _number(event.get('equity_before'), f'career.event_ledger[{index}].equity_before')
        pnl = _number(event.get('trading_pnl_cash'), f'career.event_ledger[{index}].trading_pnl_cash')
        cash_flow = _number(event.get('cash_flow_cash'), f'career.event_ledger[{index}].cash_flow_cash')
        after = _number(event.get('equity_after'), f'career.event_ledger[{index}].equity_after')
        if event_type == 'MARK' and cash_flow != 0.0:
            raise PortfolioRiskV2Error('MARK rows must have zero cash_flow_cash')
        if event_type in {'FEE', 'PAYOUT', 'WITHDRAWAL'} and cash_flow > 0.0:
            raise PortfolioRiskV2Error('fee, payout, and withdrawal ledger cash flows must be nonpositive')
        if prior_after is not None and abs(before - prior_after) > tolerance:
            raise PortfolioRiskV2Error('event ledger equity_before does not carry forward prior equity_after')
        if abs(after - (before + pnl + cash_flow)) > tolerance:
            raise PortfolioRiskV2Error('event ledger row does not reconcile equity_before + trading_pnl + cash_flow')
        events.append({
            'event_id': event_id,
            'timestamp_utc': _format_utc(moment),
            'session_id': _string(event.get('session_id'), f'career.event_ledger[{index}].session_id'),
            'event_type': event_type,
            'equity_before': before,
            'trading_pnl_cash': pnl,
            'cash_flow_cash': cash_flow,
            'equity_after': after,
        })
        prior_after = after
    starting = events[0]['equity_before']
    fees = -sum(row['cash_flow_cash'] for row in events if row['event_type'] == 'FEE')
    payouts = -sum(row['cash_flow_cash'] for row in events if row['event_type'] == 'PAYOUT')
    withdrawals = -sum(row['cash_flow_cash'] for row in events if row['event_type'] == 'WITHDRAWAL')
    total_pnl = sum(row['trading_pnl_cash'] for row in events)
    terminal = events[-1]['equity_after']
    residual = terminal - (starting + total_pnl - fees - payouts - withdrawals)
    if abs(residual) > tolerance:
        raise PortfolioRiskV2Error('career terminal equity does not reconcile to its event ledger')
    dates = sorted({row['timestamp_utc'][:10] for row in events})
    return {
        'career_id': _string(raw.get('career_id'), 'career.career_id'),
        'scenario_id': _string(raw.get('scenario_id'), 'career.scenario_id'),
        'path_mode': mode,
        'event_ledger': events,
        'starting_equity': starting,
        'terminal_equity': terminal,
        'trading_pnl_cash': total_pnl,
        'fees_cash': fees,
        'payouts_cash': payouts,
        'withdrawals_cash': withdrawals,
        'terminal_reconciliation_residual': residual,
        'calendar_dates': dates,
    }


def _rule_values(terms: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    required = ['daily_loss_limit_cash', 'max_loss_limit_cash', 'daily_loss_basis', 'max_loss_type', 'trailing_loss_update_timing']
    unknown = [name for name in required if _term_state(terms, name)[0] == 'UNKNOWN']
    if unknown:
        return None, unknown
    values = {name: _term_state(terms, name)[1] for name in required}
    values['daily_loss_limit_cash'] = _number(values['daily_loss_limit_cash'], 'terms.daily_loss_limit_cash', minimum=0.0)
    values['max_loss_limit_cash'] = _number(values['max_loss_limit_cash'], 'terms.max_loss_limit_cash', minimum=0.0)
    if values['daily_loss_basis'] not in {'SESSION_START_EQUITY', 'INITIAL_EQUITY'}:
        raise PortfolioRiskV2Error('terms.daily_loss_basis is unsupported')
    if values['max_loss_type'] not in {'STATIC', 'TRAILING'}:
        raise PortfolioRiskV2Error('terms.max_loss_type is unsupported')
    if values['trailing_loss_update_timing'] not in {'INTRADAY', 'END_OF_DAY'}:
        raise PortfolioRiskV2Error('terms.trailing_loss_update_timing is unsupported')
    return values, []


def _career_breaches(career: Mapping[str, Any], rules: Mapping[str, Any] | None) -> dict[str, Any]:
    if rules is None:
        return {'breach_status': 'NOT_EVALUATED_UNKNOWN_RULE', 'breach_events': [], 'breach_assurance': 'BLOCKED_UNKNOWN_RULE'}
    starting = float(career['starting_equity'])
    peak_intraday = starting
    peak_eod = starting
    current_session: str | None = None
    session_start = starting
    session_peak = starting
    breaches: list[dict[str, Any]] = []
    for event in career['event_ledger']:
        session = event['session_id']
        if current_session is None:
            current_session = session
            session_start = event['equity_before']
            session_peak = event['equity_before']
        elif session != current_session:
            peak_eod = max(peak_eod, session_peak)
            current_session = session
            session_start = event['equity_before']
            session_peak = event['equity_before']
        equity = float(event['equity_after'])
        daily_anchor = session_start if rules['daily_loss_basis'] == 'SESSION_START_EQUITY' else starting
        daily_floor = daily_anchor - rules['daily_loss_limit_cash']
        if rules['max_loss_type'] == 'STATIC':
            max_floor = starting - rules['max_loss_limit_cash']
        elif rules['trailing_loss_update_timing'] == 'INTRADAY':
            peak_intraday = max(peak_intraday, event['equity_before'], equity)
            max_floor = peak_intraday - rules['max_loss_limit_cash']
        else:
            max_floor = peak_eod - rules['max_loss_limit_cash']
        if equity < daily_floor:
            breaches.append({'event_id': event['event_id'], 'timestamp_utc': event['timestamp_utc'], 'rule': 'DAILY_LOSS', 'equity_after': equity, 'floor': daily_floor})
        if equity < max_floor:
            breaches.append({'event_id': event['event_id'], 'timestamp_utc': event['timestamp_utc'], 'rule': 'MAX_LOSS', 'equity_after': equity, 'floor': max_floor})
        session_peak = max(session_peak, equity)
    if career['path_mode'] == 'DAILY_CLOSE_ONLY':
        return {'breach_status': 'UNQUALIFIED_DAILY_ONLY', 'breach_events': breaches, 'breach_assurance': 'INSUFFICIENT_INTRADAY_PATH_NEVER_A_PASS'}
    if career['path_mode'] == 'CONSERVATIVE_SCENARIO':
        return {'breach_status': 'CONSERVATIVE_SCENARIO_BREACH' if breaches else 'CONSERVATIVE_SCENARIO_NO_BREACH', 'breach_events': breaches, 'breach_assurance': 'DECLARED_CONSERVATIVE_SCENARIO_NOT_OBSERVED'}
    return {'breach_status': 'OBSERVED_INTRADAY_BREACH' if breaches else 'OBSERVED_INTRADAY_NO_BREACH', 'breach_events': breaches, 'breach_assurance': 'OBSERVED_INTRADAY_PATH'}


def _dependence_summary(careers: Sequence[Mapping[str, Any]], block_days: int, replicates: int, seed: int, confidence: float) -> dict[str, Any]:
    sets = [set(item['calendar_dates']) for item in careers]
    n = len(sets)
    denominator = 0.0
    for left in sets:
        for right in sets:
            if left is right:
                denominator += 1.0
            else:
                denominator += len(left & right) / max(1, min(len(left), len(right)))
    effective_n = n * n / denominator if denominator else 0.0
    selected: list[int] = []
    occupied: set[str] = set()
    for index, dates in sorted(enumerate(sets), key=lambda pair: (min(pair[1]), careers[pair[0]]['career_id'])):
        if not dates & occupied:
            selected.append(index)
            occupied.update(dates)
    breach_flags = [bool(item['breach_events']) for item in careers]
    block_map: dict[int, list[int]] = {}
    for index, item in enumerate(careers):
        start = datetime.fromisoformat(item['calendar_dates'][0]).date().toordinal()
        block_map.setdefault(start // block_days, []).append(index)
    blocks = [block_map[key] for key in sorted(block_map)]
    rng = random.Random(seed)
    bootstrap: list[float] = []
    for _ in range(replicates):
        sample = [index for _ in blocks for index in rng.choice(blocks)]
        bootstrap.append(sum(breach_flags[index] for index in sample) / len(sample))
    bootstrap.sort()
    lower_index = max(0, math.floor(((1.0 - confidence) / 2.0) * (replicates - 1)))
    upper_index = min(replicates - 1, math.ceil(((1.0 + confidence) / 2.0) * (replicates - 1)))
    return {
        'careers': n,
        'unique_calendar_dates': len(set().union(*sets)),
        'effective_sample_size_overlap_adjusted': effective_n,
        'overlap_adjustment_method': 'n_squared_over_pairwise_min_window_overlap_sum',
        'nonoverlapping_sensitivity': {
            'careers': len(selected),
            'breach_rate': sum(breach_flags[index] for index in selected) / len(selected) if selected else None,
            'selected_career_ids': [careers[index]['career_id'] for index in selected],
        },
        'block_bootstrap': {
            'block_length_days': block_days,
            'replicates': replicates,
            'seed': seed,
            'confidence_level': confidence,
            'breach_rate_interval': [bootstrap[lower_index], bootstrap[upper_index]],
        },
    }


def build_prop_firm_scenario_v2(
    source_set: Mapping[str, Any],
    policy: Mapping[str, Any],
    terms_snapshot: Mapping[str, Any],
    careers: Sequence[Mapping[str, Any]],
    *,
    qualified_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    '''Evaluate only caller-supplied scenario ledgers; never rank a firm when material terms are unknown.'''
    sources = validate_canonical_source_set(source_set)
    declared_policy = _validate_policy(policy, 'PROP_FIRM_SCENARIO')
    limits = _limits(declared_policy, {'block_length_days', 'bootstrap_replicates', 'bootstrap_seed', 'confidence_level', 'accounting_tolerance'}, 'prop scenario policy limits')
    block_days = _integer(limits['block_length_days'], 'limits.block_length_days', minimum=1)
    replicates = _integer(limits['bootstrap_replicates'], 'limits.bootstrap_replicates', minimum=1)
    seed = _integer(limits['bootstrap_seed'], 'limits.bootstrap_seed', minimum=0)
    confidence = _number(limits['confidence_level'], 'limits.confidence_level', strictly_positive=True)
    if confidence >= 1.0:
        raise PortfolioRiskV2Error('limits.confidence_level must be less than one')
    tolerance = _number(limits['accounting_tolerance'], 'limits.accounting_tolerance', minimum=0.0)
    qualified = _qualified_inputs(qualified_inputs, sources, {'firm_terms', 'portfolio_path'})
    terms = _validate_terms(terms_snapshot)
    if not isinstance(careers, Sequence) or isinstance(careers, (str, bytes)) or not careers:
        raise PortfolioRiskV2Error('careers must be a nonempty array')
    rule_values, unknown_required_rules = _rule_values(terms)
    rows = []
    ids: set[str] = set()
    for career in careers:
        row = _career_accounting(career, tolerance)
        if row['career_id'] in ids:
            raise PortfolioRiskV2Error('career_id values must be unique')
        ids.add(row['career_id'])
        row.update(_career_breaches(row, rule_values))
        rows.append(row)
    material_unknown = [name for name in terms['material_fields'] if terms['fields'][name]['status'] == 'UNKNOWN']
    if terms['source_snapshot_status'] == 'UNKNOWN':
        material_unknown.insert(0, 'source_snapshot_status')
    material_assumed = [name for name in terms['material_fields'] if terms['fields'][name]['status'] == 'ASSUMED']
    if terms['source_snapshot_status'] == 'ASSUMED':
        material_assumed.insert(0, 'source_snapshot_status')
    if material_unknown or unknown_required_rules:
        ranking_status = 'BLOCKED_UNKNOWN_MATERIAL_TERMS'
        ranking_eligible = False
    elif material_assumed:
        ranking_status = 'CONDITIONAL_ASSUMED_TERMS_NO_QUALIFIED_RANKING'
        ranking_eligible = False
    else:
        ranking_status = 'CALLER_DECLARED_VERIFIED_TERMS_SCENARIO_ONLY'
        ranking_eligible = True
    dependence = _dependence_summary(rows, block_days, replicates, seed, confidence)
    scenario_summary = []
    for scenario in sorted({row['scenario_id'] for row in rows}):
        subset = [row for row in rows if row['scenario_id'] == scenario]
        scenario_summary.append({
            'scenario_id': scenario,
            'careers': len(subset),
            'breach_or_conservative_breach_count': sum(bool(row['breach_events']) for row in subset),
            'daily_only_insufficient_count': sum(row['breach_status'] == 'UNQUALIFIED_DAILY_ONLY' for row in subset),
            'fees_cash': sum(float(row['fees_cash']) for row in subset),
            'payouts_cash': sum(float(row['payouts_cash']) for row in subset),
            'withdrawals_cash': sum(float(row['withdrawals_cash']) for row in subset),
            'terminal_equity_sum': sum(float(row['terminal_equity']) for row in subset),
        })
    payload = {
        'terms_snapshot': terms,
        'career_ledger': rows,
        'scenario_summary': scenario_summary,
        'dependence_aware_uncertainty': dependence,
        'ranking_status': ranking_status,
        'qualified_scenario_ranking': ranking_eligible,
        'unknown_material_terms': sorted(set(material_unknown + unknown_required_rules)),
        'assumed_material_terms': sorted(set(material_assumed)),
        'scenario_only': True,
        'no_purchase_or_live_trading_authorization': True,
    }
    return _result('prop_firm_rule_timing_and_dependence_v2', sources, declared_policy, qualified, ranking_status, payload)


def _load_json_object(path: str) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise PortfolioRiskV2Error(f'cannot read JSON object from {path}') from exc
    return _mapping(value, f'JSON at {path}')


def _emit(value: Mapping[str, Any], output: str | None) -> None:
    text = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
    if output is None:
        print(text, end='')
    else:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
        print(json.dumps({'status': value.get('analysis_status', 'POLICY_BUILT'), 'output': str(target)}, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    '''Run an offline successor model from one caller-supplied JSON request.'''
    parser = argparse.ArgumentParser(description='Offline Orderflow Edge Lab portfolio-risk v2 report models; no network or trading activity.')
    subcommands = parser.add_subparsers(dest='command', required=True)
    for name, help_text in (
        ('policy', 'hash a caller-declared inert or report-only policy'),
        ('stop', 'reconcile planned stop loss with executable BBO exits'),
        ('ledger', 'build a self-financing human-book ledger'),
        ('overlay', 'build prior-only covariance and gross-tail report overlay'),
        ('prop', 'evaluate rule-timed, dependence-aware prop scenarios'),
    ):
        command = subcommands.add_parser(name, help=help_text)
        command.add_argument('--input', required=True, help='JSON request path')
        command.add_argument('--output', help='new v2 JSON output path; stdout when omitted')
    args = parser.parse_args(argv)
    try:
        request = _load_json_object(args.input)
        if args.command == 'policy':
            _exact_keys(request, {'policy_id', 'policy_kind', 'limits', 'activation_state'}, 'policy request')
            result = build_risk_policy_v2(request['policy_id'], request['policy_kind'], request['limits'], activation_state=request['activation_state'])
        elif args.command == 'stop':
            _exact_keys(request, {'source_set', 'policy', 'executions', 'qualified_inputs'}, 'stop request')
            result = build_stop_loss_reconciliation_v2(request['source_set'], request['policy'], request['executions'], qualified_inputs=request['qualified_inputs'])
        elif args.command == 'ledger':
            _exact_keys(request, {'source_set', 'policy', 'initial_book', 'intervals', 'qualified_inputs'}, 'ledger request')
            result = build_self_financing_ledger_v2(request['source_set'], request['policy'], request['initial_book'], request['intervals'], qualified_inputs=request['qualified_inputs'])
        elif args.command == 'overlay':
            _exact_keys(request, {'source_set', 'policy', 'raw_targets', 'risk_model', 'envelope', 'qualified_inputs'}, 'overlay request')
            result = build_risk_overlay_v2(request['source_set'], request['policy'], request['raw_targets'], request['risk_model'], request['envelope'], qualified_inputs=request['qualified_inputs'])
        else:
            _exact_keys(request, {'source_set', 'policy', 'terms_snapshot', 'careers', 'qualified_inputs'}, 'prop request')
            result = build_prop_firm_scenario_v2(request['source_set'], request['policy'], request['terms_snapshot'], request['careers'], qualified_inputs=request['qualified_inputs'])
        _emit(result, args.output)
        return 0
    except (PortfolioRiskV2Error, ContractValidationError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({'status': 'INVALID', 'error': str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
