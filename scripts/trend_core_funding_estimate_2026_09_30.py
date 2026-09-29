"""Pre-start funding-drag estimate for the crypto-trend-core 180-day review (registered 2026-09-30).

Runs the frozen crypto-trend-core-v1 pipeline over the pre-start window only (2026-07-15 to the
2026-09-29 start) and records the annualized funding contribution. Uses no forward day.
"""

from __future__ import annotations

import json
import sys

import pandas as pd

from orderflow_edge_lab.basis_convergence import fetch_mexc_funding_history
from orderflow_edge_lab.cross_asset_trend_forward import build_report
from orderflow_edge_lab.mexc_history import fetch_mexc_futures_klines

cfg = json.load(open("config/crypto_trend_core_v1.json", encoding="utf-8"))
as_of = pd.Timestamp("2026-09-29T00:00:00Z")
window_start = "2026-07-15T00:00:00Z"
src = cfg["source"]
frames, funding = {}, {}
for s in [s for m in cfg["groups"].values() for s in m]:
    frames[s] = fetch_mexc_futures_klines(s, src["interval"], src["warmup_start_utc"], as_of.isoformat())
    funding[s] = fetch_mexc_funding_history(s, src["warmup_start_utc"], as_of.isoformat())["funding_rate"]
r = build_report({**cfg, "prospective_start_utc": window_start}, frames, funding, as_of=as_of)
out = {"window": [window_start, as_of.isoformat()], "funding_contribution": r["funding_contribution"],
       "book": r["forward"]["combined"]}
json.dump(out, open(sys.argv[1], "w"), indent=1, default=float)
print(json.dumps(out["funding_contribution"]), out["book"]["days"])
