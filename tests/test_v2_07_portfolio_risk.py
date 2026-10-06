from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from orderflow_edge_lab.contracts_v2 import build_canonical_source_set
from orderflow_edge_lab.portfolio_risk_v2 import (
    PortfolioRiskV2Error,
    build_prop_firm_scenario_v2,
    build_prop_firm_terms_snapshot_v2,
    build_risk_overlay_v2,
    build_risk_policy_v2,
    build_self_financing_ledger_v2,
    build_stop_loss_reconciliation_v2,
    main,
)


SOURCE_SET = build_canonical_source_set([
    {'source_id': 'fixture-input', 'size_bytes': 7, 'sha256': 'a' * 64},
])


def qualified(*names: str) -> dict[str, object]:
    return {
        name: {
            'stage': f'fixture-{name}',
            'qualification': 'QUALIFIED',
            'source_set': SOURCE_SET,
            'identity_sha256': 'b' * 64,
        }
        for name in names
    }


def policy(kind: str, limits: dict[str, object]) -> dict[str, object]:
    return build_risk_policy_v2('fixture-policy-' + kind.lower(), kind, limits, activation_state='PROSPECTIVE_REPORT_ONLY')


def stop_execution(trade_id: str, price: float | None, age: float | None, status: str = 'OBSERVED') -> dict[str, object]:
    return {
        'trade_id': trade_id,
        'family': 'fixture-family',
        'direction': 'LONG',
        'quantity': 1.0,
        'entry_price': 100.0,
        'stop_price': 99.0,
        'entry_fee_cash': 0.1,
        'planned_exit_fee_cash': 0.1,
        'actual_exit_fee_cash': 0.1 if status == 'OBSERVED' else None,
        'exit_price': price,
        'exit_quote_age_ms': age,
        'exit_status': status,
        'exit_reason': 'STOP_TRIGGERED',
        'equity_before': 100.0,
        'depth_status': 'NOT_SUPPLIED',
        'risk_bucket': 'one-percent-fixture',
        'volatility_bucket': 'fixture-volatility',
        'liquidity_bucket': 'fixture-liquidity',
        'exposure_multiple': 1.0,
    }


class StopLossReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.policy = policy('STOP_LOSS_RECONCILIATION', {
            'max_exit_quote_age_ms': 1000.0,
            'ruin_equity_floor': 0.0,
            'unresolved_loss_fraction': 0.10,
        })

    def test_gap_through_stop_exceeds_planned_risk_and_no_gap_reconciles(self):
        result = build_stop_loss_reconciliation_v2(SOURCE_SET, self.policy, [
            stop_execution('gap', 95.0, 10.0),
            stop_execution('nogap', 99.0, 10.0),
        ], qualified_inputs=qualified('price', 'execution'))
        rows = {row['trade_id']: row for row in result['payload']['ledger']}
        self.assertGreater(rows['gap']['realized_loss_fraction'], rows['gap']['planned_stop_risk_fraction'])
        self.assertGreater(rows['gap']['actual_executable_bbo_gap_bps'], 0.0)
        self.assertTrue(rows['gap']['realized_loss_exceeded_planned_risk'])
        self.assertAlmostEqual(rows['nogap']['realized_loss_fraction'], rows['nogap']['planned_stop_risk_fraction'])
        self.assertEqual(result['payload']['summary']['ledger_tail_loss_reconciliation'], result['payload']['summary']['conservative_tail_loss_fraction_sum'])
        self.assertEqual(result['payload']['summary']['groups'][0]['exposure_multiple'], 1.0)

    def test_stale_and_missing_exit_are_unresolved_not_stop_fills(self):
        result = build_stop_loss_reconciliation_v2(SOURCE_SET, self.policy, [
            stop_execution('stale', 95.0, 1001.0),
            stop_execution('missing', None, None, 'MISSING'),
        ], qualified_inputs=qualified('price', 'execution'))
        rows = {row['trade_id']: row for row in result['payload']['ledger']}
        self.assertEqual(rows['stale']['resolution'], 'UNRESOLVED_STALE_EXIT')
        self.assertIsNone(rows['stale']['realized_loss_fraction'])
        self.assertEqual(rows['missing']['resolution'], 'UNRESOLVED_MISSING_EXIT')
        self.assertIsNone(rows['missing']['realized_loss_fraction'])
        self.assertEqual(result['analysis_status'], 'RECONCILED_WITH_UNRESOLVED_EXITS')


class SelfFinancingLedgerTests(unittest.TestCase):
    def test_two_asset_two_interval_hand_worked_ledger_reconciles_and_reports_mark_excursion(self):
        result = build_self_financing_ledger_v2(
            SOURCE_SET,
            policy('SELF_FINANCING_LEDGER', {
                'max_post_trade_gross': 1.0,
                'turnover_cost_rate': 0.01,
                'accounting_tolerance': 1e-10,
            }),
            {'equity': 100.0, 'cash': 100.0, 'positions': {}},
            [
                {
                    'interval_id': 'one',
                    'target_weights': {'A': 0.5, 'B': 0.5},
                    'asset_returns': {'A': 1.0, 'B': 0.0},
                    'funding_cash': {'A': -1.0, 'B': 0.0},
                },
                {
                    'interval_id': 'two',
                    'target_weights': {'A': 0.5, 'B': 0.5},
                    'asset_returns': {'A': -0.5, 'B': 0.0},
                    'funding_cash': {'A': 0.0, 'B': 0.0},
                },
            ],
            qualified_inputs=qualified('price', 'funding', 'execution'),
        )
        first, second = result['payload']['ledger']
        self.assertAlmostEqual(first['equity_end'], 148.0)
        self.assertAlmostEqual(second['turnover_notional'], 50.0)
        self.assertAlmostEqual(second['equity_end'], 110.5)
        self.assertAlmostEqual(second['equity_reconciliation_residual'], 0.0)
        self.assertGreater(second['post_mark_gross'], 1.0)
        self.assertAlmostEqual(result['payload']['summary']['equity_change_reconciliation_residual'], 0.0)

    def test_missing_funding_zero_is_rejected_instead_of_zero_filled(self):
        with self.assertRaisesRegex(PortfolioRiskV2Error, 'explicitly cover'):
            build_self_financing_ledger_v2(
                SOURCE_SET,
                policy('SELF_FINANCING_LEDGER', {'max_post_trade_gross': 1.0, 'turnover_cost_rate': 0.0, 'accounting_tolerance': 1e-10}),
                {'equity': 100.0, 'cash': 100.0, 'positions': {}},
                [{'interval_id': 'bad', 'target_weights': {'A': 1.0}, 'asset_returns': {'A': 0.0}, 'funding_cash': {}}],
                qualified_inputs=qualified('price', 'funding', 'execution'),
            )

    def test_target_above_declared_post_trade_gross_cap_fails_closed(self):
        with self.assertRaisesRegex(PortfolioRiskV2Error, 'gross cap'):
            build_self_financing_ledger_v2(
                SOURCE_SET,
                policy('SELF_FINANCING_LEDGER', {'max_post_trade_gross': 1.0, 'turnover_cost_rate': 0.0, 'accounting_tolerance': 1e-10}),
                {'equity': 100.0, 'cash': 100.0, 'positions': {}},
                [{'interval_id': 'too-gross', 'target_weights': {'A': 1.0, 'B': 0.5}, 'asset_returns': {'A': 0.0, 'B': 0.0}, 'funding_cash': {'A': 0.0, 'B': 0.0}}],
                qualified_inputs=qualified('price', 'funding', 'execution'),
            )


def overlay_limits(shrinkage: float = 0.2) -> dict[str, object]:
    return {
        'covariance_min_observations': 4,
        'covariance_shrinkage': shrinkage,
        'max_condition_number': 1000.0,
        'max_gross': 1.0,
        'max_abs_net': 1.0,
        'max_name_abs': 1.0,
        'max_abs_factor_exposure': {'BTC_BETA': 0.9},
        'max_tag_gross': {'fixture-tag': 1.0},
        'max_covariance_contribution': 0.5,
        'min_effective_n': 2.5,
        'max_expected_shortfall': 1.0,
        'expected_shortfall_tail_fraction': 0.5,
        'max_stress_loss': 1.0,
        'target_annual_vol': 0.20,
        'max_leverage': 3.0,
        'max_scaled_gross': 0.8,
        'max_tail_loss': 0.10,
        'max_drawdown': 0.30,
        'max_volatility_jump': 2.0,
        'turnover_cost_rate': 0.001,
        'accounting_tolerance': 1e-10,
    }


def risk_model(future: float = 0.99, status: str = 'OBSERVED') -> dict[str, object]:
    rows = [
        ('2026-01-01T00:00:00Z', 0.01),
        ('2026-01-02T00:00:00Z', -0.01),
        ('2026-01-03T00:00:00Z', 0.015),
        ('2026-01-04T00:00:00Z', -0.015),
        ('2026-01-05T00:00:00Z', 0.005),
        ('2026-01-07T00:00:00Z', future),
    ]
    return {
        'status': status,
        'decision_time_utc': '2026-01-06T00:00:00Z',
        'input_basis': 'CALLER_DECLARED_PNL_INDEPENDENT',
        'returns': [{'timestamp_utc': stamp, 'returns': {'A': value, 'B': value, 'C': value}} for stamp, value in rows],
        'factor_loadings': {'A': {'BTC_BETA': 1.0}, 'B': {'BTC_BETA': 1.0}, 'C': {'BTC_BETA': 1.0}},
        'asset_tags': {'A': ['fixture-tag'], 'B': ['fixture-tag'], 'C': ['fixture-tag']},
        'stress_scenarios': {'correlated-down': {'A': -0.10, 'B': -0.10, 'C': -0.10}},
    }


def envelope(status: str = 'OBSERVED') -> dict[str, object]:
    return {
        'status': status,
        'decision_time_utc': '2026-01-06T00:00:00Z',
        'realized_vol_annual': 0.10,
        'current_gross': 1.0,
        'tail_loss_estimate': 0.05,
        'recent_drawdown': 0.05,
        'volatility_jump': 1.0,
        'prior_scale': 1.0,
    }


class RiskOverlayTests(unittest.TestCase):
    def build(self, model: dict[str, object], limits: dict[str, object] | None = None):
        return build_risk_overlay_v2(
            SOURCE_SET,
            policy('PORTFOLIO_RISK_OVERLAY', limits or overlay_limits()),
            {'A': 0.8, 'B': 0.1, 'C': 0.1},
            model,
            envelope(),
            qualified_inputs=qualified('risk_panel', 'metadata', 'portfolio_accounting'),
        )

    def test_prior_only_correlated_overlay_increases_effective_bets_and_future_row_cannot_change_target(self):
        first = self.build(risk_model(0.99))
        second = self.build(risk_model(-0.99))
        cov = first['payload']['covariance_overlay']
        self.assertEqual(cov['state'], 'COVARIANCE_CONSTRAINED_REPORT_ONLY')
        self.assertEqual(cov['proposed_covariance_targets'], second['payload']['covariance_overlay']['proposed_covariance_targets'])
        self.assertEqual(cov['covariance_diagnostics']['future_observations_excluded'], 1)
        self.assertGreater(cov['covariance_diagnostics']['effective_n'], 1.5)
        self.assertLess(cov['covariance_diagnostics']['max_covariance_contribution'], 0.5)
        tail = first['payload']['gross_tail_envelope']
        self.assertLessEqual(tail['scaled_gross'], 0.8)
        self.assertIn('MAX_SCALED_GROSS', tail['constraint_bindings'])

    def test_missing_or_ill_conditioned_covariance_fails_closed_to_cash(self):
        result = self.build(risk_model(status='MISSING'))
        self.assertEqual(result['analysis_status'], 'NO_NEW_RISK_CASH')
        self.assertEqual(result['payload']['gross_tail_envelope']['proposed_risk_scale'], 0.0)
        ill = self.build(risk_model(), overlay_limits(shrinkage=0.0))
        self.assertEqual(ill['analysis_status'], 'NO_NEW_RISK_CASH')


PROP_FIELDS = {
    'daily_loss_limit_cash': {'status': 'VERIFIED', 'value': 5.0},
    'max_loss_limit_cash': {'status': 'VERIFIED', 'value': 10.0},
    'daily_loss_basis': {'status': 'VERIFIED', 'value': 'SESSION_START_EQUITY'},
    'max_loss_type': {'status': 'VERIFIED', 'value': 'STATIC'},
    'trailing_loss_update_timing': {'status': 'VERIFIED', 'value': 'INTRADAY'},
    'timezone_reset_convention': {'status': 'VERIFIED', 'value': 'UTC caller-declared'},
    'equity_balance_basis': {'status': 'VERIFIED', 'value': 'EQUITY'},
    'payout_eligibility': {'status': 'VERIFIED', 'value': 'caller-declared'},
    'maximum_payout': {'status': 'VERIFIED', 'value': 'caller-declared'},
    'prohibited_period_assumptions': {'status': 'VERIFIED', 'value': 'caller-declared'},
}


def prop_policy() -> dict[str, object]:
    return policy('PROP_FIRM_SCENARIO', {
        'block_length_days': 2,
        'bootstrap_replicates': 20,
        'bootstrap_seed': 7,
        'confidence_level': 0.90,
        'accounting_tolerance': 1e-10,
    })


def career(career_id: str, path_mode: str) -> dict[str, object]:
    return {
        'career_id': career_id,
        'scenario_id': 'intraday-recovery-fixture',
        'path_mode': path_mode,
        'event_ledger': [
            {'event_id': career_id + '-open', 'timestamp_utc': '2026-02-01T09:00:00Z', 'session_id': '2026-02-01', 'event_type': 'MARK', 'equity_before': 100.0, 'trading_pnl_cash': 0.0, 'cash_flow_cash': 0.0, 'equity_after': 100.0},
            {'event_id': career_id + '-low', 'timestamp_utc': '2026-02-01T12:00:00Z', 'session_id': '2026-02-01', 'event_type': 'MARK', 'equity_before': 100.0, 'trading_pnl_cash': -6.0, 'cash_flow_cash': 0.0, 'equity_after': 94.0},
            {'event_id': career_id + '-close', 'timestamp_utc': '2026-02-02T00:00:00Z', 'session_id': '2026-02-01', 'event_type': 'MARK', 'equity_before': 94.0, 'trading_pnl_cash': 6.0, 'cash_flow_cash': 0.0, 'equity_after': 100.0},
        ],
    }


class PropScenarioTests(unittest.TestCase):
    def terms(self, fields: dict[str, object] | None = None):
        return build_prop_firm_terms_snapshot_v2(
            'fixture-firm', 'VERIFIED', '2026-01-01T00:00:00Z', 'caller-supplied-snapshot', fields or PROP_FIELDS, list(PROP_FIELDS),
        )

    def test_intraday_recovery_is_breach_daily_only_is_never_a_pass_and_overlap_reduces_effective_n(self):
        result = build_prop_firm_scenario_v2(
            SOURCE_SET, prop_policy(), self.terms(), [career('one', 'INTRADAY_OBSERVED'), career('two', 'DAILY_CLOSE_ONLY')],
            qualified_inputs=qualified('firm_terms', 'portfolio_path'),
        )
        rows = {row['career_id']: row for row in result['payload']['career_ledger']}
        self.assertEqual(rows['one']['breach_status'], 'OBSERVED_INTRADAY_BREACH')
        self.assertEqual(rows['two']['breach_status'], 'UNQUALIFIED_DAILY_ONLY')
        self.assertLess(result['payload']['dependence_aware_uncertainty']['effective_sample_size_overlap_adjusted'], 2.0)
        self.assertEqual(rows['one']['terminal_reconciliation_residual'], 0.0)

    def test_unknown_material_terms_block_qualified_scenario_ranking(self):
        fields = {name: dict(value) for name, value in PROP_FIELDS.items()}
        fields['payout_eligibility'] = {'status': 'UNKNOWN', 'value': None}
        result = build_prop_firm_scenario_v2(
            SOURCE_SET, prop_policy(), self.terms(fields), [career('one', 'CONSERVATIVE_SCENARIO')],
            qualified_inputs=qualified('firm_terms', 'portfolio_path'),
        )
        self.assertEqual(result['analysis_status'], 'BLOCKED_UNKNOWN_MATERIAL_TERMS')
        self.assertFalse(result['payload']['qualified_scenario_ranking'])
        self.assertIn('payout_eligibility', result['payload']['unknown_material_terms'])


class PortfolioRiskV2CliTests(unittest.TestCase):
    def test_stop_cli_is_wired_to_the_successor_builder_and_writes_new_output(self):
        request = {
            'source_set': SOURCE_SET,
            'policy': policy('STOP_LOSS_RECONCILIATION', {'max_exit_quote_age_ms': 1.0, 'ruin_equity_floor': 0.0, 'unresolved_loss_fraction': 0.1}),
            'executions': [stop_execution('cli', 95.0, 0.0)],
            'qualified_inputs': qualified('price', 'execution'),
        }
        with tempfile.TemporaryDirectory() as root:
            inp = Path(root) / 'request.json'
            out = Path(root) / 'stop_report_v2.json'
            inp.write_text(json.dumps(request), encoding='utf-8')
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(['stop', '--input', str(inp), '--output', str(out)])
            self.assertEqual(code, 0, stderr.getvalue())
            self.assertTrue(out.is_file())
            written = json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(written['analysis'], 'stop_loss_reconciliation_v2')
            self.assertIn('output', json.loads(stdout.getvalue()))


if __name__ == '__main__':
    unittest.main()
