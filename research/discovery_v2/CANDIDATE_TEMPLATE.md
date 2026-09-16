# Discovery v2 Candidate Record

## Identity

- candidate_id:
- family:
- version:
- state: IDEA
- created_utc:
- frozen_utc:
- hypothesis_source: paper | github | tradingview | discretionary | ml_search | structural | other
- trial_ledger_id:

## Economic mechanism

What economic or market-structure mechanism should create the return?

## Immutable rule

### Inputs available at decision time

### Entry / target-position rule

### Exit / rebalance rule

### Execution assumption

### Parameters and permitted pre-freeze ranges

## Benchmark

What simple exposure could explain the apparent result?

- benchmark_id:
- benchmark construction:
- beta/neutrality expectation:

## Expected failure conditions

State before seeing the result.

## Dataset manifest

- dataset_id:
- independence_level: D0
- data visible during hypothesis formation: yes/no
- source:
- venue:
- market type:
- symbols:
- start/end:
- raw hash:
- cleaning hash:
- timestamp boundary:

## Trial accounting

- total variants attempted in family:
- total parameter combinations:
- total symbols inspected:
- total timeframes inspected:
- total cost cases inspected:
- unsuccessful siblings retained: yes/no

## Engine 1 — discovery

- engine:
- implementation commit:
- gross expectancy:
- net expectancy:
- Sharpe:
- max drawdown:
- turnover:
- break-even friction:
- benchmark-relative result:
- reversed/null result:

## Bias audits

- lookahead audit: pass/fail/not-applicable
- recursive/initialization audit: pass/fail/not-applicable
- timestamp audit: pass/fail
- survivorship/universe audit: pass/fail/not-applicable
- funding/borrow chronology audit: pass/fail/not-applicable

## Engine 2 — independent replication

- engine:
- independently implemented: yes/no
- shared signal code: must be no
- implementation commit:
- signal timestamp agreement:
- position agreement:
- trade-count difference:
- turnover difference:
- gross-return difference:
- net-return difference:
- unexplained discrepancy: yes/no

## Statistical robustness

- sample count:
- block-bootstrap mean CI:
- block-bootstrap median CI:
- Deflated Sharpe Ratio:
- PBO/CSCV:
- family-level Reality Check / equivalent:
- positive-period fraction:
- positive-symbol fraction:
- parameter-neighborhood stability:

## Concentration

- best-symbol PnL share:
- best-period PnL share:
- top-five-trade/period PnL share:
- contribution HHI:
- result excluding best symbol:
- result excluding best period:

## Execution stress

| Scenario | Net result | Max DD | Notes |
|---|---:|---:|---|
| baseline cost | | | |
| 1.5x cost | | | |
| 2.0x cost | | | |
| +1 decision event delay | | | |
| partial/missed fill stress | | | |

- estimated capacity:
- liquidation/margin feasibility:

## Regime decomposition

- trend:
- range:
- high volatility:
- low volatility:
- high spread / low liquidity:
- low spread / high liquidity:
- market beta regime:
- funding regime:
- long side:
- short side:

## Locked validation

- validation dataset id:
- independence level:
- rule unchanged: yes/no
- validation net result:
- benchmark-relative validation:
- validation max DD:
- validation failure reason if any:

## Prospective shadow

- evidence start UTC:
- completed independent periods/trades:
- realized vs modeled fees/slippage:
- current net PnL:
- current drawdown:

## Decision

- new state:
- hard block present: yes/no
- evidence supporting transition:
- unresolved weaknesses:
- next allowed action:

A candidate that fails locked validation is closed under this ID. Any modified hypothesis receives a new candidate ID and a new freeze.