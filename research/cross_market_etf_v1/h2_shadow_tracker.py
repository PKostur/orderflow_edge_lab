#!/usr/bin/env python3
"""Prospective shadow tracker for ETF_H2_VWAP_REVERSION_CONTEXT_V1.

The candidate definition is frozen in H2_PROSPECTIVE_SHADOW_FREEZE.json.
This script intentionally rebuilds the signal history from raw bars so that
rolling context uses only information strictly available before each signal.

No trade dated before 2026-09-22 is ever written to the prospective ledger.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

UNIVERSE = ("SPY", "QQQ", "GLD", "USO")
HISTORY_START = date(2026, 6, 1)
SHADOW_START = date(2026, 9, 22)

SIGNAL_START = dtime(9, 50)
SIGNAL_END = dtime(11, 0)
SESSION_START = dtime(9, 30)
SESSION_END = dtime(15, 59)

ROLLING_RAW_SIGNALS = 10
PRIMARY_COST_BPS = 2.0
STRESS_COST_BPS = 4.0
SLEEVE_WEIGHT = 0.25

TARGET_TRADES = 20
TARGET_SESSIONS = 10
TARGET_CALENDAR_DAYS = 20


@dataclass(frozen=True)
class Bar:
    ticker: str
    ts_ms: int
    dt_et: datetime
    o: float
    h: float
    l: float
    c: float
    v: float
    vw: float


@dataclass(frozen=True)
class RawSignal:
    ticker: str
    session_date: date
    signal_dt: datetime
    direction: int
    entry_open: float
    exit_open: float
    gross_bps: float
    net2_bps: float
    net4_bps: float
    vwap_distance_bps: float
    signal_range_bps: float
    rel_volume20: float
    mfe_bps: float
    mae_bps: float


@dataclass(frozen=True)
class ShadowTrade:
    date: str
    ticker: str
    signal_et: str
    direction: int
    entry_open: float
    exit_open: float
    vwap_distance_bps: float
    rolling_vwap_distance_mean: float
    signal_range_bps: float
    rolling_signal_range_mean: float
    rel_volume20: float
    rolling_rel_volume20_mean: float
    net_bps_2: float
    net_bps_4: float
    mfe_bps: float
    mae_bps: float


def _daterange_month_chunks(start: date, end: date) -> Iterable[tuple[date, date]]:
    cur = start.replace(day=1)
    while cur <= end:
        if cur.month == 12:
            nxt = date(cur.year + 1, 1, 1)
        else:
            nxt = date(cur.year, cur.month + 1, 1)
        chunk_start = max(start, cur)
        chunk_end = min(end, nxt - timedelta(days=1))
        yield chunk_start, chunk_end
        cur = nxt


def _request_json(url: str, params: dict[str, object], api_key: str, retries: int = 5) -> dict:
    query = dict(params)
    query["apiKey"] = api_key
    full = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(query)
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": "orderflow-edge-lab/etf-shadow"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # network/rate-limit wrapper
            last_error = exc
            if attempt + 1 >= retries:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError(f"request failed: {last_error}")


def fetch_bars(
    ticker: str,
    start: date,
    end: date,
    api_key: str,
    base_url: str,
) -> list[Bar]:
    rows: dict[int, Bar] = {}
    for chunk_start, chunk_end in _daterange_month_chunks(start, end):
        path = (
            f"{base_url.rstrip('/')}/v2/aggs/ticker/{ticker}/range/1/minute/"
            f"{chunk_start.isoformat()}/{chunk_end.isoformat()}"
        )
        payload = _request_json(
            path,
            {"adjusted": "true", "sort": "asc", "limit": 50000},
            api_key,
        )
        while True:
            for r in payload.get("results", []) or []:
                ts = int(r["t"])
                dt_et = datetime.fromtimestamp(ts / 1000, tz=UTC).astimezone(NY)
                b = Bar(
                    ticker=ticker,
                    ts_ms=ts,
                    dt_et=dt_et,
                    o=float(r["o"]),
                    h=float(r["h"]),
                    l=float(r["l"]),
                    c=float(r["c"]),
                    v=float(r["v"]),
                    vw=float(r.get("vw", r["c"])),
                )
                rows[ts] = b

            next_url = payload.get("next_url")
            if not next_url:
                break
            payload = _request_json(next_url, {}, api_key)

    return [rows[k] for k in sorted(rows)]


def group_regular_session(bars: Sequence[Bar]) -> dict[date, dict[datetime, Bar]]:
    sessions: dict[date, dict[datetime, Bar]] = {}
    for b in bars:
        t = b.dt_et.time().replace(tzinfo=None)
        if SESSION_START <= t <= SESSION_END:
            sessions.setdefault(b.dt_et.date(), {})[b.dt_et.replace(second=0, microsecond=0)] = b
    return sessions


def minute_dt(day: date, hh: int, mm: int) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=NY)


def exact_window(
    by_time: dict[datetime, Bar],
    start: datetime,
    end: datetime,
) -> list[Bar] | None:
    out: list[Bar] = []
    cur = start
    while cur <= end:
        b = by_time.get(cur)
        if b is None:
            return None
        out.append(b)
        cur += timedelta(minutes=1)
    return out


def find_raw_h2_signal(ticker: str, day: date, by_time: dict[datetime, Bar]) -> RawSignal | None:
    open_dt = minute_dt(day, 9, 30)
    search_dt = minute_dt(day, 9, 50)
    search_end = minute_dt(day, 11, 0)

    cur = search_dt
    while cur <= search_end:
        # Frozen fail-closed rule: no missing exact minute from 09:30 through signal.
        from_open = exact_window(by_time, open_dt, cur)
        if from_open is None:
            cur += timedelta(minutes=1)
            continue

        # Frozen H2 sigma: 21 exact closes -> 20 exact log returns ending at signal.
        closes_window = exact_window(by_time, cur - timedelta(minutes=20), cur)
        if closes_window is None or len(closes_window) != 21:
            cur += timedelta(minutes=1)
            continue

        returns = [
            math.log(closes_window[i].c / closes_window[i - 1].c)
            for i in range(1, len(closes_window))
            if closes_window[i - 1].c > 0 and closes_window[i].c > 0
        ]
        if len(returns) != 20:
            cur += timedelta(minutes=1)
            continue

        sigma = statistics.stdev(returns)
        if not math.isfinite(sigma) or sigma <= 0:
            cur += timedelta(minutes=1)
            continue

        total_v = sum(b.v for b in from_open)
        if total_v <= 0:
            cur += timedelta(minutes=1)
            continue
        cumulative_vwap = sum(b.vw * b.v for b in from_open) / total_v
        signal_bar = by_time[cur]
        if cumulative_vwap <= 0 or signal_bar.c <= 0 or signal_bar.l <= 0:
            cur += timedelta(minutes=1)
            continue

        z = math.log(signal_bar.c / cumulative_vwap) / (sigma * math.sqrt(20.0))
        if z < 1.0 and z > -1.0:
            cur += timedelta(minutes=1)
            continue

        direction = -1 if z >= 1.0 else 1

        entry_dt = cur + timedelta(minutes=1)
        exit_dt = cur + timedelta(minutes=11)
        entry_bar = by_time.get(entry_dt)
        exit_bar = by_time.get(exit_dt)
        if entry_bar is None or exit_bar is None or entry_bar.o <= 0:
            return None

        volume20 = exact_window(by_time, cur - timedelta(minutes=19), cur)
        if volume20 is None or len(volume20) != 20:
            return None
        mean_v20 = statistics.fmean(b.v for b in volume20)
        if mean_v20 <= 0:
            return None

        vwap_distance = abs(math.log(signal_bar.c / cumulative_vwap)) * 10000.0
        signal_range = (signal_bar.h / signal_bar.l - 1.0) * 10000.0
        rel_volume20 = signal_bar.v / mean_v20

        gross_bps = direction * (exit_bar.o / entry_bar.o - 1.0) * 10000.0

        # Position is closed at the OPEN of exit_dt. Therefore excursion bars end
        # one minute earlier; the exit bar's high/low would be post-exit information.
        held_bars = exact_window(by_time, entry_dt, exit_dt - timedelta(minutes=1))
        if held_bars is None:
            return None

        if direction == 1:
            mfe = max((b.h / entry_bar.o - 1.0) * 10000.0 for b in held_bars)
            mae = max((1.0 - b.l / entry_bar.o) * 10000.0 for b in held_bars)
        else:
            mfe = max((1.0 - b.l / entry_bar.o) * 10000.0 for b in held_bars)
            mae = max((b.h / entry_bar.o - 1.0) * 10000.0 for b in held_bars)

        return RawSignal(
            ticker=ticker,
            session_date=day,
            signal_dt=cur,
            direction=direction,
            entry_open=entry_bar.o,
            exit_open=exit_bar.o,
            gross_bps=gross_bps,
            net2_bps=gross_bps - PRIMARY_COST_BPS,
            net4_bps=gross_bps - STRESS_COST_BPS,
            vwap_distance_bps=vwap_distance,
            signal_range_bps=signal_range,
            rel_volume20=rel_volume20,
            mfe_bps=mfe,
            mae_bps=mae,
        )

    return None


def mean_factor(raw_history: Sequence[RawSignal], attr: str) -> float:
    vals = [float(getattr(x, attr)) for x in raw_history[-ROLLING_RAW_SIGNALS:]]
    return statistics.fmean(vals)


def build_shadow_trades(
    sessions_by_ticker: dict[str, dict[date, dict[datetime, Bar]]],
    end_date: date,
) -> list[ShadowTrade]:
    raw_history: dict[str, list[RawSignal]] = {t: [] for t in UNIVERSE}
    trades: list[ShadowTrade] = []

    all_days = sorted(
        {
            d
            for sessions in sessions_by_ticker.values()
            for d in sessions.keys()
            if HISTORY_START <= d <= end_date
        }
    )

    for day in all_days:
        for ticker in UNIVERSE:
            by_time = sessions_by_ticker.get(ticker, {}).get(day)
            if not by_time:
                continue

            raw = find_raw_h2_signal(ticker, day, by_time)
            if raw is None:
                continue

            history = raw_history[ticker]
            if len(history) >= ROLLING_RAW_SIGNALS:
                vd_mean = mean_factor(history, "vwap_distance_bps")
                sr_mean = mean_factor(history, "signal_range_bps")
                rv_mean = mean_factor(history, "rel_volume20")

                context_pass = (
                    raw.vwap_distance_bps > vd_mean
                    and raw.signal_range_bps > sr_mean
                    and raw.rel_volume20 > rv_mean
                )

                if context_pass and day >= SHADOW_START:
                    trades.append(
                        ShadowTrade(
                            date=day.isoformat(),
                            ticker=ticker,
                            signal_et=raw.signal_dt.isoformat(),
                            direction=raw.direction,
                            entry_open=raw.entry_open,
                            exit_open=raw.exit_open,
                            vwap_distance_bps=raw.vwap_distance_bps,
                            rolling_vwap_distance_mean=vd_mean,
                            signal_range_bps=raw.signal_range_bps,
                            rolling_signal_range_mean=sr_mean,
                            rel_volume20=raw.rel_volume20,
                            rolling_rel_volume20_mean=rv_mean,
                            net_bps_2=raw.net2_bps,
                            net_bps_4=raw.net4_bps,
                            mfe_bps=raw.mfe_bps,
                            mae_bps=raw.mae_bps,
                        )
                    )

            # Strictly after evaluating the current signal, so current factors can
            # never leak into their own rolling benchmark.
            history.append(raw)

    return trades


def profit_factor(values: Sequence[float]) -> float | None:
    pos = sum(x for x in values if x > 0)
    neg = abs(sum(x for x in values if x < 0))
    if neg == 0:
        return None if pos == 0 else math.inf
    return pos / neg


def equity_rows(trades: Sequence[ShadowTrade]) -> list[dict[str, object]]:
    daily: dict[str, list[ShadowTrade]] = {}
    for t in trades:
        daily.setdefault(t.date, []).append(t)

    equity = 1.0
    peak = 1.0
    cumulative_bps = 0.0
    out: list[dict[str, object]] = []

    for d in sorted(daily):
        day_trades = daily[d]
        day_bps = sum(t.net_bps_2 for t in day_trades)
        cumulative_bps += day_bps
        day_return = SLEEVE_WEIGHT * sum(t.net_bps_2 / 10000.0 for t in day_trades)
        equity *= 1.0 + day_return
        peak = max(peak, equity)
        dd = equity / peak - 1.0
        out.append(
            {
                "date": d,
                "trades": len(day_trades),
                "day_net_bps": day_bps,
                "constant_notional_cumulative_bps": cumulative_bps,
                "portfolio_equity": equity,
                "portfolio_return_pct": (equity - 1.0) * 100.0,
                "portfolio_drawdown_pct": dd * 100.0,
            }
        )
    return out


def summarize(trades: Sequence[ShadowTrade], through: date) -> dict[str, object]:
    net2 = [t.net_bps_2 for t in trades]
    net4 = [t.net_bps_4 for t in trades]
    wins = [x for x in net2 if x > 0]
    losses = [x for x in net2 if x <= 0]
    eq = equity_rows(trades)

    positive_total = sum(wins)
    sorted_wins = sorted(wins, reverse=True)
    top1_share = (sorted_wins[0] / positive_total) if positive_total > 0 and sorted_wins else None
    top3_share = (sum(sorted_wins[:3]) / positive_total) if positive_total > 0 else None

    by_ticker: dict[str, dict[str, object]] = {}
    for ticker in UNIVERSE:
        xs = [t for t in trades if t.ticker == ticker]
        vals = [t.net_bps_2 for t in xs]
        positive = sum(x for x in vals if x > 0)
        by_ticker[ticker] = {
            "trades": len(xs),
            "cumulative_net_bps_2": sum(vals),
            "mean_net_bps_2": statistics.fmean(vals) if vals else None,
            "win_rate_pct_2": 100.0 * sum(x > 0 for x in vals) / len(vals) if vals else None,
            "share_of_positive_pnl": positive / positive_total if positive_total > 0 else None,
        }

    avg_win = statistics.fmean(wins) if wins else None
    avg_loss = statistics.fmean(losses) if losses else None
    break_even_wr = None
    if avg_win is not None and avg_loss is not None and avg_win + abs(avg_loss) > 0:
        break_even_wr = 100.0 * abs(avg_loss) / (avg_win + abs(avg_loss))

    distinct_sessions = len({t.date for t in trades})
    calendar_days = max(0, (through - SHADOW_START).days + 1)
    target_met = (
        len(trades) >= TARGET_TRADES
        and distinct_sessions >= TARGET_SESSIONS
        and calendar_days >= TARGET_CALENDAR_DAYS
    )

    return {
        "candidate_id": "ETF_H2_VWAP_REVERSION_CONTEXT_V1",
        "shadow_start_date": SHADOW_START.isoformat(),
        "through_date": through.isoformat(),
        "status": "READY_FOR_REVIEW" if target_met else "ACCUMULATING",
        "observation_target": {
            "minimum_filtered_trades": TARGET_TRADES,
            "minimum_distinct_sessions": TARGET_SESSIONS,
            "minimum_calendar_days": TARGET_CALENDAR_DAYS,
            "target_met": target_met,
        },
        "trades": len(trades),
        "distinct_sessions": distinct_sessions,
        "calendar_days_elapsed": calendar_days,
        "constant_notional_cumulative_bps_2": sum(net2),
        "constant_notional_cumulative_bps_4": sum(net4),
        "mean_net_bps_2": statistics.fmean(net2) if net2 else None,
        "mean_net_bps_4": statistics.fmean(net4) if net4 else None,
        "win_rate_pct_2": 100.0 * len(wins) / len(net2) if net2 else None,
        "average_net_win_bps_2": avg_win,
        "average_net_loss_bps_2": avg_loss,
        "break_even_win_rate_pct": break_even_wr,
        "profit_factor_2": profit_factor(net2),
        "average_mfe_bps": statistics.fmean([t.mfe_bps for t in trades]) if trades else None,
        "average_mae_bps": statistics.fmean([t.mae_bps for t in trades]) if trades else None,
        "portfolio_model": "four fixed 25% sleeves; unused sleeves cash",
        "portfolio_compounded_return_pct": ((eq[-1]["portfolio_equity"] - 1.0) * 100.0) if eq else 0.0,
        "portfolio_max_drawdown_pct": min((r["portfolio_drawdown_pct"] for r in eq), default=0.0),
        "positive_pnl_concentration": {
            "largest_trade_share": top1_share,
            "top_three_share": top3_share,
            "ticker": by_ticker,
        },
        "diagnostic_convention": {
            "mfe_mae_window": "entry bar through the minute immediately before the exit bar; exit is at exit-bar open",
            "backfill_before_shadow_start": False,
        },
        "live_or_leverage_authorized": False,
    }


def write_csv(path: Path, rows: Sequence[dict[str, object]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--through", type=date.fromisoformat, default=date.today())
    p.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "shadow")
    p.add_argument("--base-url", default=os.environ.get("MASSIVE_BASE_URL", "https://api.massive.com"))
    p.add_argument("--allow-intraday", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.through < SHADOW_START:
        raise SystemExit(f"--through must be >= {SHADOW_START.isoformat()}")

    now_et = datetime.now(tz=NY)
    through = args.through
    if (
        not args.allow_intraday
        and through == now_et.date()
        and now_et.time().replace(tzinfo=None) < dtime(16, 5)
    ):
        through = through - timedelta(days=1)

    api_key = os.environ.get("MASSIVE_API_KEY")
    if not api_key:
        raise SystemExit("MASSIVE_API_KEY is required")

    sessions_by_ticker: dict[str, dict[date, dict[datetime, Bar]]] = {}
    for ticker in UNIVERSE:
        bars = fetch_bars(ticker, HISTORY_START, through, api_key, args.base_url)
        sessions_by_ticker[ticker] = group_regular_session(bars)

    trades = build_shadow_trades(sessions_by_ticker, through)

    if any(date.fromisoformat(t.date) < SHADOW_START for t in trades):
        raise AssertionError("pre-shadow trade leaked into prospective ledger")

    trade_rows = [asdict(t) for t in trades]
    equity = equity_rows(trades)
    summary = summarize(trades, through)

    write_csv(
        args.output_dir / "H2_SHADOW_LEDGER.csv",
        trade_rows,
        list(ShadowTrade.__dataclass_fields__.keys()),
    )
    write_csv(
        args.output_dir / "H2_SHADOW_EQUITY.csv",
        equity,
        [
            "date",
            "trades",
            "day_net_bps",
            "constant_notional_cumulative_bps",
            "portfolio_equity",
            "portfolio_return_pct",
            "portfolio_drawdown_pct",
        ],
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "H2_SHADOW_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
