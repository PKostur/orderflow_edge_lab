from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pandas as pd


BASE = "https://data.binance.vision/data/futures/um"


class BinanceVisionError(ValueError):
    pass


def _get(url: str) -> bytes:
    try:
        with urlopen(Request(url, headers={"User-Agent": "orderflow-edge-lab/1.0"}), timeout=45) as r:
            return r.read()
    except HTTPError as exc:
        raise BinanceVisionError(f"HTTP {exc.code}: {url}") from exc


def _verified_zip(url: str) -> tuple[bytes, dict]:
    payload = _get(url)
    actual = hashlib.sha256(payload).hexdigest()
    official = None
    try:
        official = _get(url + ".CHECKSUM").decode().strip().split()[0].lower()
    except BinanceVisionError as exc:
        if "HTTP 404" not in str(exc):
            raise
    if official and official != actual:
        raise BinanceVisionError(f"checksum mismatch: {url}")
    return payload, {"url": url, "sha256": actual, "official_sha256": official, "bytes": len(payload)}


def _csv(payload: bytes, *, header="infer") -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise BinanceVisionError(f"expected one CSV, got {names}")
        return pd.read_csv(io.BytesIO(zf.read(names[0])), header=header)


def _utc_epoch(values: pd.Series) -> pd.DatetimeIndex:
    x = pd.to_numeric(values, errors="coerce")
    if x.isna().any():
        raise BinanceVisionError("invalid timestamp")
    m = float(x.abs().max())
    unit = "s" if m < 1e11 else ("ms" if m < 1e14 else "us")
    return pd.DatetimeIndex(pd.to_datetime(x.astype("int64"), unit=unit, utc=True))


def _parse_kline(payload: bytes) -> pd.DataFrame:
    raw = _csv(payload, header=None)
    if pd.to_numeric(pd.Series([raw.iloc[0, 0]]), errors="coerce").isna().iloc[0]:
        raw = raw.iloc[1:].reset_index(drop=True)
    if raw.shape[1] < 6:
        raise BinanceVisionError("invalid kline schema")
    idx = _utc_epoch(raw.iloc[:, 0])
    out = pd.DataFrame(index=idx)
    for name, col in zip(("open", "high", "low", "close", "volume"), range(1, 6)):
        out[name] = pd.to_numeric(raw.iloc[:, col].to_numpy(), errors="coerce")
    return out.dropna().sort_index()[lambda x: ~x.index.duplicated(keep="last")]


def _parse_funding(payload: bytes) -> pd.DataFrame:
    raw = _csv(payload)
    names = {str(c).lower(): c for c in raw.columns}
    tcol = names.get("calc_time") or names.get("fundingtime") or names.get("funding_time")
    rcol = names.get("last_funding_rate") or names.get("fundingrate") or names.get("funding_rate")
    if tcol is None or rcol is None:
        raw = _csv(payload, header=None)
        if raw.shape[1] < 3:
            raise BinanceVisionError("invalid funding schema")
        times, rates = raw.iloc[:, 0], raw.iloc[:, -1]
    else:
        times, rates = raw[tcol], raw[rcol]
    out = pd.DataFrame({"funding_rate": pd.to_numeric(rates, errors="coerce").to_numpy()}, index=_utc_epoch(times))
    return out.dropna().sort_index()[lambda x: ~x.index.duplicated(keep="last")]


def fetch_vision(symbol: str, start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    native = symbol.upper().replace("_", "")
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    s = s.tz_localize("UTC") if s.tzinfo is None else s.tz_convert("UTC")
    e = e.tz_localize("UTC") if e.tzinfo is None else e.tz_convert("UTC")
    prices, funding, objects = [], [], []
    month = s.normalize().replace(day=1)
    while month < e:
        nxt = month + pd.offsets.MonthBegin(1)
        stamp = month.strftime("%Y-%m")
        partial_month = nxt > e
        if not partial_month:
            ku = f"{BASE}/monthly/klines/{native}/1d/{native}-1d-{stamp}.zip"
            kb, ko = _verified_zip(ku); prices.append(_parse_kline(kb)); objects.append(ko)
        else:
            d = max(month.date(), s.date()); last = (e - pd.Timedelta(days=1)).date()
            while d <= last:
                ds = d.isoformat(); ku = f"{BASE}/daily/klines/{native}/1d/{native}-1d-{ds}.zip"
                kb, ko = _verified_zip(ku); prices.append(_parse_kline(kb)); objects.append(ko); d += timedelta(days=1)

        fu = f"{BASE}/monthly/fundingRate/{native}/{native}-fundingRate-{stamp}.zip"
        try:
            fb, fo = _verified_zip(fu); funding.append(_parse_funding(fb)); objects.append(fo)
        except BinanceVisionError as exc:
            if "HTTP 404" not in str(exc):
                raise
            if not partial_month:
                raise
            d = max(month.date(), s.date()); last = (e - pd.Timedelta(days=1)).date()
            while d <= last:
                ds = d.isoformat(); du = f"{BASE}/daily/fundingRate/{native}/{native}-fundingRate-{ds}.zip"
                db, do = _verified_zip(du); funding.append(_parse_funding(db)); objects.append(do); d += timedelta(days=1)
        month = nxt
    p = pd.concat(prices).sort_index(); p = p[~p.index.duplicated(keep="last")]
    f = pd.concat(funding).sort_index() if funding else pd.DataFrame(columns=["funding_rate"], index=pd.DatetimeIndex([], tz="UTC"))
    if not f.empty: f = f[~f.index.duplicated(keep="last")]
    return p.loc[(p.index >= s) & (p.index < e)], f.loc[(f.index >= s) & (f.index < e)], objects
