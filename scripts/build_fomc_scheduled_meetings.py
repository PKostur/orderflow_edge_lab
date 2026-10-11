"""Build config/fomc_scheduled_meetings_1994_2026.json from federalreserve.gov.

1994-2020: https://www.federalreserve.gov/monetarypolicy/fomchistoricalYYYY.htm (one page per year)
2021-2026: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm

Day 0 of a meeting is the decision day (the second day of a two-day meeting).  Conference calls, unscheduled meetings,
notation votes and cancelled meetings are not scheduled meetings and are listed under ``excluded`` with the reason.
Data file only: no strategy logic here.  Usage: PYTHONPATH=src .venv/Scripts/python scripts/build_fomc_scheduled_meetings.py
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "config" / "fomc_scheduled_meetings_1994_2026.json"
BASE = "https://www.federalreserve.gov/monetarypolicy/"
CALENDAR_URL = BASE + "fomccalendars.htm"
MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
     "November", "December"])}
ABBR = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6, "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10,
        "Nov": 11, "Dec": 12}
# Documented one-off exceptions on the historical pages.
KNOWN_NON_MEETINGS = {
    date(2003, 9, 15): "pre-meeting session of the 2003-09-16 meeting (no policy statement; decision day is 2003-09-16)",
}


def month_number(name: str) -> int:
    name = name.strip()
    return MONTHS[name] if name in MONTHS else ABBR[name[:3]]


def decision_day(year: int, month_text: str, day_text: str) -> date:
    """Decision day = last day of the range; for ``A/B d1-d2`` the month is B (the later month)."""
    month = month_number(month_text.split("/")[-1])
    last = day_text.replace("*", "").strip().split("-")[-1]
    return date(year, month, int(last))


def parse_heading_date(body: str, year: int) -> date:
    """Decision day of a historical-page heading body (the part before `` - YYYY``).

    Forms: ``January 28-29 Meeting``, ``March 18 Meeting``, ``April/May 30-1 Meeting`` and the cross-month
    ``January 31-February 1 Meeting`` / ``June 30-July 1 Meeting`` (decision day = the second day, in the later month).
    """
    cross = re.match(r"^([A-Za-z]+)\s+\d+\s*-\s*([A-Za-z]+)\s+(\d+)", body)
    if cross:
        return date(year, month_number(cross.group(2)), int(cross.group(3)))
    simple = re.match(r"^([A-Za-z/]+)\s+(\d+(?:-\d+)?)", body)
    if not simple:
        raise ValueError(f"unparseable heading: {body}")
    return decision_day(year, simple.group(1), simple.group(2))


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def parse_historical_year(html: str, year: int) -> tuple[list[date], list[dict]]:
    meetings: list[date] = []
    excluded: list[dict] = []
    for match in re.finditer(r"<h5[^>]*>(.*?)</h5>", html, re.S):
        heading = strip_tags(match.group(1))
        m = re.match(r"^(.*?) - (\d{4})$", heading)
        if not m or int(m.group(2)) != year:
            continue
        body = m.group(1)
        lowered = body.lower()
        reason = None
        for key, label in (("conference call", "conference call"), ("unscheduled", "unscheduled"),
                           ("notation vote", "notation vote"), ("cancelled", "cancelled")):
            if key in lowered:
                reason = label
                break
        d = parse_heading_date(body, year)
        if reason is None and d in KNOWN_NON_MEETINGS:
            excluded.append({"date": d.isoformat(), "heading": heading, "reason": KNOWN_NON_MEETINGS[d]})
        elif reason is not None:
            excluded.append({"date": d.isoformat(), "heading": heading, "reason": reason})
        else:
            meetings.append(d)
    return meetings, excluded


def parse_calendar(html: str) -> dict[int, tuple[list[date], list[dict]]]:
    out: dict[int, tuple[list[date], list[dict]]] = {}
    parts = re.split(r"<h4[^>]*>.*?(\d{4}) FOMC Meetings.*?</h4>", html, flags=re.S)
    for k in range(1, len(parts), 2):
        year = int(parts[k])
        body = parts[k + 1]
        meetings: list[date] = []
        excluded: list[dict] = []
        for m in re.finditer(r'fomc-meeting__month[^>]*>(.*?)</div>\s*<div[^>]*fomc-meeting__date[^>]*>(.*?)</div>',
                             body, re.S):
            month_text, date_text = strip_tags(m.group(1)), strip_tags(m.group(2))
            if "notation vote" in date_text.lower():
                d = decision_day(year, month_text, re.sub(r"\(.*?\)", "", date_text))
                excluded.append({"date": d.isoformat(), "heading": f"{month_text} {date_text}", "reason": "notation vote"})
            else:
                meetings.append(decision_day(year, month_text, date_text))
        out[year] = (meetings, excluded)
    return out


def main() -> int:
    years: dict[str, dict] = {}
    for year in range(1994, 2021):
        url = f"{BASE}fomchistorical{year}.htm"
        meetings, excluded = parse_historical_year(fetch(url), year)
        years[str(year)] = {"source_url": url, "meetings": [d.isoformat() for d in sorted(meetings)],
                            "excluded": sorted(excluded, key=lambda e: e["date"])}
    calendar = parse_calendar(fetch(CALENDAR_URL))
    for year in range(2021, 2027):
        meetings, excluded = calendar[year]
        years[str(year)] = {"source_url": CALENDAR_URL, "meetings": [d.isoformat() for d in sorted(meetings)],
                            "excluded": sorted(excluded, key=lambda e: e["date"])}
    # 2020-03-17/18 was cancelled and replaced by the unscheduled 2020-03-15 meeting: not a held scheduled meeting.
    for year, info in years.items():
        n = len(info["meetings"])
        if n != 8:
            print(f"WARNING: {year} has {n} scheduled meetings", file=sys.stderr)
    payload = {
        "schema_version": 1,
        "id": "fomc-scheduled-meetings-1994-2026",
        "status": "DATA",
        "description": ("Scheduled FOMC meetings, day 0 = decision day (second day of two-day meetings). Conference calls, "
                        "unscheduled meetings, notation votes and cancelled meetings are excluded (listed per year)."),
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "sources": {"historical": BASE + "fomchistoricalYYYY.htm (1994-2020)", "calendar": CALENDAR_URL + " (2021-2026)"},
        "years": years,
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    total = sum(len(v["meetings"]) for v in years.values())
    print(f"wrote {OUT} with {total} scheduled meetings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
