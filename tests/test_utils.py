from eventyay_paypal.utils import safe_get


def test_safe_get_nested_and_missing_keys():
    data = {"purchase_units": [{"amount": {"value": "10.00"}}]}
    assert safe_get(data, ["purchase_units"])[0]["amount"]["value"] == "10.00"
    assert safe_get(data, ["missing", "key"], default="x") == "x"
    assert safe_get({"a": "not-a-dict"}, ["a", "b"], default=None) is None


def test_safe_get_empty_keys_returns_data():
    data = {"id": "ORDER1"}
    assert safe_get(data, []) is data
