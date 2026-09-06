import base64
import json

SANDBOX_API_BASE = "https://api-m.sandbox.paypal.com"
LIVE_API_BASE = "https://api-m.paypal.com"


def safe_get(data, keys, default=None):
    """
    Recursively calls .get() on a dictionary to safely access nested keys.

    Args:
        data (dict): The dictionary to access.
        keys (list): The list of keys to access, in order.
        default: The value to return if any key is missing or not a dictionary.
    """
    if not keys:
        return data
    key = keys[0]
    value = data.get(key)
    if not keys[1:]:
        return value if value is not None else default
    if isinstance(value, dict):
        return safe_get(value, keys[1:], default=default)
    return default


def resolve_paypal_api_base(endpoint: str | None) -> str:
    """Map stored endpoint settings to the PayPal REST API host."""
    value = (endpoint or "live").strip().rstrip("/")
    lowered = value.lower()
    if lowered in {"sandbox", "test"} or "sandbox" in lowered:
        return SANDBOX_API_BASE
    if lowered in {"live", "production"}:
        return LIVE_API_BASE
    if lowered.startswith("http://") or lowered.startswith("https://"):
        if lowered.startswith("https://api.paypal.com"):
            return LIVE_API_BASE
        if lowered.startswith("https://api.sandbox.paypal.com"):
            return SANDBOX_API_BASE
        return value
    return LIVE_API_BASE


def is_paypal_sandbox(endpoint: str | None) -> bool:
    return resolve_paypal_api_base(endpoint) == SANDBOX_API_BASE


def canonical_paypal_endpoint(endpoint: str | None) -> str:
    """Return live or sandbox for stored endpoint aliases and legacy URLs."""
    return "sandbox" if is_paypal_sandbox(endpoint) else "live"


def uses_paypal_connect(settings) -> bool:
    return bool(settings.connect_client_id and settings.connect_secret_key)


def paypal_payee_block(merchant_id: str | None) -> dict | None:
    """Omit payee entirely unless Connect provided a merchant id (empty payee breaks checkout)."""
    if not merchant_id:
        return None
    return {"merchant_id": merchant_id}


def paypal_approval_href(order: dict | None) -> str | None:
    """PayPal returns payer-action on newer Orders APIs and approve on older ones."""
    if not order:
        return None
    for link in order.get("links") or []:
        if not isinstance(link, dict):
            continue
        if link.get("rel") in {"payer-action", "approve"}:
            href = link.get("href")
            if href:
                return href
    return None


def paypal_error_reason(response, fallback: str = "") -> str:
    """Extract a human-readable error from a PayPal HTTP response."""
    try:
        body = response.json()
    except ValueError:
        return fallback or getattr(response, "reason", "") or "Unknown PayPal error"

    details = body.get("details") or []
    detail_parts = [
        part
        for detail in details
        if isinstance(detail, dict)
        for part in [detail.get("description") or detail.get("issue") or ""]
        if part
    ]
    return (
        body.get("message")
        or body.get("error_description")
        or body.get("error")
        or "; ".join(detail_parts)
        or fallback
        or getattr(response, "reason", "")
        or "Unknown PayPal error"
    )


def build_paypal_auth_assertion(client_id: str, merchant_id: str | None) -> str:
    """Build a PayPal-Auth-Assertion JWT with alg=none as required by PayPal."""
    if not client_id or not merchant_id:
        return ""

    def b64url(payload: dict) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    header = b64url({"alg": "none", "typ": "JWT"})
    body = b64url({"iss": client_id, "payer_id": merchant_id})
    return f"{header}.{body}."
