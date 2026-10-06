# Governance Map v2

This generated prospective map is sourced from `config/multi_agents_v2.json`. It does not alter historical v1 reports or research evidence.

- **Deterministic checker count:** 18
- **Registry SHA-256:** `06c43cccd9ff9ec558f838513882eecbe65f5da234a3984746860c39038b7126`
- **Map SHA-256:** `f9fb1201d2e3259d2be05a201b2a78621187c65e65aaf7e38909cf47fb06a1ed`

| Deterministic agent ID | Logical compatibility role | Repository evidence |
| --- | --- | --- |
| `data_integrity` | DeerFlow data integrity; Ruflo market-data reviewer | deterministic local check evidence |
| `trend_structure` | DeerFlow strategy/backtest validation; Ruflo strategy reviewer | deterministic local check evidence |
| `volatility_regime` | DeerFlow strategy/backtest validation; Ruflo strategy reviewer | deterministic local check evidence |
| `liquidity_microstructure` | DeerFlow data integrity; Ruflo market-data reviewer | deterministic local check evidence |
| `aggressive_flow` | DeerFlow strategy/backtest validation; Ruflo strategy reviewer | deterministic local check evidence |
| `mean_reversion` | DeerFlow strategy/backtest validation; Ruflo strategy reviewer | deterministic local check evidence |
| `cross_asset_context` | DeerFlow strategy/backtest validation; Ruflo strategy reviewer | deterministic local check evidence |
| `news_event_context` | DeerFlow market context; optional observational coordination | deterministic local check evidence |
| `sentiment_context` | DeerFlow market context; optional observational coordination | deterministic local check evidence |
| `derivatives_positioning` | DeerFlow market context; Ruflo strategy reviewer | deterministic local check evidence |
| `execution_economics` | DeerFlow strategy/backtest validation; Ruflo strategy reviewer | deterministic local check evidence |
| `risk_path` | DeerFlow execution safety/risk; Ruflo security architect | deterministic local check evidence |
| `indicator_orthogonality` | DeerFlow research validity/statistics; Ruflo researcher | deterministic local check evidence |
| `research_validity` | DeerFlow research validity/statistics; Ruflo researcher | deterministic local check evidence |
| `transfer_generalization` | DeerFlow strategy/backtest validation; Ruflo strategy reviewer | deterministic local check evidence |
| `execution_safety` | DeerFlow execution safety/risk; Ruflo security architect | deterministic local check evidence |
| `reliability_observability` | DeerFlow reliability/CI and observability; Ruflo tester/reviewer | deterministic local check evidence |
| `adversarial_reviewer` | Lead adversarial synthesis and release manager | deterministic local check evidence |

## Coordination boundary

DeerFlow and Ruflo labels are logical orchestration groupings only. They do not equal the deterministic checker count, do not bootstrap services, and do not substitute for repository test or governance evidence.

## Lead / release manager

Adversarial synthesis and release manager; repository evidence, not coordination voting, governs release.
