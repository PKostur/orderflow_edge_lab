"""Produce kronos-v1 forecasts (config/kronos_v1.json) for every weekly rebalance in the test window.

Run with the separate environment: .venv-kronos/Scripts/python scripts/kronos_forecast_2026_10_01.py
Resumable: forecasts are appended to research/kronos/forecasts_<sample>.json keyed by rebalance date.
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

sys.path.insert(0, str(Path("third_party/kronos").resolve()))
from model import Kronos, KronosPredictor, KronosTokenizer  # noqa: E402

from orderflow_edge_lab.xs_premia import daily_open_panel  # noqa: E402

cfg = json.load(open("config/kronos_v1.json", encoding="utf-8"))
F = cfg["forecast"]
LOOK, PRED = int(F["lookback_bars"]), int(F["pred_len_bars"])
OUT = Path("research/kronos")
OUT.mkdir(parents=True, exist_ok=True)
SAMPLES = {"development": "multi_premia_data.pkl", "confirmation": "multi_premia_untouched_data.pkl"}
W0, W1 = pd.Timestamp(cfg["test_window"]["start"], tz="UTC"), pd.Timestamp(cfg["test_window"]["end"], tz="UTC")

device = "cuda:0" if torch.cuda.is_available() else "cpu"
tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base", revision="0e0117387f39004a9016484a186a908917e22426")
model = Kronos.from_pretrained("NeoQuasar/Kronos-small", revision="901c26c1332695a2a8f243eb2f37243a37bea320")
predictor = KronosPredictor(model, tok, device=device, max_context=512)


def weights_sha() -> dict:
    from huggingface_hub import hf_hub_download
    out = {}
    for repo, rev in (("NeoQuasar/Kronos-small", "901c26c1332695a2a8f243eb2f37243a37bea320"),
                      ("NeoQuasar/Kronos-Tokenizer-base", "0e0117387f39004a9016484a186a908917e22426")):
        p = hf_hub_download(repo, "model.safetensors", revision=rev)
        out[repo] = {"revision": rev, "model.safetensors_sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest()}
    return out


pins = OUT / "pins.json"
if not pins.exists():
    pins.write_text(json.dumps({"code": cfg["pins"]["code"], "weights": weights_sha(), "torch": torch.__version__, "device": device}, indent=2))

for sample, cache in SAMPLES.items():
    frames, _ = pickle.load(open(os.path.join(os.environ["TEMP"], cache), "rb"))
    opens = daily_open_panel(frames)
    days = [d for i, d in enumerate(opens.index[:-1]) if i % 7 == 0 and W0 <= d < W1]
    path = OUT / f"forecasts_{sample}.json"
    done = json.loads(path.read_text()) if path.exists() else {}
    t0 = time.time()
    for n, d in enumerate(days):
        key = d.strftime("%Y-%m-%d")
        if key in done:
            continue
        dfs, xts, yts, syms = [], [], [], []
        for s, f in frames.items():
            ctx = f[f.index < d][["open", "high", "low", "close", "volume"]].astype(float)
            if len(ctx) < LOOK:
                continue
            ctx = ctx.iloc[-LOOK:]
            if ctx.isnull().values.any() or (ctx.index[-1] != d - pd.Timedelta(hours=8)):
                continue
            dfs.append(ctx.reset_index(drop=True))
            xts.append(pd.Series(ctx.index.tz_convert(None)))
            yts.append(pd.Series(pd.date_range(d, periods=PRED, freq="8h").tz_convert(None)))
            syms.append(s)
        rows = {}
        for b in range(0, len(dfs), 32):
            torch.manual_seed(int(cfg["forecast"]["seed"]) + n)
            np.random.seed(int(cfg["forecast"]["seed"]) + n)
            preds = predictor.predict_batch(dfs[b:b + 32], xts[b:b + 32], yts[b:b + 32], pred_len=PRED, T=F["sampling"]["T"],
                                            top_p=F["sampling"]["top_p"], sample_count=F["sampling"]["sample_count"], verbose=False)
            for s, ctx, p in zip(syms[b:b + 32], dfs[b:b + 32], preds):
                last = float(ctx["close"].iloc[-1])
                closes = p["close"].to_numpy(dtype=float)
                path_ = np.concatenate([[last], closes])
                lr = np.diff(np.log(np.clip(path_, 1e-12, None)))
                rows[s] = {"pred_return": float(closes[-1] / last - 1.0), "pred_move": float(np.mean(np.abs(lr)) * np.sqrt(PRED))}
        done[key] = rows
        path.write_text(json.dumps(done))
        print(f"{sample} {key} coins={len(rows)} [{n + 1}/{len(days)}] {time.time() - t0:.0f}s", flush=True)
print("done")
