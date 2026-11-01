"""CTREND (Fieberg, Liedtke, Poddig, Walker, Zaremba, JFQA 2025): 28 technical indicators, CS-C-ENet, quintile long-short.

Implements candidate R2C1_CTREND of ``config/strategy_search_v1_round2.json`` exactly as registered (see the module
constants for every literal choice).  Descriptive research code: no promotion, no leverage, no order placement.

Data convention: ``data`` is a dict with dates x symbols DataFrames ``close``, ``high``, ``low`` and ``dollar_volume``
(quote-asset volume), indexed by UTC-normalised daily dates; the bar dated ``d`` covers ``d 00:00-23:59:59 UTC``.  Keys
starting with ``_`` are kept untouched by ``strategy_search.truncate_data``.

Timeline.  Week ``k`` ends on Sunday ``S_k``.  The indicators at ``S_k`` use daily bars up to and including the Sunday
close.  The portfolio decided at ``S_k`` is held Monday to Sunday (earns the close ``S_k`` -> close ``S_{k+1}`` return).
Everything known at ``S_k``: indicators and ranks up to ``S_k``; univariate cross-sectional regressions of the return
of week ``j`` (``S_{j-1}`` -> ``S_j``) on the ranks at ``S_{j-1}`` for ``j <= k``.  CS-C-ENet uses ONE trailing window of
``M`` weeks (``j = k-M+1 .. k``): the weekly WLS coefficients are averaged over the window; in-window forecasts for each
of those ``M`` weeks are built from the window-averaged coefficients and that week's ranks; the pooled elastic net
regresses the ``M`` realised returns on those forecasts; positive coefficients select the univariate forecasts whose
equal-weighted mean (at ``S_k``) is the signal.  About ``M`` weeks of regressions are needed.  Nothing later is used.

Literal choices where the source is silent (all logged in the round-2 result file):
* EMA alpha = 1/(1+L), first EMA value = first close (the printed "initialise with the close at t-1").
* RSI uses plain (simple) averages of gains and losses; Bollinger sigma is the population sd (ddof 0); CCI uses the mean
  absolute deviation around the current SMA(20) and the constant 0.015; Chaikin is the 21-day money-flow ratio.
* An indicator that is not defined for an eligible coin (insufficient history, zero denominator) ranks as 0, the
  cross-sectional median of the [-0.5, 0.5] mapping.
* The univariate FM coefficients are plain averages of the last ``M`` weekly WLS fits (``M`` = rolling window).
* The pooled elastic net is unweighted, uses centred data (free intercept), no standardisation and no demeaning of the
  returns, sklearn's default path (``eps=1e-3``, 100 values), and corrected AIC
  ``n ln(RSS/n) + 2k + 2k(k+1)/(n-k-1)`` with ``k`` = nonzero coefficients + 1 (intercept).
* No winsorising or truncation of returns (not registered).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any
import warnings

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

DEFAULT_PARAMS: dict[str, Any] = {"rolling_window_weeks": 52, "quantiles": 5, "l1_ratio": 0.5,
                                  "indicator_window_scale": 1.0}
MIN_BARS = 200
MIN_DOLLAR_VOLUME = 1_000_000.0
DOLLAR_VOLUME_WINDOW = 30
DOLLAR_VOLUME_MIN_PERIODS = 20
MIN_CROSS_SECTION = 20
GROSS_PER_LEG = 0.5
SMA_LENGTHS = (3, 5, 10, 20, 50, 100, 200)
ENET_EPS = 1e-3
ENET_N_ALPHAS = 100

INDICATOR_NAMES: tuple[str, ...] = (
    "rsi", "stochK", "stochD", "stochRSI", "cci",
    *(f"sma_{n}d" for n in SMA_LENGTHS), "macd", "macd_diff_signal",
    *(f"volsma_{n}d" for n in SMA_LENGTHS), "volmacd", "volmacd_diff_signal", "chaikin",
    "boll_low", "boll_mid", "boll_high", "boll_width",
)
N_INDICATORS = len(INDICATOR_NAMES)


class CTrendError(ValueError):
    pass


# -------------------------------------------------------------------------------------------- indicators


def scaled_window(length: int, scale: float) -> int:
    """Lookback ``length`` scaled by ``scale`` and rounded half up, minimum 2 (scale 1.0 is the identity)."""
    return max(2, int(math.floor(length * scale + 0.5 + 1e-9)))


def sma(x: pd.DataFrame | pd.Series, length: int):
    return x.rolling(length, min_periods=length).mean()


def ema(x: pd.DataFrame | pd.Series, length: int):
    """EMA_t = a P_t + (1 - a) EMA_{t-1}, a = 1/(1+L) as printed in the supplement; first value = first observation."""
    return x.ewm(alpha=1.0 / (1.0 + length), adjust=False).mean()


def rolling_mean_abs_dev(x: pd.DataFrame, length: int) -> pd.DataFrame:
    """Mean of |x_{t-l} - mean(x_{t-L+1..t})| over the window (NaN if any value in the window is missing)."""
    a = x.to_numpy(dtype=float)
    out = np.full(a.shape, np.nan)
    if a.shape[0] >= length:
        win = sliding_window_view(a, length, axis=0)  # (T - L + 1, N, L)
        step = 256
        for s in range(0, win.shape[0], step):
            blk = win[s:s + step]
            m = blk.mean(axis=2)
            out[length - 1 + s:length - 1 + s + len(blk)] = np.abs(blk - m[:, :, None]).mean(axis=2)
    return pd.DataFrame(out, index=x.index, columns=x.columns)


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    return df.where(np.isfinite(df))


def indicator_frames(close: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame, dollar_volume: pd.DataFrame,
                     scale: float = 1.0):
    """Yield ``(name, frame)`` for the 28 indicators (daily frames), in ``INDICATOR_NAMES`` order."""
    w = lambda n: scaled_window(n, scale)  # noqa: E731
    c, h, lo, v = close, high, low, dollar_volume
    # oscillators
    l14 = w(14)
    delta = c.diff()
    gains = delta.clip(lower=0.0)
    losses = (-delta).clip(lower=0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = sma(gains, l14) / sma(losses, l14)
        rsi = 100.0 - 100.0 / (1.0 + rs)
        hh = h.rolling(l14, min_periods=l14).max()
        ll = lo.rolling(l14, min_periods=l14).min()
        stoch_k = (c - ll) / (hh - ll)
        rsi_lo = rsi.rolling(l14, min_periods=l14).min()
        rsi_hi = rsi.rolling(l14, min_periods=l14).max()
        stoch_rsi = (rsi - rsi_lo) / (rsi_hi - rsi_lo)
    yield "rsi", _clean(rsi)
    yield "stochK", _clean(stoch_k)
    yield "stochD", _clean(sma(stoch_k, w(3)))
    yield "stochRSI", _clean(stoch_rsi)
    l20 = w(20)
    tp = (c + h + lo) / 3.0
    tp_sma = sma(tp, l20)
    with np.errstate(divide="ignore", invalid="ignore"):
        cci = (tp - tp_sma) / (0.015 * rolling_mean_abs_dev(tp, l20))
    yield "cci", _clean(cci)
    # moving averages of the close, scaled by the close
    for n in SMA_LENGTHS:
        with np.errstate(divide="ignore", invalid="ignore"):
            yield f"sma_{n}d", _clean(sma(c, w(n)) / c)
    fast, slow, sig = w(12), w(26), w(9)
    ema_fast = ema(c, fast)
    with np.errstate(divide="ignore", invalid="ignore"):
        macd = (ema_fast - ema(c, slow)) / ema_fast
    yield "macd", _clean(macd)
    yield "macd_diff_signal", _clean(macd - ema(macd, sig))
    # dollar-volume indicators
    for n in SMA_LENGTHS:
        with np.errstate(divide="ignore", invalid="ignore"):
            yield f"volsma_{n}d", _clean(sma(v, w(n)) / v)
    v_fast = ema(v, fast)
    with np.errstate(divide="ignore", invalid="ignore"):
        volmacd = (v_fast - ema(v, slow)) / v_fast
    yield "volmacd", _clean(volmacd)
    yield "volmacd_diff_signal", _clean(volmacd - ema(volmacd, sig))
    l21 = w(21)
    rng = h - lo
    with np.errstate(divide="ignore", invalid="ignore"):
        mfm = ((c - lo) - (h - c)) / rng
    mfm = mfm.where(rng != 0, 0.0).where(rng.notna())
    ad = mfm * v
    with np.errstate(divide="ignore", invalid="ignore"):
        chaikin = ad.rolling(l21, min_periods=l21).sum() / v.rolling(l21, min_periods=l21).sum()
    yield "chaikin", _clean(chaikin)
    # Bollinger bands: 20d SMA +/- 2 population sd, scaled by the close
    mid = sma(c, l20)
    sd = c.rolling(l20, min_periods=l20).std(ddof=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        boll_low = (mid - 2.0 * sd) / c
        boll_mid = mid / c
        boll_high = (mid + 2.0 * sd) / c
        boll_width = (boll_high - boll_low) / boll_mid
    yield "boll_low", _clean(boll_low)
    yield "boll_mid", _clean(boll_mid)
    yield "boll_high", _clean(boll_high)
    yield "boll_width", _clean(boll_width)


# ------------------------------------------------------------------------------------------ ranks and model


def rank_to_unit(values: np.ndarray, eligible: np.ndarray) -> np.ndarray:
    """Cross-sectional (row-wise) rank mapped to [-0.5, 0.5] among eligible coins with a finite value.

    Ties get the average rank.  Eligible coins without a finite value get 0 (the median); ineligible coins get NaN.
    """
    v = np.where(eligible & np.isfinite(values), values, np.nan)
    ranks = pd.DataFrame(v).rank(axis=1, method="average").to_numpy(dtype=float)
    n = np.isfinite(v).sum(axis=1, keepdims=True).astype(float)
    mapped = np.where(n > 1, (ranks - 1.0) / np.maximum(n - 1.0, 1.0) - 0.5, 0.0)
    return np.where(np.isfinite(v), mapped, np.where(eligible, 0.0, np.nan))


def wls_univariate(z: np.ndarray, y: np.ndarray, w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Weighted least squares of ``y`` on each row of ``z`` (indicators x coins): intercepts and slopes.

    Minimises sum_i w_i (y_i - a - b z_i)^2.  A degenerate indicator (zero weighted variance) gets slope 0.
    """
    ws = w / w.sum()
    zbar = z @ ws
    ybar = float(ws @ y)
    zc = z - zbar[:, None]
    var = (zc * zc) @ ws
    cov = zc @ (ws * (y - ybar))
    slope = np.where(var > 1e-14, cov / np.where(var > 1e-14, var, 1.0), 0.0)
    intercept = ybar - slope * zbar
    return intercept, slope


def enet_aicc_path(x: np.ndarray, y: np.ndarray, l1_ratio: float) -> dict[str, Any]:
    """Elastic net over sklearn's default lambda path; the lambda minimising the corrected AIC.

    Returns the path (alphas, coefficients), the AICc values and the chosen coefficients.  Centred data, free
    intercept, unweighted, no standardisation.  AICc = n ln(RSS/n) + 2k + 2k(k+1)/(n-k-1), k = nonzero coefficients + 1.
    """
    import inspect

    from sklearn.exceptions import ConvergenceWarning
    from sklearn.linear_model import enet_path

    n = x.shape[0]
    xc = x - x.mean(axis=0)
    yc = y - y.mean()
    if n < 3 or not np.any(np.abs(xc.T @ yc) > 0.0):
        zero = np.zeros(x.shape[1])
        return {"alphas": np.array([]), "coefs": np.zeros((x.shape[1], 0)), "aicc": np.array([]), "best": None,
                "coef": zero, "n": n}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        # sklearn >= 1.9 takes the number of path values as ``alphas=<int>`` (``n_alphas`` is deprecated)
        grid = ({"alphas": ENET_N_ALPHAS} if inspect.signature(enet_path).parameters["n_alphas"].default == "deprecated"
                else {"n_alphas": ENET_N_ALPHAS})
        alphas, coefs, _ = enet_path(xc, yc, l1_ratio=l1_ratio, eps=ENET_EPS, **grid)
    resid = yc[:, None] - xc @ coefs
    rss = np.maximum((resid ** 2).sum(axis=0), 1e-300)
    k = (coefs != 0).sum(axis=0) + 1.0
    with np.errstate(divide="ignore", invalid="ignore"):
        aicc = n * np.log(rss / n) + 2.0 * k + 2.0 * k * (k + 1.0) / (n - k - 1.0)
    aicc = np.where((n - k - 1.0) > 0, aicc, np.inf)
    best = int(np.argmin(aicc))
    return {"alphas": alphas, "coefs": coefs, "aicc": aicc, "best": best, "coef": coefs[:, best], "n": n}


def quintile_weights(signal: np.ndarray, size: np.ndarray, quantiles: int, gross_per_leg: float = GROSS_PER_LEG,
                     min_names: int = MIN_CROSS_SECTION) -> np.ndarray:
    """Long the top ``1/quantiles`` of the signal, short the bottom, each leg value-weighted by ``size``.

    Position ``p`` (0-based, ascending signal, ties by column order) is in group ``floor(p * q / n)``.  Returns zeros
    when fewer than ``min_names`` coins have a signal.
    """
    out = np.zeros(signal.shape[0], dtype=float)
    ok = np.flatnonzero(np.isfinite(signal) & np.isfinite(size) & (size > 0))
    n = len(ok)
    if n < max(min_names, quantiles):
        return out
    order = ok[np.argsort(signal[ok], kind="stable")]
    group = (np.arange(n) * quantiles) // n
    short = order[group == 0]
    long = order[group == quantiles - 1]
    out[long] = gross_per_leg * size[long] / size[long].sum()
    out[short] = -gross_per_leg * size[short] / size[short].sum()
    return out


# ------------------------------------------------------------------------------------------------ engine


def _fingerprint(data: Mapping[str, Any]) -> tuple:
    parts: list[Any] = []
    for key in ("close", "high", "low", "dollar_volume"):
        df = data[key]
        values = df.to_numpy(dtype=float)
        parts.append((key, df.shape, str(df.index[0]) if len(df) else "", str(df.index[-1]) if len(df) else "",
                      float(np.nansum(values)), int(np.isfinite(values).sum())))
    return tuple(parts)


class CTrendEngine:
    """Weekly CTREND pipeline for one data set; indicator ranks and weekly regressions are reused across params."""

    def __init__(self, data: Mapping[str, Any], *, min_bars: int = MIN_BARS, min_dollar_volume: float = MIN_DOLLAR_VOLUME,
                 min_cross_section: int = MIN_CROSS_SECTION):
        close = data["close"]
        idx = pd.DatetimeIndex(close.index)
        if len(idx) == 0:
            raise CTrendError("empty data")
        full = pd.date_range(idx[0], idx[-1], freq="D", tz=idx.tz)
        self.all_columns = list(close.columns)
        self.min_cross_section = int(min_cross_section)
        c = close.reindex(full)
        h = data["high"].reindex(full)
        lo = data["low"].reindex(full)
        v = data["dollar_volume"].reindex(full)
        self.index = full
        self.sunday_rows = np.flatnonzero(full.dayofweek == 6)
        if len(self.sunday_rows) < 3:
            raise CTrendError("fewer than 3 Sundays in the data")
        bars = c.notna().cumsum().to_numpy()[self.sunday_rows]
        dv30 = v.rolling(DOLLAR_VOLUME_WINDOW, min_periods=DOLLAR_VOLUME_MIN_PERIODS).mean().to_numpy()[self.sunday_rows]
        c_sun = c.to_numpy(dtype=float)[self.sunday_rows]
        with np.errstate(invalid="ignore"):
            eligible = (bars >= min_bars) & (dv30 >= min_dollar_volume) & np.isfinite(c_sun)
        ever = eligible.any(axis=0)
        self.keep = np.flatnonzero(ever)  # columns never eligible cannot influence any output
        self.columns = [self.all_columns[i] for i in self.keep]
        self._c, self._h, self._lo, self._v = (f.iloc[:, self.keep] for f in (c, h, lo, v))
        self.eligible = eligible[:, self.keep]
        self.size = dv30[:, self.keep]
        self.weeks = full[self.sunday_rows]
        self.n_weeks = len(self.weeks)
        self.c_sun = c_sun[:, self.keep]
        with np.errstate(invalid="ignore", divide="ignore"):
            fwd = np.full_like(self.c_sun, np.nan)
            fwd[:-1] = self.c_sun[1:] / self.c_sun[:-1] - 1.0
        self.ret_fwd = np.where(np.isfinite(fwd), fwd, np.nan)  # return of the week S_k -> S_{k+1}
        self._ranks: dict[float, np.ndarray] = {}
        self._reg: dict[float, tuple[np.ndarray, np.ndarray]] = {}
        self._signals: dict[tuple, dict[str, Any]] = {}

    # ---- ranks and weekly regressions

    def ranks(self, scale: float) -> np.ndarray:
        """(indicators, weeks, coins) ranks in [-0.5, 0.5] at each Sunday close."""
        key = round(float(scale), 10)
        if key not in self._ranks:
            z = np.full((N_INDICATORS, self.n_weeks, len(self.columns)), np.nan)
            for m, (name, frame) in enumerate(indicator_frames(self._c, self._h, self._lo, self._v, scale)):
                if name != INDICATOR_NAMES[m]:
                    raise CTrendError(f"indicator order mismatch: {name} vs {INDICATOR_NAMES[m]}")
                z[m] = rank_to_unit(frame.to_numpy(dtype=float)[self.sunday_rows], self.eligible)
            self._ranks[key] = z
        return self._ranks[key]

    def regressions(self, scale: float) -> tuple[np.ndarray, np.ndarray]:
        """Weekly WLS fits.  Row ``j`` is the regression of the week-``j`` return on the ranks at ``S_{j-1}``."""
        key = round(float(scale), 10)
        if key not in self._reg:
            z = self.ranks(scale)
            a = np.full((self.n_weeks, N_INDICATORS), np.nan)
            b = np.full((self.n_weeks, N_INDICATORS), np.nan)
            for j in range(1, self.n_weeks):
                y = self.ret_fwd[j - 1]
                mask = self.eligible[j - 1] & np.isfinite(y) & np.isfinite(self.size[j - 1]) & (self.size[j - 1] > 0)
                if mask.sum() < self.min_cross_section:
                    continue
                a[j], b[j] = wls_univariate(z[:, j - 1, :][:, mask], y[mask], self.size[j - 1][mask])
            self._reg[key] = (a, b)
        return self._reg[key]

    # ---- the signal

    def signals(self, params: Mapping[str, Any], only_week: int | None = None) -> dict[str, Any]:
        """Model output per week.  ``valid[k]``: the model could be estimated at ``S_k`` (full windows available).

        ``only_week`` fits the elastic net for that week only (validity is still determined for every week; it needs no
        model fit), used by the truncation test.
        """
        scale = float(params["indicator_window_scale"])
        window = int(params["rolling_window_weeks"])
        l1 = float(params["l1_ratio"])
        cache_key = (round(scale, 10), window, round(l1, 10), only_week)
        if cache_key in self._signals:
            return self._signals[cache_key]
        z = self.ranks(scale)
        a, b = self.regressions(scale)
        abar = pd.DataFrame(a).rolling(window, min_periods=window).mean().to_numpy()
        bbar = pd.DataFrame(b).rolling(window, min_periods=window).mean().to_numpy()
        n_w, n_c = self.n_weeks, len(self.columns)
        pair_rows = np.array([(self.eligible[j] & np.isfinite(self.ret_fwd[j])).sum() for j in range(n_w)])
        finite_abar = np.isfinite(abar).all(axis=1) & np.isfinite(bbar).all(axis=1)
        valid = np.zeros(n_w, dtype=bool)
        for k in range(window, n_w):  # single window: regressions k-M+1..k, pairs (ranks at S_j, return of week j+1)
            valid[k] = bool(finite_abar[k] and pair_rows[k - window:k].sum() > N_INDICATORS + 2)
        signal = np.full((n_w, n_c), np.nan)
        n_kept = np.zeros(n_w, dtype=int)
        kept_names: dict[int, list[str]] = {}
        training_weeks: dict[int, list[int]] = {}
        weeks = np.flatnonzero(valid) if only_week is None else ([only_week] if valid[only_week] else [])
        for k in weeks:
            rows_x, rows_y = [], []
            used: list[int] = []
            for j in range(k - window, k):  # ranks at S_j, return of week j + 1 <= k (all realised by S_k)
                y = self.ret_fwd[j]
                mask = self.eligible[j] & np.isfinite(y)
                if not mask.any():
                    continue
                f = abar[k][:, None] + bbar[k][:, None] * z[:, j, :]  # in-window fitted forecasts (window-averaged coefficients)
                rows_x.append(f[:, mask].T)
                rows_y.append(y[mask])
                used.append(j)
            training_weeks[k] = used
            fit = enet_aicc_path(np.vstack(rows_x), np.concatenate(rows_y), l1)
            keep = fit["coef"] > 0.0
            n_kept[k] = int(keep.sum())
            if not keep.any():
                continue
            kept_names[k] = [INDICATOR_NAMES[m] for m in np.flatnonzero(keep)]
            f_now = abar[k][:, None] + bbar[k][:, None] * z[:, k, :]
            signal[k] = np.where(self.eligible[k], f_now[keep].mean(axis=0), np.nan)
        result = {"signal": signal, "valid": valid, "n_kept": n_kept, "kept_names": kept_names,
                  "training_weeks": training_weeks}  # training_weeks[k]: ranks-week indices j (return of week j+1) used
        self._signals[cache_key] = result
        return result

    def weekly_weights(self, params: Mapping[str, Any], only_week: int | None = None) -> tuple[np.ndarray, np.ndarray]:
        """(weeks x coins) target weights decided at each Sunday close, and the validity mask of the weeks."""
        sig = self.signals(params, only_week)
        q = int(params["quantiles"])
        w = np.zeros((self.n_weeks, len(self.columns)))
        for k in np.flatnonzero(np.isfinite(sig["signal"]).any(axis=1)):
            w[k] = quintile_weights(sig["signal"][k], self.size[k], q, min_names=self.min_cross_section)
        return w, sig["valid"]

    def daily_weights(self, params: Mapping[str, Any], only_last_week: bool = False) -> pd.DataFrame:
        """Daily weights frame on the data's daily index (all input columns): row ``t`` = target decided at close ``t``.

        The Sunday weights are held through the following Saturday.  Rows before the first full signal are NaN; a
        week after that with no estimable model or no kept forecast holds zero weights (cash).
        """
        last = self.n_weeks - 1
        w, valid = self.weekly_weights(params, last if only_last_week else None)
        out = pd.DataFrame(np.nan, index=self.index, columns=self.all_columns, dtype=float)
        if not valid.any():
            return out
        start = last if only_last_week else int(np.flatnonzero(valid)[0])
        if only_last_week and not valid[last] and not (valid[:last].any()):
            return out
        rows = self.sunday_rows[start:]
        block = np.zeros((len(rows), len(self.all_columns)))
        block[:, self.keep] = w[start:]
        out.iloc[rows, :] = block
        first = rows[0]
        out.iloc[first:, :] = out.iloc[first:, :].ffill()
        return out

    def eligibility_frame(self) -> pd.DataFrame:
        """Daily boolean frame: coin eligible at the Sunday close whose decision is held on that row (all columns)."""
        block = np.zeros((self.n_weeks, len(self.all_columns)))
        block[:, self.keep] = self.eligible.astype(float)
        sunday = pd.DataFrame(block, index=self.weeks, columns=self.all_columns)
        return sunday.reindex(self.index).ffill().fillna(0.0) > 0.5


_ENGINES: dict[tuple, CTrendEngine] = {}
_ENGINE_ORDER: list[tuple] = []
_ENGINE_LIMIT = 3


def get_engine(data: Mapping[str, Any], **kwargs) -> CTrendEngine:
    key = (_fingerprint(data), tuple(sorted(kwargs.items())))
    if key not in _ENGINES:
        _ENGINES[key] = CTrendEngine(data, **kwargs)
        _ENGINE_ORDER.append(key)
        while len(_ENGINE_ORDER) > _ENGINE_LIMIT:
            _ENGINES.pop(_ENGINE_ORDER.pop(0), None)
    return _ENGINES[key]


def _engine_kwargs(params: Mapping[str, Any]) -> dict[str, Any]:
    """Test-only overrides (underscore keys); the registered values are the defaults."""
    out: dict[str, Any] = {}
    for key, name in (("_min_bars", "min_bars"), ("_min_dollar_volume", "min_dollar_volume"),
                      ("_min_cross_section", "min_cross_section")):
        if key in params:
            out[name] = params[key]
    return out


def ctrend_weights(data: Mapping[str, Any], params: Mapping[str, Any]) -> pd.DataFrame:
    """Daily weights (dates x all input symbols) of the CTREND long-short book.

    ``params['_only_last_week']`` (truncation test only) computes just the final Sunday's model; the row it yields is
    identical to the full pipeline's because the model at ``S_k`` never looks past ``S_k``.
    """
    merged = {**DEFAULT_PARAMS, **dict(params)}
    only_last = bool(merged.get("_only_last_week", False))
    # truncated data sets are used once: build a throw-away engine so the main engine stays in the cache
    engine = CTrendEngine(data, **_engine_kwargs(merged)) if only_last else get_engine(data, **_engine_kwargs(merged))
    return engine.daily_weights(merged, only_last_week=only_last)


def ctrend_weights_last_week(data: Mapping[str, Any], params: Mapping[str, Any]) -> pd.DataFrame:
    return ctrend_weights(data, {**dict(params), "_only_last_week": True})


def eligible_mask_daily(data: Mapping[str, Any], params: Mapping[str, Any] | None = None) -> pd.DataFrame:
    """Daily eligibility of each coin for the week held on that row (hold of the last Sunday's eligibility)."""
    merged = {**DEFAULT_PARAMS, **dict(params or {})}
    return get_engine(data, **_engine_kwargs(merged)).eligibility_frame()


def paper_cost_scenarios(weights: pd.DataFrame, returns: pd.DataFrame,
                         scenarios_bps: Sequence[tuple[float, float]] = ((30.0, 40.0), (40.0, 50.0))) -> dict[str, Any]:
    """Descriptive: daily net return series with the paper's one-way costs on the long and the short leg turnover.

    Cost = long-leg turnover * c_long + short-leg turnover * c_short (basis points, one way).  Returns the series per
    scenario (callers summarise them) plus the mean daily turnover of each leg.
    """
    wp = weights.shift(1)
    valid = wp.notna().any(axis=1)
    if not valid.any():
        return {"series": {}, "mean_daily_turnover_long": None, "mean_daily_turnover_short": None}
    wp = wp.loc[valid.idxmax():].fillna(0.0)
    rets = returns.reindex(index=wp.index, columns=wp.columns).fillna(0.0)
    gross = (wp * rets).sum(axis=1)
    long_w, short_w = wp.clip(lower=0.0), (-wp).clip(lower=0.0)
    t_long = long_w.diff().abs().sum(axis=1)
    t_short = short_w.diff().abs().sum(axis=1)
    t_long.iloc[0], t_short.iloc[0] = float(long_w.iloc[0].sum()), float(short_w.iloc[0].sum())
    series = {f"{int(cl)}/{int(cs)}": gross - t_long * cl / 1e4 - t_short * cs / 1e4 for cl, cs in scenarios_bps}
    return {"series": series, "mean_daily_turnover_long": float(t_long.mean()),
            "mean_daily_turnover_short": float(t_short.mean())}
