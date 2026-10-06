import unittest

from orderflow_edge_lab.paper_signal_controls_v3 import (
    PaperSignalControlError, make_midpoint_momentum_control,
)
from orderflow_edge_lab.paper_bot_v3 import POLICY_SCHEMA, run_paper_bot_v3


class PaperSignalControlTests(unittest.TestCase):
    def frames(self):
        return [{'ts_ns': (i + 1) * 3600_000_000_000, 'received_ns': (i + 1) * 3600_000_000_000,
                 'symbol': 'SYNTH-USD', 'bid': 99 + i, 'ask': 101 + i,
                 'close': 100000 - i, 'source_id': 'synthetic-test', 'batch_id': 'test'} for i in range(5)]

    def control(self, **overrides):
        return make_midpoint_momentum_control(**{'lookback_quotes': 2, 'cadence_ns': 3600_000_000_000,
                                               'target_fraction': 0.1, **overrides})

    def test_quote_causal_warmup_and_ignores_future_close(self):
        frames = self.frames()
        control = self.control()
        self.assertEqual(control(frames[:2]), 0)
        self.assertEqual(control(frames[:3]), 0.1)
        frames[-1]['bid'] = frames[-1]['ask'] = 0.01
        self.assertEqual(control(frames[:3]), 0.1)
        self.assertEqual(control(frames), -0.1)

    def test_missing_cadence_and_bad_inputs_fail_closed(self):
        frames = self.frames()
        with self.assertRaises(PaperSignalControlError):
            self.control()(frames[::2])
        frames[0]['bid'] = True
        with self.assertRaises(PaperSignalControlError):
            self.control()(frames[:3])
        for overrides in ({'lookback_quotes': True}, {'cadence_ns': 0}, {'target_fraction': float('nan')},
                          {'target_fraction': 0}, {'tolerance_ns': -1}):
            with self.assertRaises(PaperSignalControlError):
                self.control(**overrides)

    def test_stable_specification_and_parameter_binding(self):
        self.assertEqual(self.control().signal_id, self.control().signal_id)
        self.assertNotEqual(self.control().signal_id, self.control(lookback_quotes=3).signal_id)
        self.assertFalse(self.control().specification['profitable_edge_established'])

    def test_paper_engine_fills_only_after_control_decision(self):
        control = self.control()
        policy = {'schema': POLICY_SCHEMA, 'signal_id': control.signal_id,
                  'instrument': {'symbol': 'SYNTH-USD', 'contract_multiplier': 1,
                                 'instrument_type': 'synthetic_linear', 'funding_treatment': 'not_modeled'},
                  'initial_cash': 10000, 'fee_rate': 0.0005, 'slippage_bps': 2,
                  'max_quote_age_ns': 1000000, 'max_position_fraction': 0.2,
                  'max_gross_exposure_fraction': 0.2, 'max_loss_fraction': 0.1, 'max_drawdown_fraction': 0.1}
        artifact = run_paper_bot_v3(self.frames(), control, policy, synthetic_demo=True)
        events = artifact['event_chain']
        self.assertFalse(any(e.get('execution', {}).get('executed', False) if e.get('execution') else False for e in events[:3]))
        self.assertTrue(events[3]['execution']['executed'])
        self.assertGreater(artifact['summary']['fees_paid'], 0)
        self.assertEqual(artifact['status'], 'COMPLETE')


if __name__ == '__main__':
    unittest.main()
