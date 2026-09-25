from __future__ import annotations

from datetime import datetime
import json
import math
import time
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class OkxMarketDataHistoryError(ValueError):
    pass


_MARKET_DATA_HISTORY_PATH = "/api/v5/public/market-data-history"
_FUNDING_RATE_MODULE = "3"
_ALLOWED_AGGREGATIONS = {"daily", "monthly"}


def _timestamp_ms(value: str | int | float) -> int:
    if isinstance(value, bool):
        raise OkxMarketDataHistoryError("boolean timestamp is invalid")
    if isinstance(value, (int, float)):
        out = int(value)
        if out <= 0:
            raise OkxMarketDataHistoryError("timestamp must be positive")
        return out
    text = str(value).strip()
    if not text:
        raise OkxMarketDataHistoryError("timestamp is required")
    if text.isdigit():
        out = int(text)
        if out <= 0:
            raise OkxMarketDataHistoryError("timestamp must be positive")
        return out
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise OkxMarketDataHistoryError("ISO timestamp must include timezone")
    return int(parsed.timestamp() * 1000)


def _get_json(url: str, *, timeout: float = 30.0) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "orderflow-edge-lab/1.0",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise OkxMarketDataHistoryError(
                f"OKX historical market data returned HTTP {response.status}"
            )
        raw = response.read(8_000_000)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OkxMarketDataHistoryError(
            "OKX historical market data response is not valid JSON"
        ) from exc
    if not isinstance(payload, dict) or str(payload.get("code")) != "0":
        raise OkxMarketDataHistoryError(
            f"OKX historical market data response failed: {payload}"
        )
    data = payload.get("data")
    if not isinstance(data, list):
        raise OkxMarketDataHistoryError(
            "OKX historical market data response data must be a list"
        )
    return payload


def fetch_okx_historical_funding_manifest(
    *,
    aggregation: str,
    begin: str | int | float,
    end: str | int | float,
    instrument_families: list[str] | None = None,
    any_instrument: bool = False,
    rest_base: str = "https://www.okx.com",
    request_pause_seconds: float = 0.0,
) -> dict[str, Any]:
    aggregation = str(aggregation).lower()
    if aggregation not in _ALLOWED_AGGREGATIONS:
        raise OkxMarketDataHistoryError(
            f"unsupported date aggregation: {aggregation}"
        )
    begin_ms = _timestamp_ms(begin)
    end_ms = _timestamp_ms(end)
    if end_ms < begin_ms:
        raise OkxMarketDataHistoryError("end must not be before begin")

    if any_instrument:
        if instrument_families:
            raise OkxMarketDataHistoryError(
                "ANY cannot be combined with explicit instrument families"
            )
        family_value = "ANY"
    else:
        families = [str(value).strip() for value in (instrument_families or [])]
        if not families or any(not value for value in families):
            raise OkxMarketDataHistoryError(
                "at least one instrument family is required"
            )
        if len(families) > 10:
            raise OkxMarketDataHistoryError(
                "at most ten instrument families are supported per query"
            )
        family_value = ",".join(families)

    if aggregation == "daily" and family_value != "ANY":
        raise OkxMarketDataHistoryError(
            "daily funding archive query requires instFamilyList=ANY"
        )

    query = urlencode(
        {
            "module": _FUNDING_RATE_MODULE,
            "instType": "SWAP",
            "dateAggrType": aggregation,
            "begin": str(begin_ms),
            "end": str(end_ms),
            "instFamilyList": family_value,
        }
    )
    endpoint = rest_base.rstrip("/") + _MARKET_DATA_HISTORY_PATH
    payload = _get_json(f"{endpoint}?{query}")
    if request_pause_seconds > 0:
        time.sleep(float(request_pause_seconds))

    manifests: list[dict[str, Any]] = []
    for group in payload["data"]:
        if not isinstance(group, Mapping):
            continue
        raw_details = group.get("details")
        if not isinstance(raw_details, list):
            continue
        for detail in raw_details:
            if not isinstance(detail, Mapping):
                continue
            raw_groups = detail.get("groupDetails")
            if not isinstance(raw_groups, list):
                continue
            for item in raw_groups:
                if not isinstance(item, Mapping):
                    continue
                url = str(item.get("url") or "").strip()
                filename = str(item.get("filename") or "").strip()
                raw_ts = item.get("dataTs", item.get("dateTs"))
                try:
                    data_ts = int(raw_ts) if raw_ts not in (None, "") else None
                except (TypeError, ValueError):
                    data_ts = None
                raw_size = item.get("sizeMB")
                try:
                    size_mb = float(raw_size) if raw_size not in (None, "") else None
                except (TypeError, ValueError):
                    size_mb = None
                if size_mb is not None and not math.isfinite(size_mb):
                    size_mb = None
                manifests.append(
                    {
                        "inst_id": str(detail.get("instId") or ""),
                        "inst_family": str(detail.get("instFamily") or ""),
                        "inst_type": str(detail.get("instType") or ""),
                        "date_range_start": detail.get("dateRangeStart"),
                        "date_range_end": detail.get("dateRangeEnd"),
                        "filename": filename,
                        "data_ts": data_ts,
                        "size_mb": size_mb,
                        "url": url,
                    }
                )

    return {
        "schema_version": 1,
        "source": "OKX public historical market data",
        "endpoint_path": _MARKET_DATA_HISTORY_PATH,
        "module": _FUNDING_RATE_MODULE,
        "instrument_type": "SWAP",
        "date_aggregation_type": aggregation,
        "begin_ms": begin_ms,
        "end_ms": end_ms,
        "inst_family_list": family_value,
        "manifest_count": len(manifests),
        "download_url_count": sum(bool(row["url"]) for row in manifests),
        "manifests": manifests,
    }


def build_okx_historical_funding_source_probe(
    config: Mapping[str, Any],
) -> dict[str, Any]:
    queries = config.get("queries")
    if not isinstance(queries, list) or not queries:
        raise OkxMarketDataHistoryError("probe config requires queries")

    rest_base = str(config["rest_base"])
    results: list[dict[str, Any]] = []
    all_files: dict[str, dict[str, Any]] = {}
    for index, query in enumerate(queries):
        if not isinstance(query, Mapping):
            raise OkxMarketDataHistoryError("query entries must be objects")
        result = fetch_okx_historical_funding_manifest(
            aggregation=str(query["aggregation"]),
            begin=query["begin"],
            end=query["end"],
            instrument_families=[
                str(value) for value in query.get("instrument_families", [])
            ],
            any_instrument=bool(query.get("any_instrument", False)),
            rest_base=rest_base,
            request_pause_seconds=float(
                config.get("request_pause_seconds", 0.25)
            ),
        )
        result["query_index"] = index
        results.append(result)
        for row in result["manifests"]:
            key = row["url"] or row["filename"]
            if key:
                all_files[key] = row

    url_count = sum(bool(row["url"]) for row in all_files.values())
    return {
        "schema_version": 1,
        "analysis": "okx_historical_funding_source_probe_v1",
        "probe_id": str(config["probe_id"]),
        "evidence_use": "engineering_source_discovery_only",
        "endpoint_path": _MARKET_DATA_HISTORY_PATH,
        "funding_module": _FUNDING_RATE_MODULE,
        "query_count": len(results),
        "queries": results,
        "unique_manifest_file_count": len(all_files),
        "unique_download_url_count": url_count,
        "source_available": url_count > 0,
        "claims": {
            "candidate_pnl_computed": False,
            "candidate_retested": False,
            "historical_result_repaired": False,
            "strategy_definition_changed": False,
            "candidate_promoted": False,
            "profitable_edge_established": False,
            "live_trading_authorized": False,
            "leverage_authorized": False,
        },
    }
