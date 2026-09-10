"""Bounded HTTPS diagnostics. Credentials stay in memory and are never returned."""
import base64
import json
import math
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_ENDPOINT = "https://tools.dxfeed.com/webservice/rest/events.json"
DEFAULT_SYMBOL = "/NQ:XCME"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe_connection(endpoint, token, symbol, *, username=None, password=None):
    result = {"mode": "rest", "status": "failed", "account_entitlement_verified": False,
              "historical_access_verified": False, "quote_received": False}
    try:
        parsed = urllib.parse.urlsplit(endpoint)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or any(c.isspace() for c in endpoint)
                or not symbol.strip() or any(c in symbol for c in "\r\n,")):
            raise ValueError("invalid endpoint or symbol")
        parsed.port
        if token:
            if username or password or not token.strip() or any(c in token for c in "\r\n"):
                raise ValueError("invalid authentication")
            authorization = f"Bearer {token}"
        else:
            if not username or not password or ":" in username or any(c in username + password for c in "\r\n"):
                raise ValueError("invalid authentication")
            authorization = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        request = urllib.request.Request(endpoint + "?" + urllib.parse.urlencode(
            [("event", "Quote"), ("symbol", symbol), ("timeout", "3")]),
            headers={"Authorization": authorization, "Accept": "application/json", "User-Agent": "orderflow-edge-lab/1.0"})
    except (ValueError, TypeError, AttributeError):
        return 3, {**result, "error_type": "InvalidConfiguration"}
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
            body = response.read(64_001)
            status = response.status
    except urllib.error.HTTPError as exc:
        redirect_to_demo = False
        if 300 <= exc.code < 400:
            target = urllib.parse.urlsplit(urllib.parse.urljoin(endpoint, exc.headers.get("Location", "")))
            redirect_to_demo = target.hostname == "demo.dxfeed.com"
        exc.close()
        return 3, {**result, "http_status": exc.code, "error_type": "HTTPError",
                   "redirect_to_public_demo": redirect_to_demo,
                   "note": ("Redirect refused; credentials were not forwarded. Obtain the provider endpoint for an account test."
                            if 300 <= exc.code < 400 else
                            "This endpoint rejected the request; other provider endpoints or entitlements are not tested.")}
    except Exception as exc:
        return 3, {**result, "error_type": type(exc).__name__,
                   "note": "Connection failed; credentials and server messages were not logged."}
    result.update(http_status=status, response_bytes_read=len(body), status="ok" if 200 <= status < 300 else "failed")
    result["note"] = "HTTP access alone does not verify account rights, real-time data, or historical access."
    if len(body) > 64_000:
        return 4, {**result, "status": "failed", "error_type": "ResponseTooLarge"}
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        payload = None
    if isinstance(payload, dict):
        if payload.get("status") not in (None, "OK"):
            return 4, {**result, "status": "failed", "error_type": "ServiceRejected"}
        quotes = payload.get("Quote")
        quote = quotes.get(symbol) if isinstance(quotes, dict) else None
        if isinstance(quote, dict) and quote.get("eventSymbol") == symbol:
            bid, ask = quote.get("bidPrice"), quote.get("askPrice")
            try:
                result["quote_received"] = (type(bid) in (int, float) and type(ask) in (int, float)
                                            and math.isfinite(bid) and math.isfinite(ask) and 0 < bid < ask)
            except OverflowError:
                result["quote_received"] = False
    return (0 if result["status"] == "ok" else 4), result
