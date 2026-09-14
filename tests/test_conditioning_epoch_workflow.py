from pathlib import Path


def test_continuous_discovery_persists_and_reuses_one_conditioning_epoch() -> None:
    workflow = Path('.github/workflows/orderflow-continuous-discovery.yml').read_text(encoding='utf-8')

    assert 'Recover newest structurally valid cumulative discovery ledger' in workflow
    assert 'Recover canonical conditioning epoch if present' in workflow
    assert "reuse=true" in workflow
    assert "reuse=false" in workflow
    assert "strategy_conditioning_registry_binding_v1.json state_threshold_freeze_v1.json strategy_state_mapping_v1.json" in workflow
    assert 'Aggregate conditioned results only within the canonical conditioning epoch' in workflow
    assert 'CURRENT_MANIFEST=' in workflow
    assert 'MANIFEST" != "$CURRENT_MANIFEST' in workflow
    assert "mixed_conditioning_epochs_pooled': False" in workflow


def test_conditioning_epoch_reuse_prevents_refreeze_on_later_trials() -> None:
    workflow = Path('.github/workflows/orderflow-continuous-discovery.yml').read_text(encoding='utf-8')

    guarded_steps = [
        'Bind conditioning freeze to deterministic state candidate before strategy PnL',
        'Freeze PnL-independent market-state thresholds before strategy PnL',
        'Freeze PnL-independent strategy-state bucket mapping before strategy PnL',
    ]
    for step_name in guarded_steps:
        index = workflow.index(f'- name: {step_name}')
        following = workflow[index:index + 700]
        assert "if: steps.conditioning_epoch.outputs.reuse != 'true'" in following


def test_failed_downstream_run_can_supply_next_structurally_valid_ledger() -> None:
    workflow = Path('.github/workflows/orderflow-continuous-discovery.yml').read_text(encoding='utf-8')

    recovery_start = workflow.index('- name: Recover newest structurally valid cumulative discovery ledger')
    recovery_end = workflow.index('- name: Aggregate market-state evidence', recovery_start)
    recovery = workflow[recovery_start:recovery_end]

    assert "actions/runs/${RUN_ID}" not in recovery
    assert "find \"$PRIOR_HISTORY\" -type f -name market_state.json" in recovery
