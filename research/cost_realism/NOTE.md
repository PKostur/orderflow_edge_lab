# Cost realism: MEXC order-book snapshot (2026-09-26)

A single public depth snapshot per instrument, sequential REST calls. The round
trip is the market-order impact on both sides versus mid, plus twice the taker
fee from the contract metadata. Raw data is in `snapshot_2026_09_26.json`.

| Instrument | Spread | Taker per side | Round trip @10k | Round trip @50k |
| --- | ---: | ---: | ---: | ---: |
| BTC / ETH | 0.0 | 4.0 | 8.0 | 8.0 |
| SOL / XRP / DOGE | 0.6–1.0 | 0–1 | 0.6–2.8 | 0.6–2.8 |
| ADA / LINK / SUI / ENA | 0.4–3.9 | 0 | 0.9–3.9 | 2.6–6.2 |
| BNB | 1.3 | 4.0 | 11.4 | 13.0 |
| XAUT / SILVER | 0.2–1.6 | 4.0 | 8.7–9.6 | 9.0–9.7 |
| USOIL | 2.1 | 1.0 | 8.1 | 11.1 |
| SPX500 | 0.9 | 4.0 | 11.5 | 14.0 |
| NAS100 | 4.6 | 4.0 | 15.0 | **21.2** |

All figures are in bps.

**Reading.** The 20 bps round-trip assumption is conservative for 14 of the 15
forward instruments at 10–50k USDT per order. NAS100 at 50k is the only case
above it. The assumption stands; it is not lowered. One snapshot does not
cover volatile periods, weekends or fee-schedule changes. Repeated capture
(for example via the high-cadence capture workflow) would be needed before
relying on anything tighter.
