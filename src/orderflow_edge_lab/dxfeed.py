"""Bounded HTTPS diagnostics. Credentials stay in memory and are never returned."""
from datetime import datetime, timezone
import base64
import json
import math
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_ENDPOINT = "https://tools.dxfeed.com/webservice/rest/events.json"
DEFAULT_SYMBOL = "/NQ:XCME"
MAX_HISTORY_WINDOW_SECONDS = 600
QUOTE_RESPONSE_LIMIT_BYTES = 64_000
HISTORY_RESPONSE_LIMIT_BYTES = 2_000_000
DEPTH_RESPONSE_LIMIT_BYTES = 2_000_000
FUTURES_DEPTH_SOURCE = "AGGREGATE"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _validated_endpoint_symbol(endpoint: str, symbol: str) -> tuple[str, str]:
    parsed = urllib.parse.urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or any(c.isspace() for c in endpoint)
        or not symbol.strip()
        or any(c in symbol for c in "\r\n,")
    ):
        raise ValueError("invalid endpoint or symbol")
    parsed.port
    return endpoint, symbol.strip()


def _authorization(token: str | None, *, username: str | None, password: str | None) -> str:
    if token:
        if username or password or not token.strip() or any(c in token for c in "\r\n"):
            raise ValueError("invalid authentication")
        return f"Bearer {token}"
    if not username or not password or ":" in username or any(c in username + password for c in "\r\n"):
        raise ValueError("invalid authentication")
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode("ascii")


def _parse_bounded_history_window(from_time: str, to_time: str) -> tuple[str, str]:
    def parse(value: str) -> datetime:
        if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n"):
            raise ValueError("invalid history time")
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("history times must be timezone-aware")
        return parsed.astimezone(timezone.utc)

    start = parse(from_time)
    end = parse(to_time)
    seconds = (end - start).total_seconds()
    if seconds <= 0 or seconds > MAX_HISTORY_WINDOW_SECONDS:
        raise ValueError(f"history window must be >0 and <= {MAX_HISTORY_WINDOW_SECONDS} seconds")
    fmt = lambda value: value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return fmt(start), fmt(end)


def _open_bounded_json(request, endpoint: str, *, max_bytes: int):
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
            body = response.read(max_bytes + 1)
            status = response.status
    except urllib.error.HTTPError as exc:
        redirect_to_demo = False
        if 300 <= exc.code < 400:
            target = urllib.parse.urlsplit(urllib.parse.urljoin(endpoint, exc.headers.get("Location", "")))
            redirect_to_demo = target.hostname == "demo.dxfeed.com"
        exc.close()
        return None, None, {
            "http_status": exc.code,
            "error_type": "HTTPError",
            "transport_error": True,
            "redirect_to_public_demo": redirect_to_demo,
            "note": (
                "Redirect refused; credentials were not forwarded. Obtain the provider endpoint for an account test."
                if 300 <= exc.code < 400
                else "This endpoint rejected the request; other provider endpoints or entitlements are not tested."
            ),
        }
    except Exception as exc:
        return None, None, {
            "error_type": type(exc).__name__,
            "transport_error": True,
            "note": "Connection failed; credentials and server messages were not logged.",
        }

    if len(body) > max_bytes:
        return status, None, {"error_type": "ResponseTooLarge"}
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        return status, None, {"error_type": "InvalidJSON"}
    return status, payload, None


def _service_rejected(payload) -> bool:
    return isinstance(payload, dict) and payload.get("status") not in (None, "OK")


def probe_connection(endpoint, token, symbol, *, username=None, password=None):
    result = {
        "mode": "rest",
        "status": "failed",
        "account_entitlement_verified": False,
        "historical_access_verified": False,
        "quote_received": False,
        "quote_sizes_received": False,
        "research_eligibility": {
            "current_level1_bbo_prices": False,
            "current_level1_bbo_sizes": False,
            "CMF_H3_live_capture_component": False,
            "historical_quote_stream_verified": False,
        },
    }
    try:
        endpoint, symbol = _validated_endpoint_symbol(endpoint, symbol)
        authorization = _authorization(token, username=username, password=password)
        request = urllib.request.Request(
            endpoint
            + "?"
            + urllib.parse.urlencode(
                [("event", "Quote"), ("symbol", symbol), ("timeout", "3")]
            ),
            headers={
                "Authorization": authorization,
                "Accept": "application/json",
                "User-Agent": "orderflow-edge-lab/1.0",
            },
        )
    except (ValueError, TypeError, AttributeError):
        return 3, {**result, "error_type": "InvalidConfiguration"}

    status, payload, failure = _open_bounded_json(
        request, endpoint, max_bytes=QUOTE_RESPONSE_LIMIT_BYTES
    )
    if failure is not None:
        if failure.get("error_type") == "InvalidJSON" and status is not None and 200 <= status < 300:
            result.update(
                http_status=status,
                status="ok",
                response_bytes_limit=QUOTE_RESPONSE_LIMIT_BYTES,
                note="HTTP access alone does not verify account rights, real-time data, or historical access.",
            )
            return 0, result
        return 3 if failure.get("transport_error") else 4, {
            **result,
            **failure,
            **({"http_status": status} if status is not None else {}),
        }

    result.update(
        http_status=status,
        status="ok" if status is not None and 200 <= status < 300 else "failed",
        response_bytes_limit=QUOTE_RESPONSE_LIMIT_BYTES,
    )
    result["note"] = (
        "HTTP access alone does not verify account rights, real-time data, or historical access."
    )
    if _service_rejected(payload):
        return 4, {**result, "status": "failed", "error_type": "ServiceRejected"}
    if isinstance(payload, dict):
        quotes = payload.get("Quote")
        quote = quotes.get(symbol) if isinstance(quotes, dict) else None
        if isinstance(quote, dict) and quote.get("eventSymbol") == symbol:
            bid, ask = quote.get("bidPrice"), quote.get("askPrice")
            bid_size = quote.get("bidSizeAsDouble", quote.get("bidSize"))
            ask_size = quote.get("askSizeAsDouble", quote.get("askSize"))
            try:
                result["quote_received"] = (
                    type(bid) in (int, float)
                    and type(ask) in (int, float)
                    and math.isfinite(bid)
                    and math.isfinite(ask)
                    and 0 < bid < ask
                )
                result["quote_sizes_received"] = (
                    _finite_number(bid_size, nonnegative=True)
                    and _finite_number(ask_size, nonnegative=True)
                    and float(bid_size) + float(ask_size) > 0
                )
            except (OverflowError, TypeError, ValueError):
                result["quote_received"] = False
                result["quote_sizes_received"] = False
    result["research_eligibility"] = {
        "current_level1_bbo_prices": bool(result["quote_received"]),
        "current_level1_bbo_sizes": bool(result["quote_sizes_received"]),
        "CMF_H3_live_capture_component": bool(
            result["quote_received"] and result["quote_sizes_received"]
        ),
        "historical_quote_stream_verified": False,
    }
    return (0 if result["status"] == "ok" else 4), result


def _time_and_sale_events(payload, symbol: str) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    collection = payload.get("TimeAndSale")
    candidates: list[object] = []
    nested_by_symbol = False
    if isinstance(collection, dict) and symbol in collection:
        nested_by_symbol = True
        value = collection.get(symbol)
        if isinstance(value, list):
            candidates.extend(value)
        elif isinstance(value, dict):
            candidates.append(value)
    elif isinstance(collection, list):
        candidates.extend(collection)

    events = []
    for value in candidates:
        if not isinstance(value, dict):
            continue
        event_symbol = value.get("eventSymbol")
        if nested_by_symbol:
            if event_symbol not in (None, symbol):
                continue
        elif event_symbol != symbol:
            continue
        events.append(value)
    return events


def _finite_number(value, *, positive: bool = False, nonnegative: bool = False) -> bool:
    if isinstance(value, bool) or type(value) not in (int, float):
        return False
    try:
        if not math.isfinite(value):
            return False
    except OverflowError:
        return False
    if positive and value <= 0:
        return False
    if nonnegative and value < 0:
        return False
    return True


def _order_events(payload, symbol: str) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    collection = payload.get("Order")
    candidates: list[object] = []
    nested_by_symbol = False
    if isinstance(collection, dict) and symbol in collection:
        nested_by_symbol = True
        value = collection.get(symbol)
        if isinstance(value, list):
            candidates.extend(value)
        elif isinstance(value, dict):
            candidates.append(value)
    elif isinstance(collection, list):
        candidates.extend(collection)

    events = []
    for value in candidates:
        if not isinstance(value, dict):
            continue
        event_symbol = value.get("eventSymbol")
        if nested_by_symbol:
            if event_symbol not in (None, symbol):
                continue
        elif event_symbol != symbol:
            continue
        events.append(value)
    return events


def probe_depth_snapshot(
    endpoint,
    token,
    symbol,
    *,
    username=None,
    password=None,
):
    """Probe current AGGREGATE futures Order depth without returning raw orders."""
    result = {
        "mode": "rest_depth_snapshot",
        "status": "failed",
        "account_entitlement_verified": False,
        "historical_depth_verified": False,
        "depth_source": FUTURES_DEPTH_SOURCE,
        "current_depth_snapshot_verified": False,
        "valid_order_events": 0,
        "bid_price_levels": 0,
        "ask_price_levels": 0,
        "top10_each_side_verified": False,
        "research_eligibility": {
            "CMF_H2_current_depth_component": False,
            "CMF_H2_historical_replay": False,
        },
    }
    try:
        endpoint, symbol = _validated_endpoint_symbol(endpoint, symbol)
        authorization = _authorization(token, username=username, password=password)
        request = urllib.request.Request(
            endpoint
            + "?"
            + urllib.parse.urlencode(
                [
                    ("event", "Order"),
                    ("symbol", symbol),
                    ("source", FUTURES_DEPTH_SOURCE),
                    ("timeout", "3"),
                ]
            ),
            headers={
                "Authorization": authorization,
                "Accept": "application/json",
                "User-Agent": "orderflow-edge-lab/1.0",
            },
        )
    except (ValueError, TypeError, AttributeError):
        return 3, {**result, "error_type": "InvalidConfiguration"}

    status, payload, failure = _open_bounded_json(
        request, endpoint, max_bytes=DEPTH_RESPONSE_LIMIT_BYTES
    )
    if failure is not None:
        return 3 if failure.get("transport_error") else 4, {
            **result,
            **failure,
            **({"http_status": status} if status is not None else {}),
        }
    result.update(
        http_status=status,
        response_bytes_limit=DEPTH_RESPONSE_LIMIT_BYTES,
        status="ok" if status is not None and 200 <= status < 300 else "failed",
    )
    if _service_rejected(payload):
        return 4, {**result, "status": "failed", "error_type": "ServiceRejected"}

    bid_levels: set[float] = set()
    ask_levels: set[float] = set()
    valid_orders = 0
    for event in _order_events(payload, symbol):
        price = event.get("price")
        size = event.get("sizeAsDouble", event.get("size"))
        side = str(event.get("orderSide", "")).strip().upper()
        if not _finite_number(price, positive=True) or not _finite_number(size, positive=True):
            continue
        valid_orders += 1
        if side in {"BUY", "BID"}:
            bid_levels.add(float(price))
        elif side in {"SELL", "ASK"}:
            ask_levels.add(float(price))

    result["valid_order_events"] = valid_orders
    result["bid_price_levels"] = len(bid_levels)
    result["ask_price_levels"] = len(ask_levels)
    result["current_depth_snapshot_verified"] = bool(bid_levels and ask_levels)
    result["top10_each_side_verified"] = len(bid_levels) >= 10 and len(ask_levels) >= 10
    result["research_eligibility"] = {
        "CMF_H2_current_depth_component": bool(result["top10_each_side_verified"]),
        "CMF_H2_historical_replay": False,
    }
    result["note"] = (
        "Order/AGGREGATE verifies only a current depth snapshot. REST toTime is not a "
        "historical-depth guarantee for indexed Order events; historical CMF-H2 replay "
        "still requires a captured/exported Order stream."
    )
    if result["current_depth_snapshot_verified"]:
        return 0, result
    return 4, {**result, "error_type": "NoDepthSnapshot"}


def probe_history(
    endpoint,
    token,
    symbol,
    from_time,
    to_time,
    *,
    username=None,
    password=None,
):
    """Probe a bounded historical dxFeed TimeAndSale window without returning raw events."""
    result = {
        "mode": "rest_history",
        "status": "failed",
        "account_entitlement_verified": False,
        "historical_access_verified": False,
        "time_and_sale_received": False,
        "event_count": 0,
        "valid_price_events": 0,
        "events_with_size": 0,
        "events_with_bid_ask": 0,
        "events_with_aggressor_side": 0,
        "events_with_sequence": 0,
    }
    try:
        endpoint, symbol = _validated_endpoint_symbol(endpoint, symbol)
        start, end = _parse_bounded_history_window(from_time, to_time)
        authorization = _authorization(token, username=username, password=password)
        request = urllib.request.Request(
            endpoint
            + "?"
            + urllib.parse.urlencode(
                [
                    ("event", "TimeAndSale"),
                    ("symbol", symbol),
                    ("fromTime", start),
                    ("toTime", end),
                    ("timeout", "3"),
                ]
            ),
            headers={
                "Authorization": authorization,
                "Accept": "application/json",
                "User-Agent": "orderflow-edge-lab/1.0",
            },
        )
    except (ValueError, TypeError, AttributeError):
        return 3, {**result, "error_type": "InvalidConfiguration"}

    status, payload, failure = _open_bounded_json(
        request, endpoint, max_bytes=HISTORY_RESPONSE_LIMIT_BYTES
    )
    if failure is not None:
        return 3 if failure.get("transport_error") else 4, {
            **result,
            **failure,
            **({"http_status": status} if status is not None else {}),
        }

    result.update(
        http_status=status,
        requested_from_time=start,
        requested_to_time=end,
        response_bytes_limit=HISTORY_RESPONSE_LIMIT_BYTES,
        status="ok" if status is not None and 200 <= status < 300 else "failed",
    )
    if _service_rejected(payload):
        return 4, {**result, "status": "failed", "error_type": "ServiceRejected"}

    events = _time_and_sale_events(payload, symbol)
    result["event_count"] = len(events)
    for event in events:
        price = event.get("price")
        size = event.get("size")
        bid = event.get("bidPrice")
        ask = event.get("askPrice")
        side = event.get("aggressorSide")
        sequence = event.get("sequence")

        if _finite_number(price, positive=True):
            result["valid_price_events"] += 1
        if _finite_number(size, nonnegative=True):
            result["events_with_size"] += 1
        if _finite_number(bid, positive=True) and _finite_number(ask, positive=True) and bid < ask:
            result["events_with_bid_ask"] += 1
        if side is not None and str(side).strip().upper() not in {"", "UNDEFINED", "UNKNOWN", "NONE"}:
            result["events_with_aggressor_side"] += 1
        if isinstance(sequence, int) and not isinstance(sequence, bool) and sequence >= 0:
            result["events_with_sequence"] += 1

    result["time_and_sale_received"] = result["valid_price_events"] > 0
    result["historical_access_verified"] = result["time_and_sale_received"]
    result["research_eligibility"] = {
        "historical_time_and_sale_component": bool(result["historical_access_verified"]),
        "CMF_H1_aggressor_component": bool(
            result["events_with_size"] > 0 and result["events_with_aggressor_side"] > 0
        ),
        "historical_quote_stream_verified": False,
        "CMF_H1_full_frozen_replay": False,
        "CMF_H2_full_frozen_replay": False,
        "CMF_H3_full_frozen_replay": False,
    }
    result["note"] = (
        "Historical TimeAndSale access is verified only for this endpoint, symbol, and bounded window. "
        "The frozen futures replay still requires actual quote events for executable BBO state; "
        "TimeAndSale alone does not verify historical Quote or Order streams."
    )
    if result["historical_access_verified"]:
        return 0, result
    return 4, {**result, "error_type": "NoHistoricalTimeAndSale"}
