import copy
import pytest


def payload_args():
    return dict(cart_id="FAKE_CART", cart_version=7, flow_version="grocery_flow_v1",
                position={"location": [69.1, 41.3], "placeId": "FAKE", "flat": "1"},
                payment_type="card", payment_id="FAKE_CARD", depot_type="regular")


def test_legacy_provider_payload_matches_intercepted_frontend():
    from lavka_submit_payload import build_provider_payload
    actual = build_provider_payload(**payload_args())
    assert actual == {
        "cartId": "FAKE_CART", "cartVersion": 7, "flowVersion": "grocery_flow_v1",
        "position": {"location": [69.1, 41.3], "placeId": "FAKE", "flat": "1"},
        "paymentMethodType": "card", "paymentMethodId": "FAKE_CARD",
        "depotOrderContext": {"depotType": "regular", "position": [69.1, 41.3]},
    }


def test_sbp_legacy_ids_follow_frontend():
    from lavka_submit_payload import build_provider_payload
    for kind in ("sbp", "sbp_bind_token"):
        args = payload_args()
        args.update(payment_type=kind, payment_id="FAKE_CARD")
        assert build_provider_payload(**args)["paymentMethodId"] == {"sbp": "sbp_qr", "sbp_bind_token": "sbp_bind_token"}[kind]


def test_optional_fields_are_serialized_without_invented_fields():
    from lavka_submit_payload import build_provider_payload
    args = payload_args()
    args["options"] = {"serviceFee": "1000", "useRover": False, "timeslot": {"id": "FAKE"}}
    result = build_provider_payload(**args)
    assert result["serviceFee"] == "1000"
    assert result["useRover"] is False
    assert result["timeslot"] == {"id": "FAKE"}
    assert "offerId" not in result and "idempotencyToken" not in result
    args["options"]["timeslot"]["id"] = "changed"
    assert result["timeslot"]["id"] == "FAKE"


def test_new_payment_branch_and_legacy_branch_are_exclusive():
    from lavka_submit_payload import build_provider_payload
    args = payload_args()
    args.pop("payment_type")
    args.pop("payment_id")
    args["payment_method"] = {"type": "card", "id": "FAKE_CARD"}
    result = build_provider_payload(**args)
    assert result["paymentMethod"] == args["payment_method"]
    assert "paymentMethodType" not in result and "paymentMethodId" not in result
    args["payment_type"] = "card"
    args["payment_id"] = "FAKE_CARD"
    with pytest.raises(ValueError):
        build_provider_payload(**args)


@pytest.mark.parametrize("change", [
    {"cart_id": ""}, {"cart_version": True}, {"cart_version": 0},
    {"flow_version": ""}, {"position": {"location": [float('nan'), 41.3]}},
    {"position": {"location": [69.1]}}, {"depot_type": ""},
    {"payment_id": ""}, {"options": {"offerId": "not allowed"}},
    {"options": {"serviceFee": float('nan')}},
])
def test_invalid_payloads_are_rejected(change):
    from lavka_submit_payload import build_provider_payload
    args = payload_args()
    args.update(change)
    with pytest.raises(ValueError):
        build_provider_payload(**args)
