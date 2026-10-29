from lavka_rejection_capture import sanitize_upstream_error


def test_unknown_structured_error_code_and_status_are_preserved():
    body = {"error": {"code": "region_not_supported", "details": {"reason": "payment_declined", "retryable": False, "status": 409}}}
    assert sanitize_upstream_error(409, body) == {"http_status": 409, "error": {"error": {"code": "region_not_supported", "details": {"reason": "payment_declined", "retryable": False, "status": 409}}}}


def test_nested_sensitive_fields_and_freeform_messages_are_never_exposed():
    body = {"response": {"message": "Delivery to 10 Main St; token=abc", "details": [{"code": "payment_declined", "token": "abc", "address": "10 Main St", "card_id": "123"}, {"message": "name@example.com"}]}, "body": {"code": "do_not_leak"}, "headers": {"authorization": "abc"}}
    result = sanitize_upstream_error(400, body)
    assert result == {"http_status": 400, "error": {"response": {"message": "[redacted]", "details": [{"code": "payment_declined"}, {"message": "[redacted]"}]}}}


def test_status_validation_and_non_json_are_safe():
    import pytest
    assert sanitize_upstream_error(502, "<html>private address</html>") == {"http_status": 502, "error": "[redacted]"}
    for status in (True, 200, 600, "400"):
        with pytest.raises(ValueError):
            sanitize_upstream_error(status, {})
