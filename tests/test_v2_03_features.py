from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.contracts_v2 import (
    CLOSED_OPEN,
    build_canonical_source_set,
    build_source_record,
    build_utc_interval,
    canonical_json_sha256,
    non_authority_claims,
)
from orderflow_edge_lab.features_v2 import (
    CAPTURE_PAIR_BINDING_SCHEMA,
    LINEAGE_SCHEMA,
    FeatureV2Error,
    build_btc_correlation_input_v2,
    build_btc_correlation_panel_v2,
    build_btc_correlation_policy_v2,
    build_feature_policy_v2,
    build_full_baseline_orthogonality_v2,
    build_mature_target_v2,
    build_orthogonality_policy_v2,
    build_pnl_stratification_v2,
    build_quote_provenance_v2,
    build_state_discovery_v2,
    main,
    scan_market_state_v2,
)

BASE = 1_800_000_000_000_000_000
SECOND = 1_000_000_000
FROZEN_HASH = 'f' * 64


def utc(ns: int) -> str:
    return datetime.fromtimestamp(ns / SECOND, tz=timezone.utc).isoformat().replace('+00:00', 'Z')


def source_set(label: str = 'raw') -> dict:
    return build_canonical_source_set([
        build_source_record(label, {'schema': 'orderflow_edge_lab.file_identity.v2', 'size_bytes': 1, 'sha256': 'a' * 64})
    ])


def capture(sources: dict, start: int = BASE, end: int = BASE + 30 * SECOND) -> dict:
    unsigned = {
        'schema': CAPTURE_PAIR_BINDING_SCHEMA,
        'analysis': 'capture_pair_replay_eligibility',
        'source_set': sources,
        'outcome': 'COMPLETE',
        'replay_status': 'REPLAY_ELIGIBLE',
        'capture_start_utc': utc(start),
        'capture_end_utc': utc(end),
        'non_authority_claims': non_authority_claims(),
    }
    return {**unsigned, 'capture_pair_sha256': canonical_json_sha256(unsigned)}


def feature_policy(*, start: int = BASE, end: int = BASE + 10 * SECOND, horizon: int = SECOND, sample: int = SECOND, max_age: int = 2 * SECOND, max_gap: int = 5 * SECOND) -> dict:
    return build_feature_policy_v2({
        'policy_id': 'feature-policy-fixture',
        'frozen_at_utc': utc(start - SECOND),
        'evidence_start_utc': utc(start),
        'lifecycle': 'FROZEN_FOR_NEW_EVIDENCE',
        'freeze_evidence_sha256': FROZEN_HASH,
        'quote': {
            'accepted_event_types': ['snapshot', 'depth'],
            'max_quote_age_ns': max_age,
            'max_context_quote_age_ns': max_age,
            'require_exchange_timestamp': False,
            'allow_recovered_book': False,
            'recovered_book_cooldown_ns': 0,
            'require_context_quote': False,
        },
        'scan': {
            'analysis_interval': build_utc_interval(utc(start), utc(end), convention=CLOSED_OPEN),
            'sample_cadence_ns': sample,
            'context_lookback_ns': SECOND,
            'minimum_association_observations': 2,
        },
        'targets': [{
            'target_id': 'one_second',
            'horizon_ns': horizon,
            'max_endpoint_lag_ns': SECOND,
            'max_interior_gap_ns': max_gap,
            'minimum_quote_points': 1,
        }],
    })


def depth(symbol: str, ns: int, *, mid: float = 100.0, spread_bps: float = 10.0, applied: bool = True) -> dict:
    half = mid * (spread_bps / 10_000.0) / 2.0
    return {
        'symbol': symbol,
        'event_type': 'depth',
        'received_at_ns': ns,
        'exchange_ts_ms': ns // 1_000_000,
        'depth_applied': applied,
        'best_bid': mid - half,
        'best_ask': mid + half,
        'best_bid_contract_volume': 10.0,
        'best_ask_contract_volume': 10.0,
        'book_imbalance_10': 0.2,
        'microprice': mid,
        'depth_flow_imbalance': 0.1,
    }


def mature_events(start: int = BASE, end: int = BASE + 10 * SECOND) -> list[dict]:
    rows: list[dict] = []
    for offset in range(0, int((end - start) // SECOND) + 1):
        ns = start + offset * SECOND
        rows.extend([
            depth('ETH_USDT', ns, mid=100.0 + offset * 0.1),
            depth('BTC_USDT', ns, mid=200.0 + offset * 0.2),
        ])
    return rows


class QuoteAndTargetV2Tests(unittest.TestCase):
    def test_stale_depth_fails_fresh_depth_passes_and_trade_echo_is_never_quote(self):
        sources = source_set()
        policy = feature_policy(max_age=2 * SECOND)
        old = depth('ETH_USDT', BASE)
        stale = build_quote_provenance_v2(old, feature_received_at_ns=BASE + 5 * SECOND, source_set=sources, policy=policy)
        fresh = build_quote_provenance_v2(old, feature_received_at_ns=BASE + SECOND, source_set=sources, policy=policy)
        echoed = dict(old, event_type='trade', received_at_ns=BASE + SECOND)
        echo = build_quote_provenance_v2(echoed, feature_received_at_ns=BASE + SECOND, source_set=sources, policy=policy)
        self.assertEqual(stale['eligibility_reason'], 'QUOTE_STALE')
        self.assertTrue(fresh['quote_is_fresh'])
        self.assertEqual(echo['eligibility_reason'], 'EVENT_NOT_ACCEPTED_QUOTE_SOURCE')

    def test_strict_target_excludes_anchor_and_late_or_truncated_targets_fail_closed(self):
        sources = source_set()
        policy = feature_policy(horizon=5 * SECOND)
        anchor = build_quote_provenance_v2(depth('ETH_USDT', BASE, spread_bps=200), feature_received_at_ns=BASE, source_set=sources, policy=policy)
        points = [
            anchor,
            build_quote_provenance_v2(depth('ETH_USDT', BASE + SECOND, spread_bps=10), feature_received_at_ns=BASE + SECOND, source_set=sources, policy=policy),
            build_quote_provenance_v2(depth('ETH_USDT', BASE + 5 * SECOND, spread_bps=10), feature_received_at_ns=BASE + 5 * SECOND, source_set=sources, policy=policy),
        ]
        target = build_mature_target_v2(anchor, points, target_spec=policy['targets'][0], capture_end_ns=BASE + 8 * SECOND, source_set=sources, policy=policy)
        self.assertEqual(target['maturity'], 'MATURE')
        self.assertAlmostEqual(target['values']['future_spread_bps'], 10.0, places=9)
        late = points[:-1] + [
            build_quote_provenance_v2(depth('ETH_USDT', BASE + 7 * SECOND, spread_bps=10), feature_received_at_ns=BASE + 7 * SECOND, source_set=sources, policy=policy)
        ]
        late_target = build_mature_target_v2(anchor, late, target_spec=policy['targets'][0], capture_end_ns=BASE + 10 * SECOND, source_set=sources, policy=policy)
        self.assertEqual(late_target['ineligibility_reason'], 'ENDPOINT_TOO_LATE')
        truncated = build_mature_target_v2(anchor, points, target_spec=policy['targets'][0], capture_end_ns=BASE + 3 * SECOND, source_set=sources, policy=policy)
        self.assertEqual(truncated['maturity'], 'NOT_MATURE')
        self.assertEqual(truncated['ineligibility_reason'], 'CAPTURE_ENDED_BEFORE_HORIZON')
        gap_policy = feature_policy(horizon=5 * SECOND, max_gap=SECOND)
        gap_anchor = build_quote_provenance_v2(depth('ETH_USDT', BASE, spread_bps=200), feature_received_at_ns=BASE, source_set=sources, policy=gap_policy)
        gap_points = [
            gap_anchor,
            build_quote_provenance_v2(depth('ETH_USDT', BASE + SECOND, spread_bps=10), feature_received_at_ns=BASE + SECOND, source_set=sources, policy=gap_policy),
            build_quote_provenance_v2(depth('ETH_USDT', BASE + 5 * SECOND, spread_bps=10), feature_received_at_ns=BASE + 5 * SECOND, source_set=sources, policy=gap_policy),
        ]
        gapped = build_mature_target_v2(gap_anchor, gap_points, target_spec=gap_policy['targets'][0], capture_end_ns=BASE + 8 * SECOND, source_set=sources, policy=gap_policy)
        self.assertEqual(gapped['ineligibility_reason'], 'INTERIOR_QUOTE_GAP_EXCEEDED')
        self.assertEqual(gapped, build_mature_target_v2(gap_anchor, gap_points, target_spec=gap_policy['targets'][0], capture_end_ns=BASE + 8 * SECOND, source_set=sources, policy=gap_policy))

    def test_state_scan_counts_only_genuine_quote_updates_and_exposes_provenance(self):
        sources = source_set()
        policy = feature_policy(start=BASE, end=BASE + 10 * SECOND, horizon=5 * SECOND, sample=5 * SECOND, max_age=2 * SECOND)
        rows = [
            depth('ETH_USDT', BASE, spread_bps=20),
            depth('BTC_USDT', BASE, mid=200.0),
            {
                **depth('ETH_USDT', BASE + 5 * SECOND, spread_bps=20),
                'event_type': 'trade', 'rolling_buy_volume': 9.0, 'rolling_sell_volume': 1.0,
            },
            depth('BTC_USDT', BASE + 5 * SECOND, mid=201.0),
        ]
        rows.sort(key=lambda row: row['received_at_ns'])
        report = scan_market_state_v2(rows, source_set=sources, capture_pair=capture(sources, end=BASE + 12 * SECOND), policy=policy, symbol='ETH_USDT', context_symbol='BTC_USDT')
        self.assertEqual(report['quote_series']['quote_update_intensity_count'], 1)
        self.assertEqual(report['quote_series']['trade_carried_bbo_excluded_count'], 1)
        stale = report['observations'][1]['quote_provenance']
        self.assertEqual(stale['quote_source_event_type'], 'depth')
        self.assertEqual(stale['quote_age_ns_at_feature'], 5 * SECOND)
        self.assertEqual(stale['eligibility_reason'], 'QUOTE_STALE')


class FullBaselineV2Tests(unittest.TestCase):
    def orth_policy(self) -> dict:
        return build_orthogonality_policy_v2({
            'policy_id': 'orth-fixture', 'frozen_at_utc': utc(BASE - SECOND), 'evidence_start_utc': utc(BASE),
            'lifecycle': 'FROZEN_FOR_NEW_EVIDENCE', 'freeze_evidence_sha256': FROZEN_HASH,
            'target_baselines': {'future_state': ['base_a', 'base_b']},
            'candidate_admission_order': {'future_state': ['unclustered_noise', 'duplicate_base']},
            'redundancy_threshold': 0.9, 'resamples': 100, 'confidence': 0.9, 'seed': 7,
        })

    def rows(self) -> list[dict]:
        rows = []
        for index in range(36):
            a = float(index % 7)
            b = float((index * 3) % 5)
            noise = float((index * 11) % 13)
            rows.append({
                'observation_id': f'obs-{index}', 'batch_id': f'batch-{index % 3}', 'dependence_cluster': f'cluster-{index % 4}',
                'feature_eligibility': 'ELIGIBLE', 'target_maturity': {'future_state': 'MATURE'},
                'features': {'base_a': a, 'base_b': b, 'unclustered_noise': noise, 'duplicate_base': a},
                'targets': {'future_state': a + b},
            })
        return rows

    def test_every_candidate_including_unclustered_is_evaluated_against_full_baseline(self):
        report = build_full_baseline_orthogonality_v2(self.rows(), target='future_state', source_set=source_set('evidence'), policy=self.orth_policy())
        self.assertEqual([item['candidate'] for item in report['candidate_reports']], ['unclustered_noise', 'duplicate_base'])
        self.assertTrue(all(item['complete_baseline'] == ['base_a', 'base_b'] for item in report['candidate_reports']))
        duplicate = report['candidate_reports'][1]['incremental_information']['delta_r2_rank']
        self.assertLess(abs(duplicate), 0.01)
        self.assertFalse(report['claims']['strategy_pnl_read'])
        broken = self.rows()
        broken[0]['dependence_cluster'] = ''
        with self.assertRaises(FeatureV2Error):
            build_full_baseline_orthogonality_v2(broken, target='future_state', source_set=source_set('evidence'), policy=self.orth_policy())
        missing_value = self.rows()
        del missing_value[0]['features']['base_a']
        with self.assertRaises(FeatureV2Error):
            build_full_baseline_orthogonality_v2(missing_value, target='future_state', source_set=source_set('evidence'), policy=self.orth_policy())


class BtcInputV2Tests(unittest.TestCase):
    def btc_policy(self) -> dict:
        return build_btc_correlation_policy_v2({
            'policy_id': 'btc-fixture', 'frozen_at_utc': utc(BASE - SECOND), 'evidence_start_utc': utc(BASE),
            'lifecycle': 'FROZEN_FOR_NEW_EVIDENCE', 'freeze_evidence_sha256': FROZEN_HASH,
            'context_symbol': 'BTC_USDT', 'cadence_ns': 5 * 60 * SECOND, 'min_samples': 3,
            'panel_size': 2, 'high_positive_min': 0.65, 'low_absolute_max': 0.25, 'high_target': 1, 'low_target': 1,
        })

    def test_gap_creates_no_long_duration_return_and_as_of_is_deterministic(self):
        cadence = 5 * 60 * SECOND
        bars = {
            'BTC_USDT': [{'open_time_ns': BASE + i * cadence, 'close': 100 + i, 'closed': True} for i in range(5)],
            'ETH_USDT': [{'open_time_ns': BASE + i * cadence, 'close': 50 + i, 'closed': True} for i in (0, 1, 3, 4)],
        }
        sources = source_set('bars')
        policy = self.btc_policy()
        first = build_btc_correlation_input_v2(bars, source_set=sources, policy=policy, as_of_utc=utc(BASE + 6 * cadence))
        second = build_btc_correlation_input_v2(bars, source_set=sources, policy=policy, as_of_utc=utc(BASE + 6 * cadence))
        eth = first['correlations'][0]
        self.assertEqual(eth['valid_consecutive_pair_count'], 2)
        self.assertEqual(eth['dropped_nonconsecutive_common_pair_count'], 1)
        self.assertEqual(eth['status'], 'INSUFFICIENT')
        self.assertEqual(first, second)
        duplicate = {**bars, 'ETH_USDT': [*bars['ETH_USDT'], bars['ETH_USDT'][0]]}
        invalid = build_btc_correlation_input_v2(duplicate, source_set=sources, policy=policy, as_of_utc=utc(BASE + 6 * cadence))
        self.assertEqual(invalid['coverage_ledger']['ETH_USDT']['status'], 'INVALID')
        self.assertEqual(invalid['correlations'][0]['status'], 'INVALID')

    def test_panel_rejects_pnl_tainted_candidate(self):
        cadence = 5 * 60 * SECOND
        bars = {
            'BTC_USDT': [{'open_time_ns': BASE + i * cadence, 'close': 100 + i, 'closed': True} for i in range(5)],
            'ETH_USDT': [{'open_time_ns': BASE + i * cadence, 'close': 50 + 2 * i, 'closed': True} for i in range(5)],
        }
        sources = source_set('bars')
        policy = self.btc_policy()
        input_report = build_btc_correlation_input_v2(bars, source_set=sources, policy=policy, as_of_utc=utc(BASE + 6 * cadence))
        with self.assertRaises(FeatureV2Error):
            build_btc_correlation_panel_v2(input_report, candidates=[{'symbol': 'ETH_USDT', 'compatibility_rank': 1, 'strategy_pnl_used': True}], source_set=sources, policy=policy)


class PnlBarrierAndCliV2Tests(unittest.TestCase):
    def scan_and_discovery(self) -> tuple[dict, dict, dict]:
        sources = source_set()
        policy = feature_policy(start=BASE, end=BASE + 5 * SECOND, horizon=SECOND, sample=SECOND)
        scan = scan_market_state_v2(mature_events(BASE, BASE + 7 * SECOND), source_set=sources, capture_pair=capture(sources, end=BASE + 7 * SECOND), policy=policy, symbol='ETH_USDT', context_symbol='BTC_USDT')
        return sources, policy, build_state_discovery_v2(scan)

    def lineage(self, discovery: dict, policy: dict, pnl_sources: dict) -> dict:
        unsigned = {
            'schema': LINEAGE_SCHEMA,
            'analysis': 'caller_declared_frozen_state_hypothesis_trial_lineage',
            'state_hypothesis_id': 'hyp-1', 'state_hypothesis_sha256': '1' * 64,
            'state_discovery_sha256': discovery['state_discovery_sha256'], 'feature_policy_sha256': policy['policy_sha256'],
            'threshold_mapping_sha256': '2' * 64, 'trial_accounting_id': 'trial-1', 'trial_accounting_sha256': '3' * 64,
            'outcome_maturity_sha256': '4' * 64, 'frozen_effective_utc': utc(BASE), 'pnl_source_set': pnl_sources,
            'freeze_verification': 'CALLER_DECLARED_LOCAL_IDENTITY_ONLY', 'non_authority_claims': non_authority_claims(),
        }
        return {**unsigned, 'lineage_sha256': canonical_json_sha256(unsigned)}

    def test_pnl_is_waiting_without_lineage_and_descriptive_without_pf_ranking_when_bound(self):
        _sources, policy, discovery = self.scan_and_discovery()
        pnl_sources = source_set('pnl')
        waiting = build_pnl_stratification_v2(discovery, [], pnl_source_set=pnl_sources, feature_policy=policy)
        self.assertEqual(waiting['status'], 'WAITING_FOR_FROZEN_STATE_HYPOTHESIS')
        self.assertEqual(waiting['descriptive_rows'], [])
        rows = [
            {'condition_id': 'z-condition', 'arm': 'baseline', 'observed_at_utc': utc(BASE + SECOND), 'net_bps': -2.0, 'fee_bps_round_trip': 8.0, 'gate_identity': 'same-gate'},
            {'condition_id': 'z-condition', 'arm': 'conditioned', 'observed_at_utc': utc(BASE + SECOND), 'net_bps': 100.0, 'fee_bps_round_trip': 8.0, 'gate_identity': 'same-gate'},
            {'condition_id': 'a-condition', 'arm': 'baseline', 'observed_at_utc': utc(BASE + SECOND), 'net_bps': 3.0, 'fee_bps_round_trip': 8.0, 'gate_identity': 'same-gate'},
            {'condition_id': 'a-condition', 'arm': 'conditioned', 'observed_at_utc': utc(BASE + SECOND), 'net_bps': -100.0, 'fee_bps_round_trip': 8.0, 'gate_identity': 'same-gate'},
        ]
        report = build_pnl_stratification_v2(discovery, rows, pnl_source_set=pnl_sources, feature_policy=policy, lineage=self.lineage(discovery, policy, pnl_sources))
        self.assertEqual(report['status'], 'DESCRIPTIVE_NON_PROMOTING')
        self.assertFalse(report['claims']['profit_factor_ranking_present'])
        self.assertEqual([item['condition_id'] for item in report['descriptive_rows']], ['a-condition', 'a-condition', 'z-condition', 'z-condition'])
        self.assertEqual(report['canonical_state_order'], discovery['canonical_target_order'])
        changed_pnl = [dict(row, net_bps=-row['net_bps']) for row in rows]
        changed = build_pnl_stratification_v2(discovery, changed_pnl, pnl_source_set=pnl_sources, feature_policy=policy, lineage=self.lineage(discovery, policy, pnl_sources))
        self.assertEqual(changed['canonical_state_order'], report['canonical_state_order'])

    def test_module_cli_runs_real_scan_with_local_raw_identity_and_help_is_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = feature_policy(start=BASE, end=BASE + 3 * SECOND, horizon=SECOND, sample=SECOND)
            events = mature_events(BASE, BASE + 5 * SECOND)
            events_path = root / 'events.jsonl'
            events_path.write_text(''.join(json.dumps(row) + '\n' for row in events), encoding='utf-8')
            from orderflow_edge_lab.contracts_v2 import build_file_identity
            cli_sources = build_canonical_source_set([build_source_record('fixture-raw', build_file_identity(events_path, logical_name='fixture-raw'))])
            capture_path = root / 'capture.json'
            capture_path.write_text(json.dumps(capture(cli_sources, end=BASE + 5 * SECOND)), encoding='utf-8')
            policy_path = root / 'policy.json'
            policy_path.write_text(json.dumps(policy), encoding='utf-8')
            output = root / 'scan_v2.json'
            self.assertEqual(main(['scan', str(events_path), '--source-id', 'fixture-raw', '--policy', str(policy_path), '--capture-pair', str(capture_path), '--symbol', 'ETH_USDT', '--context-symbol', 'BTC_USDT', '--output', str(output)]), 0)
            payload = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(payload['schema'], 'orderflow_edge_lab.causal_market_state_scan.v2')
            with self.assertRaises(SystemExit) as exit_code:
                main(['--help'])
            self.assertEqual(exit_code.exception.code, 0)


if __name__ == '__main__':
    unittest.main()
