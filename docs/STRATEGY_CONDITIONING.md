# Strategy conditioning protocol

`strategy-conditioning-v1` is a fail-closed boundary between market-state research and strategy-PnL conditioning.

It exists to prevent a state feature from being selected because it happened to improve historical strategy returns. A feature can enter this stage only after the frozen `regime-research-v1.1` forward screen has matured and independently qualified the feature as predictive of a future market-state target.

## Required sequence

```text
regime-research-v1 scan
    -> regime-research-v1.1 forward cross-batch screen
    -> PnL-independent redundancy representative
    -> strategy-conditioning-v1 freeze
    -> baseline versus conditioned strategy comparison
    -> trial accounting
    -> later candidate freeze / holdout / untouched OOS path
```

The conditioning freeze does not run a strategy backtest and does not claim profitability. It binds the exact state-screen artifact and selected state hypothesis before later conditioned strategy PnL is inspected.

## Eligibility

The freeze requires:

* a `regime_research_v1_1_market_state_screen` artifact with status `screen_ready`;
* at least five qualifying independent forward capture batches;
* a state association marked `v1_1_eligible_state_association=true`;
* dominant-sign consistency of at least 80 percent;
* median absolute Spearman of at least 0.10;
* `strategy_pnl_used=false` in the upstream state screen;
* the selected feature to be the PnL-independent representative of any highly redundant feature cluster.

`strategy-conditioning-v1` permits one feature only. A second feature requires a separately versioned protocol frozen before later evidence is inspected. This prevents incremental feature selection from drifting after PnL is visible.

## Trial invariants

The later comparison must keep the frozen `discovery-v1` trading logic unchanged except for the single state condition. Baseline and conditioned arms must use the same capture batches, horizons, direction logic, fees, spread, slippage, latency and staleness assumptions.

State thresholds or bucket mappings must be frozen before conditioned strategy PnL is inspected and may be derived only from market-state evidence. They may not be optimized on strategy returns.

Stop-based MAE/MFE work and original-versus-reversed controls remain required. Cross-pair transfer must use unchanged feature definitions and a PnL-independent universe. Transfer evidence is not untouched OOS validation.

## Create a conditioning freeze

Once a future v1.1 state screen has matured:

```bash
orderflow-strategy-conditioning-freeze \
  --state-screen artifacts/orderflow/market_state_aggregate_v1_1.json \
  --research-family liquidity_microstructure \
  --feature spread_bps \
  --target future_spread_bps_5s \
  --output research/strategy_conditioning_freeze.json
```

The feature and target above are illustrative only. The command will reject them unless the actual upstream state-screen artifact qualifies that exact association.

The resulting manifest contains SHA-256 bindings for both the conditioning protocol and the upstream state-screen artifact. It remains research-only and cannot authorize live transmission.
