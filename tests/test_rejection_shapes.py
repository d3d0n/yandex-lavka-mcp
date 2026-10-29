from lavka_rejection_capture import sanitize_rejection


def test_frontend_response_wrapper_and_checkout_reason_are_extracted_safely():
    body = {"response": {"message": "grocery_unavailable_for_checkout", "details": {"cart": {"checkout_unavailable_reason": "bad_service_fee_v2", "address": "private", "items": [{"code": "secret"}]}}}, "token": "secret"}
    assert sanitize_rejection(400, body) == {"http_status": 400, "codes": ["grocery_unavailable_for_checkout", "bad_service_fee_v2"]}


def test_direct_backend_shape_and_unknown_reason_remain_private():
    body = {"code": "grocery_unavailable_for_checkout", "details": {"cart": {"checkout_unavailable_reason": "private-identifier", "phone": "private"}}}
    assert sanitize_rejection(400, body) == {"http_status": 400, "codes": ["grocery_unavailable_for_checkout"], "unrecognized_code": True}


def test_actual_provider_error_envelope_without_request_body_disclosure():
    body = {"data": {"data": {"body": {"code": "private", "message": "bad_service_fee_v2"},
                                "response": {"message": "grocery_unavailable_for_checkout",
                                             "details": {"cart": {"checkout_unavailable_reason": "bad_service_fee_v2"}}}}}}
    assert sanitize_rejection(400, body) == {"http_status": 400, "codes": ["grocery_unavailable_for_checkout", "bad_service_fee_v2"]}
    body["data"]["data"]["response"] = {}
    assert sanitize_rejection(400, body) == {"http_status": 400, "codes": [], "unrecognized_code": False}


def test_untrusted_unrelated_subtree_is_not_traversed():
    body = {"customer": {"code": "bad_service_fee_v2"}, "details": {"cart": {"items": [{"message": "grocery_unavailable_for_checkout"}]}}}
    assert sanitize_rejection(400, body) == {"http_status": 400, "codes": [], "unrecognized_code": False}
