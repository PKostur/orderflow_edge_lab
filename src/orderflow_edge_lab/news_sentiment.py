"""news-sentiment-v1 (config/news_sentiment_v1.json): collect public news/Reddit RSS, tag coins, score with a frozen
word list, keep an append-only ledger and aggregate daily sentiment. Observational only; no trading."""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

DEFAULT_CONFIG = Path("config/news_sentiment_v1.json")
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(el: ET.Element | None) -> str:
    return "" if el is None else "".join(el.itertext())


def _parse_time(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def clean(text: str, limit: int | None = None) -> str:
    out = _WS.sub(" ", html.unescape(_TAG.sub(" ", text or ""))).strip()
    return out[:limit] if limit else out


def parse_feed(xml_bytes: bytes, source: str, kind: str, fetched_utc: str) -> list[dict[str, Any]]:
    """RSS 2.0 <item> and Atom <entry> -> item dicts (title, summary, link, published_utc)."""
    root = ET.fromstring(xml_bytes)
    items = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        fields: dict[str, Any] = {}
        for ch in el:
            name = _local(ch.tag)
            if name == "title":
                fields["title"] = clean(_text(ch))
            elif name == "link":
                fields.setdefault("link", (ch.get("href") or _text(ch)).strip())
            elif name in ("description", "summary", "content", "encoded") and "summary" not in fields:
                fields["summary"] = clean(_text(ch), 400)
            elif name in ("pubDate", "published", "updated", "date") and "published_utc" not in fields:
                fields["published_utc"] = _parse_time(_text(ch))
        if not fields.get("title"):
            continue
        key = hashlib.sha256(f"{source}|{fields.get('link') or fields['title']}".encode()).hexdigest()
        items.append({"id": key, "source": source, "kind": kind, "title": fields["title"], "summary": fields.get("summary", ""),
                      "link": fields.get("link", ""), "published_utc": fields.get("published_utc") or fetched_utc,
                      "fetched_utc": fetched_utc})
    return items


class Scorer:
    def __init__(self, cfg: Mapping[str, Any]):
        sc = cfg["scoring"]
        self.pos = self._phrases(sc["positive"])
        self.neg = self._phrases(sc["negative"])
        self.negators = [tuple(n.lower().split()) for n in sc["negators"]]
        tag = cfg["coin_tagging"]
        self.names = {c: [re.compile(r"(?<![\w$])" + re.escape(n.lower()) + r"(?!\w)") for n in ns] for c, ns in tag["names"].items()}
        self.ambiguous = set(tag["ambiguous_tickers"])
        self.tickers = sorted({s.replace("_USDT", "") for s in tag.get("_symbols", [])} | set(tag["names"]))

    @staticmethod
    def _phrases(words: Iterable[str]) -> list[tuple[str, ...]]:
        return sorted({tuple(w.lower().split()) for w in words}, key=len, reverse=True)

    def score(self, text: str) -> tuple[float, int, int]:
        toks = re.findall(r"[a-z0-9$'.-]+", text.lower())
        toks = [t.strip(".'") for t in toks]
        pos = neg = 0
        i = 0
        while i < len(toks):
            hit = None
            for lex, sign in ((self.pos, 1), (self.neg, -1)):
                for ph in lex:
                    if tuple(toks[i:i + len(ph)]) == ph:
                        hit = (sign, len(ph))
                        break
                if hit:
                    break
            if hit:
                sign, n = hit
                window = toks[max(0, i - 3):i]
                if any(tuple(window[j:j + len(ng)]) == ng for ng in self.negators for j in range(len(window))):
                    sign = -sign
                pos += sign > 0
                neg += sign < 0
                i += n
            else:
                i += 1
        return (pos - neg) / (pos + neg + 1), pos, neg

    def coins(self, text: str) -> list[str]:
        low = text.lower()
        found = set()
        for c, pats in self.names.items():
            if any(p.search(low) for p in pats):
                found.add(c)
        for t in self.tickers:
            if re.search(r"\$" + re.escape(t) + r"\b", text, flags=re.I):
                found.add(t)
            elif len(t) >= 3 and t not in self.ambiguous and re.search(r"(?<![\w$])" + re.escape(t) + r"(?![\w])", text):
                found.add(t)
        return sorted(found)


def load_config(path: Path | str = DEFAULT_CONFIG, universe_path: str = "config/multi_premia_blend_v1.json") -> dict[str, Any]:
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    cfg["coin_tagging"]["_symbols"] = json.loads(Path(universe_path).read_text(encoding="utf-8"))["symbols"]
    return cfg


def enrich(items: list[dict[str, Any]], scorer: Scorer) -> list[dict[str, Any]]:
    for it in items:
        text = f"{it['title']}. {it['summary']}"
        s, p, n = scorer.score(text)
        it.update(score=round(s, 6), pos=p, neg=n, coins=scorer.coins(text))
    return items


def merge(prior: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {it["id"] for it in prior}
    out = list(prior) + [it for it in new if it["id"] not in seen]
    return sorted(out, key=lambda it: (it["published_utc"], it["id"]))


def daily_aggregates(items: list[dict[str, Any]]) -> dict[str, Any]:
    market: dict[str, dict[str, Any]] = {}
    coins: dict[str, dict[str, dict[str, Any]]] = {}
    for it in items:
        day = it["published_utc"][:10]
        m = market.setdefault(day, {"n": 0, "sum": 0.0, "news_n": 0, "news_sum": 0.0, "social_n": 0, "social_sum": 0.0})
        m["n"] += 1
        m["sum"] += it["score"]
        m[f"{it['kind']}_n"] += 1
        m[f"{it['kind']}_sum"] += it["score"]
        for c in it["coins"]:
            d = coins.setdefault(c, {}).setdefault(day, {"n": 0, "sum": 0.0})
            d["n"] += 1
            d["sum"] += it["score"]
    fmt = lambda s, n: round(s / n, 6) if n else None  # noqa: E731
    return {
        "market": {d: {"items": v["n"], "score": fmt(v["sum"], v["n"]), "news_items": v["news_n"], "news_score": fmt(v["news_sum"], v["news_n"]),
                       "social_items": v["social_n"], "social_score": fmt(v["social_sum"], v["social_n"])} for d, v in sorted(market.items())},
        "coins": {c: {d: {"mentions": v["n"], "score_sum": round(v["sum"], 6)} for d, v in sorted(days.items())} for c, days in sorted(coins.items())},
    }


def fetch(url: str, user_agent: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def collect(cfg: Mapping[str, Any], *, now: datetime | None = None, fetcher=fetch, pause: float | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    fetched = now.isoformat()
    src = cfg["sources"]
    pause = src["pause_between_requests_seconds"] if pause is None else pause
    items, status = [], {}
    for kind, group in (("news", src["news_rss"]), ("social", src["social_rss"])):
        for name, url in group.items():
            try:
                got = parse_feed(fetcher(url, src["user_agent"]), name, kind, fetched)
                items += got
                status[name] = {"ok": True, "items": len(got)}
            except Exception as exc:  # a failed source is recorded and skipped
                status[name] = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
            if pause:
                time.sleep(pause)
    return items, status


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Collect and score public crypto news/Reddit RSS (news-sentiment-v1).")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--prior-ledger", default=None)
    p.add_argument("--output-dir", required=True)
    a = p.parse_args(argv)
    cfg = load_config(a.config)
    prior = []
    if a.prior_ledger and Path(a.prior_ledger).exists():
        prior = [json.loads(line) for line in Path(a.prior_ledger).read_text(encoding="utf-8").splitlines() if line.strip()]
    new, status = collect(cfg)
    ledger = merge(prior, enrich(new, Scorer(cfg)))
    out = Path(a.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ledger.jsonl").write_text("".join(json.dumps(it, ensure_ascii=False, sort_keys=True) + "\n" for it in ledger), encoding="utf-8")
    agg = daily_aggregates(ledger)
    report = {"protocol": cfg["protocol_id"], "run_utc": datetime.now(timezone.utc).isoformat(), "sources": status,
              "items_total": len(ledger), "items_new": len(ledger) - len(prior), "first_item_utc": ledger[0]["published_utc"] if ledger else None,
              "ledger_sha256": hashlib.sha256((out / "ledger.jsonl").read_bytes()).hexdigest(), "claims": cfg["claims"]}
    (out / "daily.json").write_text(json.dumps(agg, indent=1, sort_keys=True), encoding="utf-8")
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"items_total": report["items_total"], "items_new": report["items_new"],
                      "failed_sources": sorted(k for k, v in status.items() if not v["ok"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
