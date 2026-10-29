from lavka_rejection_capture import sanitize_rejection


def test_known_nested_error_is_captured_without_sensitive_fields():
    body = {"message": "grocery_unavailable_for_checkout", "details": {"code": "bad_service_fee_v2", "address": "private address", "token": "secret"}, "payment": "secret"}
    assert sanitize_rejection(400, body) == {"http_status": 400, "codes": ["grocery_unavailable_for_checkout", "bad_service_fee_v2"]}


def test_unknown_strings_and_untrusted_fields_are_never_emitted():
    body = {"message": "secret_token", "details": [{"code": "my_private_identifier"}], "code": "grocery_unavailable_for_checkout", "other": {"code": "bad_service_fee_v2"}}
    assert sanitize_rejection(400, body) == {"http_status": 400, "codes": ["grocery_unavailable_for_checkout"], "unrecognized_code": True}


def test_malformed_input_is_safe_and_status_is_validated():
    import pytest
    assert sanitize_rejection(500, "secret") == {"http_status": 500, "codes": [], "unrecognized_code": False}
    for status in (True, 200, 600, "400"):
        with pytest.raises(ValueError):
            sanitize_rejection(status, {})
