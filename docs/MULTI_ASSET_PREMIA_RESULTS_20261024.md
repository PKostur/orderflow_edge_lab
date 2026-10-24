# New allocation candidate: 24 October 2026

## Result

The new **25% SPY / 25% TLT / 25% GLD / 25% SHV** allocation passed all five frozen historical screens at baseline and doubled costs. It is a diversified investment allocation, with quarterly liquidation/reopening and integer-share budgets. It does not forecast price direction. No leverage is used.

Historical simulation, 2 January 2009 through 30 September 2026, starting with $10,000:

| Portfolio | Final net liquidation value | CAGR | Maximum close drawdown |
|---|---:|---:|---:|
| Four assets, baseline | $28,251.76 | 6.03% | 16.88% |
| Four assets, double costs | $26,380.82 | 5.62% | 17.28% |
| Short Treasuries only | $12,138.51 | 1.10% | 0.98% |
| Stocks only | $98,008.18 | 13.73% | 32.86% |
| 60/40 stocks / long Treasuries | $44,323.09 | 8.75% | 27.76% |
| Stocks / long Treasuries / gold | $37,912.73 | 7.80% | 22.30% |

All controls use the same funded quarterly execution and dividend accounting. They have different risk. Stocks and 60/40 earned more; this candidate does not establish alpha or superior absolute returns.

Baseline had 560 filled orders and four missed orders; these are not 560 independent trades. Paid costs were $904.35, or $1,780.05 under stress. Final baseline NAV includes $110.637 of unpaid dividend receivables: spendable terminal cash is $28,141.12. The 2022 return was **-12.12%**; January–September 2026 was **-0.01065%**. Losses and prolonged disappointing periods remain possible.

The five predeclared screens were: CAGR at least 4%, CAGR above Treasury-only, close drawdown at most 25%, all four fixed multiyear blocks positive, and no calendar year below -20%, each at both cost levels. Baseline block returns were +32.61%, +19.13%, +36.36%, +31.15%. The screen is a practical historical filter, not statistical proof of future profits.

## Independent verification and provenance

An independent implementation imported no production evaluator and reconciled all ten portfolio/cost cases: 44,630 daily wallet marks, 3,104 order records and 1,972 dividend events. Cash, inventory, NAV, receivables, yearly returns and block returns matched; maximum aggregate cost residual was below $0.000000000001. Full report is in the evidence bundle.

Public Yahoo raw unadjusted daily OHLCV and dividend events: 1 December 2008–30 September 2026, 4,485 synchronized bars per asset; 4,463 evaluated sessions. No split events were accepted. Full raw replies, extracted data, calendars and hash manifests are archived. This is one public provider, not independently verified exchange tape. The sample omits the 2008 crisis. SPY/SHV had already been viewed in the rejected timing study. Published allocation literature and incidental performance snippets were exposed before freeze. All historical observations are development evidence.

Quarterly full turnover, per-sleeve fixed cash budgets, fee-inclusive integer sizing and 102% prior-close opening limits are charged explicitly. Dividends are counted once, becoming buying power only after a modeled 90-day delay; exact payment dates were not reconstructed. Baseline costs are `max($1, .005 * shares) + .00015 * notional` per side; stress doubles them. Actual broker commissions, settlement, auction fills, taxes and currency conversion remain unverified. ETF expenses already affect observed prices.

Candidate design was committed at `7192bf3` before new TLT/GLD acquisition. Executed evaluator commit: `cf646c6df9ca225e7c3815fc7617692c4b81d554`.

| Identity | SHA256 |
|---|---|
| Evaluator | b3309541dd9d51864b9bd0816062ace49bdfbad7d516f138d724efd9930cf614 |
| Wallet helper | e225d2aeb2af6092fe3915b577442be2c97c5bf5001ab7917a339c9a849eb922 |
| Frozen config | 3cbc69df7600826d7dbbaabd4eef9b5020fc408523d5a3e9113370eb51c53bdf |
| Source manifest | ea5c738007581cda81a5c93689bc2c67eb42eb4349c0cda463aff79b6be82813 |
| Uncompressed results | 464607c46c75f8b7ebe45ecfa82c34215cd6e94d833c0e526b26c0fba68ae83f |

See [evidence index](../artifacts/multi_asset_premia_20261024/index.json), [compact results](../artifacts/multi_asset_premia_20261024/summary.json), [trial ledger](../artifacts/multi_asset_premia_20261024/trial_ledger.json), and the full `.json.gz` ledgers/source ZIPs in that directory. Decompress without reformatting to verify original hashes. Frozen prior research lanes are unchanged.

## Rejected new study retained

The month-end SPY / short-Treasury timing hypothesis returned 2.73% CAGR but failed its positive-block and random-window screens: 2014–18 lost 9.95%, and 21/100 random controls exceeded it (corrected tail 22/101 = 21.78%). **Rejected as defined.** No tuning followed. The initial BIL source failed on a reverse split before economics; SHV replacement and surprise-closure causality repairs were frozen before the sole economic timing run. All registrations and failed-source evidence are retained, rather than silently discarding unsuccessful attempts. Minimum cumulative trial counts are 36 trading hypotheses / 37 including signal studies; this is repeated historical selection, not a fresh holdout.

## Forward operational paper pilot

The sealed entry intention is **Monday 26 October 2026, 13:30 UTC / 15:30 Athens**. Reference prices are from 23 October. Two separate modeled $10,000 accounts track baseline and double costs. Each intends SPY 3, TLT 30, GLD 6, SHV 22 shares, subject to the frozen limits and separate $2,500 budgets. Missing a limit leaves that sleeve in cash. No quantities are recalculated after the opening. The pilot holds until 31 December 2026 close and has no next-quarter reentry.

Canonical intent seal: `1d66bb284c0df54a6b1af65d6d0c6f925c1030c8bc08ca8879ebc88da30bfc60`. Full calendar covers 2026–2027; the historical truncated calendar is not reused. Preflight reports `WAITING_FOR_REGISTERED_ENTRY` with no fabricated positions or fills. Current intentions are simulation instructions, not broker orders.

The GitHub workflow observes completed sessions at 22:15 UTC on weekdays in October–December and becomes scheduled only after merge to the default branch. It expires after the finite pilot; it has read-only permissions and no account credentials. Scheduled runs can be delayed by GitHub. Raw observations and hash-bound results are uploaded as artifacts for 90 days. Download evidence before expiry.

This is an **operational forward observation**, not a registered statistical confirmation study. It does not prove an edge, authorize live execution, or satisfy the user's ultimate requirement for confirmation on untouched future data. `promotable=false`; live orders remain disabled. The immediate next step is collect the frozen opening and subsequent observations, reconcile execution assumptions, then define any further confirmation phase before inspecting its future outcomes.

The independent forward review passed the fixed registration, funding, terminal sale, dividend and failure paths. Runtime binds the exact intent/reference/quantities, complete calendar and wallet helper to published registration `d4cb8bd61eb7e0a2c9c1f4cfe07101b7c3fb527c`. GitHub Actions run `40089297194` independently timestamps the fixed observer `084c44306409acf8d160fb8521c3d8d1b6758e46` before the planned opening; retained API receipts are in `external-publication.json`. A self-supplied creation timestamp is not the registration evidence. Subsequent Yahoo revisions may restate earlier modeled marks: retain each raw snapshot and disclose revisions; these are not immutable verified broker executions.

## Delivery checks

[PR #178](https://github.com/PKostur/orderflow_edge_lab/pull/178) carries the new lane. At source commit `084c44306409acf8d160fb8521c3d8d1b6758e46`, all **1,246 tests** passed in Linux/Python 3.10, 3.11, 3.12 and Windows/Python 3.12 CI; Ruff and CodeQL analysis passed. The downloaded remote multi-agent manifest verifies and its release manager is `reviewable`, zero errors/warnings. Repository CodeQL has two pre-existing alerts in `tests/test_news_sentiment.py:26`, created 2 October; this PR does not change that file. A passing analysis is not a claim that the repository has zero alerts.

Collector scripts are retained in a ZIP as acquisition provenance; they contain the original directory layout and guards, and must not overwrite frozen evidence. To recompute history, extract the four-regime source ZIP to a fresh directory and run `python -m orderflow_edge_lab.four_regime_allocation --source <extracted-directory> --output <new-result.json>` with `PYTHONPATH=src`. The output records the current reproduction commit; the archived original run retains its exact execution identity. Calendar creation used `exchange_calendars==4.11.1`; existing archived calendars make economic replay independent of future calendar-library changes.

Reproduce preflight:

```powershell
$env:PYTHONPATH='src'
python -m orderflow_edge_lab.four_regime_paper --intent config/four_regime_paper_intent_v1.json --calendar artifacts/four_regime_forward_operational_v1/calendar.csv --output artifacts/local-forward-observation
```
