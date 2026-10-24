# Equity turn-of-month: pre-data source and execution review

Date: 2026-10-24. Status: source-readiness review only; no price history, market payload, return calculation, backtest, registration, or orders. Root is sole repository writer. This file is outside Git.

## Scope and overlap

ONE new economic hypothesis: SPY exposure during the published four-session turn-of-month interval, cash otherwise; long-only, no leverage, no indicator or threshold search. A scoped case-insensitive search of repository config/ and docs/ for turn-of-month, McConnell, and equity/calendar combinations found no implementation; the only hit was an unrelated existing calendar-diagnostic sentence. This is a scoped search, not proof of absence throughout every file. Frozen crypto/prospective lanes remain unchanged. No claim of viability is made.

## Published definition and exact clock

McConnell and Xu, Financial Analysts Journal 64(2), 2008, pp49-64, DOI10.2469/faj.v64.n2.11. Author-hosted paper and publisher abstract establish a window consisting of the final trading session of a month and the first three sessions of the next month. The source studies broad equity daily returns, not a specified SPY bot with order-size and cost rules. SPY plus cash is a declared implementable adaptation.

Let sessions in the old month end ..., P, L and those in the next month begin F1,F2,F3. To earn daily close-to-close returns labelled L,F1,F2,F3, buy at P close and sell at F3 close. Buying at L close misses the entire last-session return. Holding from P close through F3 close comprises four session returns; overnight/weekend exposure is included. Exit after F3 close is too late if execution instead occurs F4 open. Do not silently substitute open execution.

Calendar-only MOC intent can be committed before the closing price is known. The current official NYSE page specifies Arca closing freeze at3:59pm Eastern and closing auction4pm; the NYSE venue has a different3:50pm cutoff. SPY's issuer identifies NYSE Arca as its listing venue. Broker deadlines may be earlier. Early closes require the venue's adjusted schedule. Use America/New_York, not a fixed UTC offset; validate holiday changes, extraordinary closures and historical session calendars. No price-derived scheduling or truncation-dependent last-row scheduling.

Daily vendor close is an execution proxy until shown to equal the relevant official auction print. The mathematical study must state this limitation and frozen per-side spread/slippage/commission burdens. A full-equity fraction computed using the unknown same-auction close is not automatically an executable fixed-share MOC instruction: freeze a causal quantity rule, fee reserve and cash rejection policy before loading prices. Do not allow negative cash, borrowing or retrospective resizing. This review does not choose a sizing rule.

## Data feasibility and corporate actions

Issuer metadata confirms SPY inception22Jan1993; this is not a verified first usable exchange-price date or a completeness guarantee. Yahoo's official help says adjusted close incorporates split and dividend multipliers, including backward dividend adjustments. It also says historical CSV downloading currently requires Gold and may be restricted by licensing. Therefore free Yahoo chart JSON is a possible technical route, not a documented guaranteed public API or verified usable dataset. No chart/data endpoint has been requested here. Do not bypass authentication, access controls or rate limits. An actual later acquisition needs endpoint/status, request interval, access time, response hash, schema, full coverage/null/duplicate/session audits and licensing caveat.

Required retained fields: provider date/timezone, raw or explicitly split-adjusted OHLCV convention, close, adjusted close, ex-dividend amount/date, splits; pay dates where available. Never assume the provider's field named close is unadjusted. Freeze and reconcile adjustment conventions before computing returns. Adjusted close is not a tradable cash/share price. Adjusted-close ratios are a vendor-adjusted return proxy: Yahoo's multiplicative dividend adjustment is not by itself proof of exact cash-dividend reinvestment or auction fills. Do not add dividends again to adjusted returns. For actual share/cash accounting, credit entitlement only if held across the ex-date boundary, retain a receivable until payment, and do not spend unpaid cash dividends. Subsequent back-adjustments must not determine historical quantities or calendar signals.

The issuer product page is a primary metadata/distribution cross-check. A free issuer NAV-history spreadsheet has not been downloaded or verified; NAV is not the market closing auction price and cannot replace it silently. Fund expenses embedded in fund prices should not be subtracted a second time; trading costs and any taxes are separate declared assumptions. Full OHLCV is useful for QA; the core calendar hypothesis needs validated closes and corporate actions rather than intraday signal data.

## Cash carry and comparators

Off-window cash must be explicitly defined, using the same convention for candidate and controls. Treasury bill quoted discount rates are annualized yields, not a daily investable total-return series. TreasuryDirect documents the discount-price formula; treating rate/252 as realized bill return invents a rolling mark-to-market instrument. A lagged, availability-aware interest accrual can be a labelled research cash proxy if its exact day-count/weekend/settlement conventions are frozen before data; it is not guaranteed broker interest or bill execution. Do not use same-day rates published after the decision or unreleased revised values. A zero-interest cash sensitivity can isolate the calendar exposure hypothesis. This review does not choose a cash series or carry rate.

A subsequent frozen study should use same-data SPY buy-and-hold and all-cash comparators, an explicitly fixed exposure-matched calendar control, complete month clusters, and a predeclared cost burden. This source audit creates no new gates or pass criteria. Do not import a crypto52-entry-week criterion into a new monthly design by accident; equally do not weaken any existing lane's gate. Freeze a separate appropriate calendar protocol before outcomes.

## Readiness boundary and next step

Mechanics are draftable, but not yet a fully specified executable strategy. Root must freeze P-close/F3-close timing, eligible date range, causal sizing, cash-carry accounting, complete-month admission, treatment of extraordinary closures, execution proxy/costs, benchmarks, controls, dependence inference and a future confirmation endpoint before acquisition. Historical data remains DEVELOPMENT. Search results exposed published paper findings and issuer summary-performance snippets; no claim of blind source discovery or untouched historical confirmation is appropriate. No strategy PnL or price-history payload was inspected in this review. Genuine later untouched evidence remains necessary for a viability claim.

## Primary sources checked

- Publisher: https://rpc.cfainstitute.org/research/financial-analysts-journal/2008/equity-returns-at-the-turn-of-the-month
- Author-hosted published paper: https://business.purdue.edu/faculty/mcconnell/publications/Equity-Returns-at-the-Turn-of-the-Month.pdf (indexed text retrieved; direct PDF web open timed out; no local PDF/hash receipt claimed)
- Author institutional working-paper record (2006 predecessor; distinguish from2008 publication): https://docs.lib.purdue.edu/ciberwp/43/
- Official auctions and venue clocks: https://www.nyse.com/trade/auctions
- Official calendars: https://www.nyse.com/markets/hours-calendars
- Issuer SPY metadata: https://www.ssga.com/us/en/institutional/etfs/state-street-spdr-sp-500-etf-trust-spy
- Yahoo adjustment definition: https://in.help.yahoo.com/kb/adjusted-close-sln28256.html
- Yahoo download availability: https://in.help.yahoo.com/kb/finance/download-historical-data-yahoo-finance-sln2311.html
- Treasury bill pricing convention: https://www.treasurydirect.gov/marketable-securities/understanding-pricing/

Web checks used search/indexed primary-source text on2026-10-24. Mutable pages are not immutable receipts. No source code copied. registered=false; new_trading_cells=0.
