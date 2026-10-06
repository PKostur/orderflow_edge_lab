# Process v2: portfolio risk successors

## Scope and boundary

`orderflow_edge_lab.portfolio_risk_v2` is an **additive offline reporting and model module**. It does not modify a v1 study, frozen configuration, research result, watch, signal, sizing rule, live path, or account. It accepts caller-supplied JSON only and has no collector, network, schedule, credential, purchase, broker, exchange, paper-trading, or order capability.

Each output carries the shared all-false `non_authority_claims` and an `analysis_sha256`. A local source identity or a caller declaration is not durable-storage verification, provider-completeness verification, external firm-term verification, execution calibration, profitability evidence, promotion authority, or live-trading permission.

## Implemented finding mapping

| Finding | Executable successor | Key behavior |
|---|---|---|
| 07-portfolio-risk-F1 | `build_stop_loss_reconciliation_v2` | Separates planned technical-stop loss from fresh observed executable-BBO loss, actual stop-to-BBO gap, overshoot, stale and missing exits, and caller-declared conservative unresolved loss. |
| 07-portfolio-risk-F2 | `build_self_financing_ledger_v2` | Carries marked positions, cash, equity, target notionals, turnover, cost, funding, gross, and exact interval/terminal reconciliation. |
| 07-portfolio-risk-F3 | `build_risk_overlay_v2` | Uses only returns with timestamps strictly before the decision time, applies caller-declared shrinkage/covariance/factor/tag/ES/stress constraints, and fails closed to cash. |
| 07-portfolio-risk-F4 | `build_risk_overlay_v2` | Produces a report-only scale constrained by caller-declared target volatility, leverage, scaled gross, tail loss, drawdown, and volatility-jump conditions. |
| 07-portfolio-risk-F5 | `build_prop_firm_terms_snapshot_v2` and `build_prop_firm_scenario_v2` | Hashes per-field verified/assumed/unknown term states, checks intraday or declared conservative paths, reconciles career event ledgers, and reports overlap-adjusted effective N, non-overlap sensitivity, and deterministic block-bootstrap uncertainty. |

## Common caller contract

All principal builders take a canonical shared-contract `source_set`, a hash-bound policy, and stage-qualified inputs. The qualification object has one entry per required upstream input:

```json
{
  `price`: {
    `stage`: `caller-declared-stage`,
    `qualification`: `QUALIFIED`,
    `source_set`: { ... exact same canonical source set ... },
    `identity_sha256`: `64 hexadecimal characters`
  }
}
```

The expected names are:

| Builder | Required qualified input names |
|---|---|
| Stop reconciliation | `price`, `execution` |
| Self-financing ledger | `price`, `funding`, `execution` |
| Risk overlay | `risk_panel`, `metadata`, `portfolio_accounting` |
| Prop scenario | `firm_terms`, `portfolio_path` |

The qualification is a strict local interface gate. It does **not** upgrade an upstream stage or an external source to verified authority. Stage 03 and Stage 05 integration must create compatible identity records/source sets; until then a caller cannot manufacture a qualified output with a mismatched source set.

## Caller-declared frozen policy

Use `build_risk_policy_v2(policy_id, policy_kind, limits, activation_state=...)` or the `policy` CLI command. It hashes caller-supplied bytes and allows only `INERT_TEMPLATE` or `PROSPECTIVE_REPORT_ONLY`. The helper never selects limits, risk appetite, model thresholds, or an active policy.

A policy must be exactly hash-bound and `FROZEN` before it can be used. Required limit keys are intentionally exhaustive so a missing setting cannot silently become a working default.

| Policy kind | Required `limits` keys |
|---|---|
| `STOP_LOSS_RECONCILIATION` | `max_exit_quote_age_ms`, `ruin_equity_floor`, `unresolved_loss_fraction` |
| `SELF_FINANCING_LEDGER` | `max_post_trade_gross`, `turnover_cost_rate`, `accounting_tolerance` |
| `PORTFOLIO_RISK_OVERLAY` | `covariance_min_observations`, `covariance_shrinkage`, `max_condition_number`, `max_gross`, `max_abs_net`, `max_name_abs`, `max_abs_factor_exposure`, `max_tag_gross`, `max_covariance_contribution`, `min_effective_n`, `max_expected_shortfall`, `expected_shortfall_tail_fraction`, `max_stress_loss`, `target_annual_vol`, `max_leverage`, `max_scaled_gross`, `max_tail_loss`, `max_drawdown`, `max_volatility_jump`, `turnover_cost_rate`, `accounting_tolerance` |
| `PROP_FIRM_SCENARIO` | `block_length_days`, `bootstrap_replicates`, `bootstrap_seed`, `confidence_level`, `accounting_tolerance` |

These are **inert templates**, not activated limits. A future operator must separately approve and freeze a prospective policy before later relevant evidence is viewed. No output applies a policy to v1 results.

## F1: stop loss reconciliation

An execution row includes quantity, entry/stop price, planned and actual fee cash, executable exit price, exit quote age, observed/missing exit state, equity before the stop loss, family/direction, and a depth status. For a fresh observed exit:

```text
planned loss = quantity x absolute(entry - stop) + planned entry fee + planned exit fee
realized loss = max(0, quantity x adverse(entry - executable BBO) + actual entry fee + actual exit fee)
actual BBO gap = max(0, adverse(stop - executable BBO) / stop x 10000)
```

The model reports `planned_stop_risk_fraction` separately from `realized_loss_fraction`. A stale or missing exit has `realized_loss_fraction: null`; it is labelled unresolved and receives only the caller-declared conservative scenario loss. `NOT_SUPPLIED` depth is recorded as such and never treated as observed depth.

## F2: self-financing ledger

Initial book identity is `equity = cash + sum(signed marked positions)`. At each interval, target notionals are current equity times caller target weights; turnover is measured against **marked pre-trade positions**. The model charges the declared turnover rate, applies caller-provided signed funding cash, marks target positions through supplied returns, and checks:

```text
ending equity - starting equity = price PnL + funding PnL - trading cost
```

Funding for every nonzero target must be explicit, including observed zero. Missing funding is rejected rather than zero-filled. A target above the caller-declared post-trade gross cap fails closed before a ledger is emitted; post-mark gross excursions from supplied returns are retained as diagnostics rather than hidden.

## F3 and F4: covariance and gross-tail overlay

The risk panel declares `CALLER_DECLARED_PNL_INDEPENDENT`; that claim is preserved as a declaration and is not externally verified. Only rows strictly before `decision_time_utc` enter covariance. Rows on/after that time are counted as excluded future data, so changing future rows cannot change the earlier decision. Missing asset, factor, tag, or stress coverage fails closed to `NO_NEW_RISK_CASH`.

The covariance projection retains the caller raw target's active signed name set but redistributes risk budget by inverse volatility to reduce concentration; it may retain a cash residual. It serializes condition number, prior observation count, factor exposure, tags, effective N, covariance contributions, expected shortfall, stress losses, raw-to-final targets, and every binding constraint. Poor conditioning, inadequate coverage, infeasible concentration, or a missing model never returns an unconstrained or leveraged target.

The envelope reports a proposed scale only. It is constrained by the minimum of volatility target, leverage, scaled-gross, and tail-loss scales; caller drawdown or volatility-jump gates return zero new risk. Scale-change cost is computed from declared current gross, prior scale, and cost rate. It remains a model report and does not rebalance a portfolio.

## F5: prop-firm scenario model

Build a term snapshot with every material field marked `VERIFIED`, `ASSUMED`, or `UNKNOWN`. Unknown fields have no invented values. A source snapshot reference and its status are hash-bound, but the module labels status as caller-declared rather than an external verification fact.

`build_prop_firm_scenario_v2` recognizes these material rule values when they are available:

- `daily_loss_limit_cash`
- `max_loss_limit_cash`
- `daily_loss_basis`
- `max_loss_type`
- `trailing_loss_update_timing`
- `timezone_reset_convention`
- `equity_balance_basis`
- `payout_eligibility`
- `maximum_payout`
- `prohibited_period_assumptions`

Each career has a reconciled chronological event ledger. A row obeys:

```text
 equity_after = equity_before + trading_pnl_cash + cash_flow_cash
```

Fees, payouts, withdrawals, terminal equity, and breaches are reported from that ledger. `INTRADAY_OBSERVED` checks the actual supplied path. `CONSERVATIVE_SCENARIO` is evaluated but labelled as scenario rather than observed. `DAILY_CLOSE_ONLY` is **never a pass**: it is `UNQUALIFIED_DAILY_ONLY` even if the daily-close value recovers.

Careers sharing dates do not receive independent-count precision. The report emits calendar coverage, overlap-adjusted effective sample size, a greedy non-overlap sensitivity, and deterministic block-bootstrap breach-rate interval. Unknown material terms or unknown required loss rules produce `BLOCKED_UNKNOWN_MATERIAL_TERMS`; assumed material terms remain conditional and cannot produce a qualified ranking. Even caller-declared verified terms only produce a scenario-only status, never a recommendation, purchase, or account action.

## Offline CLI

The module is directly executable now:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m orderflow_edge_lab.portfolio_risk_v2 --help
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m orderflow_edge_lab.portfolio_risk_v2 policy --input policy_request.json --output policy_v2.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m orderflow_edge_lab.portfolio_risk_v2 stop --input stop_request.json --output stop_report_v2.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m orderflow_edge_lab.portfolio_risk_v2 ledger --input ledger_request.json --output human_ledger_v2.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m orderflow_edge_lab.portfolio_risk_v2 overlay --input overlay_request.json --output risk_overlay_v2.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m orderflow_edge_lab.portfolio_risk_v2 prop --input prop_request.json --output prop_scenario_v2.json
```

Each command consumes one local JSON request and writes only its caller-specified new output. It never reads repository research outputs by default. Stage 10/integration must register these commands in any package dispatcher/CI command registry and add cross-stage fixtures; this workstream does not edit global packaging, CI, or the dispatcher.

## Activation blockers

The code is complete as an offline successor model, but activation is blocked by external and governance prerequisites:

1. A separately frozen prospective risk policy with justified limits, covariance panel provenance, factor/tag metadata, and stress basis.
2. Qualified stage 03/05 price, execution, funding, and accounting identities bound to exact source sets.
3. Durable external storage/retention and retrieval/rehearsal evidence. Local source hashes are insufficient.
4. Provider completeness/authenticity and executable BBO, staleness, depth, funding, and mark coverage evidence.
5. Independent execution/fill/impact and risk-engine calibration evidence.
6. A time-stamped firm-term source snapshot and rule-field verification; unknown material terms must remain ranking blockers.
7. Intraday portfolio paths or separately frozen conservative excursions for prop scenarios, plus a prospective governance decision. No challenge purchase or live account action is authorized.

None of these blockers has a fake working default in this module.
