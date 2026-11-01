"""Compute the registered forward drawdown envelopes once (config/forward_drawdown_envelopes_v1.json).

Pre-start cached data only.  Refuses to overwrite an existing output.  Descriptive only.
Usage: python scripts/build_forward_drawdown_envelopes.py [output_path]
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import pickle
import sys

import pandas as pd

from orderflow_edge_lab.drawdown_envelopes import bootstrap_envelopes

CONFIG = pathlib.Path("config/forward_drawdown_envelopes_v1.json")
DEFAULT_OUT = pathlib.Path("research/forward_envelopes/envelopes_v1.json")


def series_sha256(s: pd.Series) -> str:
    h = hashlib.sha256()
    for t, v in s.items():
        h.update(f"{pd.Timestamp(t).isoformat()}|{float(v):.12e}\n".encode())
    return h.hexdigest()


def load_series() -> dict[str, pd.Series]:
    from orderflow_edge_lab.multi_premia_forward import blend, leg_returns
    from orderflow_edge_lab.strategy_search import crypto_trend_core_reference

    pkl = pathlib.Path(os.environ["TEMP"]) / "multi_premia_data.pkl"
    bcfg = json.loads(pathlib.Path("config/multi_premia_blend_v1.json").read_text(encoding="utf-8"))
    with open(pkl, "rb") as handle:
        frames, fund = pickle.load(handle)
    legs = leg_returns(bcfg, frames, fund)
    legs = legs[(legs != 0).all(axis=1).cumsum() > 0]
    s4 = blend(legs, vol_window=int(bcfg["blend"]["vol_window_days"]), min_obs=int(bcfg["blend"]["min_obs"]))
    s4 = s4[s4.index < pd.Timestamp("2026-09-12", tz="UTC")]
    ref = crypto_trend_core_reference(pathlib.Path("config/crypto_trend_core_v1.json"), pkl)
    ref = ref[ref.index < pd.Timestamp("2026-09-29", tz="UTC")]
    return {"multi-premia-blend-v1": s4, "crypto-trend-core-v1": ref}


def build(series: dict[str, pd.Series], out_path: pathlib.Path, cfg: dict) -> dict:
    if out_path.exists():
        raise FileExistsError(f"REFUSED: {out_path} already exists; envelopes are computed once.")
    m = cfg["method"]
    books = {c["watch_id"]: c["book"] for c in cfg["covered"]}
    doc = {"envelope_id": cfg["envelope_id"], "descriptive_only": True, "method": m, "watches": {}}
    for wid, s in series.items():
        entry = {"book": books.get(wid), "input_days": int(len(s)), "input_first": str(s.index[0]),
                 "input_last": str(s.index[-1]), "input_sha256": series_sha256(s), "variants": {}}
        for name, demean in (("as_backtested", False), ("zero_edge", True)):
            env = bootstrap_envelopes(s.to_numpy(), m["horizon_days"], m["paths"], m["mean_block_days"], m["seed"], demean)
            entry["variants"][name] = {c: [float(v) for v in env[c]] for c in env.columns}
        doc["watches"][wid] = entry
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "x", encoding="utf-8") as f:
        json.dump(doc, f, allow_nan=False)
    return doc


def main(out: str | None = None) -> int:
    out_path = pathlib.Path(out) if out else DEFAULT_OUT
    if out_path.exists():
        print(f"REFUSED: {out_path} already exists", file=sys.stderr)
        return 2
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    doc = build(load_series(), out_path, cfg)
    print(json.dumps({w: {"days": e["input_days"], "sha256": e["input_sha256"]} for w, e in doc["watches"].items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
