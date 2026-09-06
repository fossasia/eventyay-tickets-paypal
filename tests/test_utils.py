from types import SimpleNamespace

from eventyay_paypal.utils import (
    build_paypal_auth_assertion,
    is_paypal_sandbox,
    paypal_error_reason,
    resolve_paypal_api_base,
    safe_get,
    uses_paypal_connect,
)


def test_safe_get_nested_and_missing_keys():
    data = {"purchase_units": [{"amount": {"value": "10.00"}}]}
    assert safe_get(data, ["purchase_units"])[0]["amount"]["value"] == "10.00"
    assert safe_get(data, ["missing", "key"], default="x") == "x"
    assert safe_get({"a": "not-a-dict"}, ["a", "b"], default=None) is None


def test_resolve_paypal_api_base_accepts_aliases_and_urls():
    assert resolve_paypal_api_base("sandbox") == "https://api-m.sandbox.paypal.com"
    assert resolve_paypal_api_base("https://api.sandbox.paypal.com") == "https://api-m.sandbox.paypal.com"
    assert resolve_paypal_api_base("https://api.paypal.com") == "https://api-m.paypal.com"
    assert resolve_paypal_api_base("live") == "https://api-m.paypal.com"
    assert resolve_paypal_api_base(None) == "https://api-m.paypal.com"
    assert is_paypal_sandbox("sandbox")
    assert not is_paypal_sandbox("live")


def test_uses_paypal_connect_prefers_platform_credentials():
    settings = SimpleNamespace(connect_client_id="client", connect_secret_key="secret", secret="leftover")
    assert uses_paypal_connect(settings)
    settings.connect_secret_key = ""
    assert not uses_paypal_connect(settings)


def test_build_paypal_auth_assertion_is_unsigned_jwt():
    token = build_paypal_auth_assertion("client-id", "MERCHANT1")
    header, payload, signature = token.split(".")
    assert header
    assert payload
    assert signature == ""
    assert build_paypal_auth_assertion("client-id", None) == ""


class DummyResponse:
    def __init__(self, payload, reason="Bad Request"):
        self._payload = payload
        self.reason = reason

    def json(self):
        return self._payload


def test_paypal_error_reason_reads_api_message():
    response = DummyResponse({"message": "INVALID_REQUEST", "details": [{"description": "Amount mismatch"}]})
    assert paypal_error_reason(response) == "INVALID_REQUEST"
