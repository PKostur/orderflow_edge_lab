# Backtest Council

`backtest_council_v1` attacks a single backtest from several independent angles and returns a rule-based verdict. It implements the `mandatory_controls` frozen in `config/universal_backtest_framework_v1.json`, which the universal engine records but did not previously enforce together.

Every member is a deterministic test. None of them is a language model and none of them votes by opinion. The judge applies fixed rules: any `FAIL` rejects, any `WARN` requires more or new data, and only an all-pass result is eligible for a separately frozen forward shadow.

## Members

| Member | Control | Question it asks | Fails when |
|---|---|---|---|
| `lookahead_auditor` | `no_lookahead_check` | Does the signal change if future bars are removed? | Targets on truncated history differ from the full-history targets |
| `sample_clerk` | sample size | Are there enough trades to judge? | Fewer than 30 trades (warns below 100) |
| `cost_skeptic` | `cost_stress` | Does it survive costs, stressed costs and adverse perpetual funding? | Net expectancy after base costs and adverse funding is not positive (warns at 1.5x costs) |
| `null_examiner` | `reversed_or_sign_control` | Does the timing beat the same positions shifted to random times? | Circular-shift p-value above 0.20 (warns above 0.05) |
| `concentration_prosecutor` | `concentration` | Is the result carried by a few trades or one day? | Removing the best day leaves no profit (warns if the top 5% of trades carry it or one day is at least 50% of net) |
| `fold_examiner` | `time_fold` | Does it work across time? | Under 35% of 30-day folds positive (warns under 50% or if the block-bootstrap interval touches zero) |
| `breadth_examiner` | `symbol_breadth` | Does it transfer across symbols? | Positive on under 50% of symbols (warns for a single symbol) |
| `multiple_testing_auditor` | multiple testing | Is this just the best of many tries? | Deflated Sharpe probability under 0.5 over the grid, or Bonferroni-adjusted p above 0.5 over declared trials (warns if the trial count is unknown) |
| `risk_path_auditor` | leverage path | Would the intended leverage have survived each trade's adverse excursion? | Expectancy is negative once liquidated trades lose the full margin |
| `direction_auditor` | direction split | Is only one side making money? | Never fails; warns when long and short disagree in sign |
| `believer` | case for | What is the strongest factual case? | Never votes |

Thresholds live in `config/backtest_council_v1.json` and are frozen before use.

## Run

```bash
orderflow-backtest-council \
  --data-dir data/ohlcv_8h \
  --family donchian_breakout --params-json '{"lookback":55}' \
  --grid-json '{"lookback":[20,55,100]}' --trial-count 40 \
  --cost-bps 20 --leverage 25 \
  --output artifacts/council/don8.json --markdown artifacts/council/don8.md
```

A custom strategy, such as rules extracted from a discretionary method, plugs in as any object implementing `StrategyPlugin`:

```bash
orderflow-backtest-council --strategy mypackage.rules:make_strategy --data BTC=btc_1h.csv --cost-bps 12 --output out.json
```

`--strict` exits nonzero unless the verdict is `SHADOW_ELIGIBLE`.

## Evidence semantics

- The report is hashed; `verify_council_report` rejects edited verdicts or claims.
- `profitable_edge_established`, `verified_out_of_sample_evidence` and `live_trading_authorized` are always `false`.
- Running the council inspects the data. That data is then spent for independent validation.
- A `REJECT` is not repaired by re-tuning on the same data. Loosening thresholds to pass a candidate is not allowed.
- The council does not change frozen candidates. It is a reporting layer and is allowed under the current research stop rule.

## Known limits

- Bars are the finest resolution for the liquidation check, so intrabar ordering is unknown. The liquidation count is a lower bound.
- Funding is modeled as an adverse flat charge per 8-hour crossing, not from the historical funding series.
- The circular-shift null preserves exposure, holding pattern and long/short mix but also carries over any warmup period.
- Order-book and event strategies still need the event-driven path in `orderflow_backtest.py`.
