"""Synthetic, network-free regression tests for the proposed UZ fee bridge."""
import copy
import pytest

from lavka_submit_payload import build_provider_payload


def build(cart, **changes):
    args = dict(cart_id="FAKE_CART", cart_version=7, flow_version="FAKE_FLOW",
                position={"location": [69.1, 41.3]}, depot_type="regular",
                payment_type="card", payment_id="FAKE_CARD", raw_cart=cart)
    args.update(changes)
    return build_provider_payload(**args)


def valid_cart(amount="3990"):
    return {"cartId": "FAKE_CART", "cartVersion": 7,
            "paidServices": {"serviceFeeV2": {"amount": amount},
                             "totalServiceFees": {"amount": "4640"}}}


def test_nested_service_fee_is_bound_to_offline_payload_not_fee_total():
    cart = {
        "cartId": "FAKE_CART", "cartVersion": 7,
        "paidServices": {"serviceFeeV2": {"amount": "3990"},
                         "totalServiceFees": {"amount": "4640"}},
    }
    payload = build_provider_payload(
        cart_id="FAKE_CART", cart_version=7, flow_version="FAKE_FLOW",
        position={"location": [69.1, 41.3]}, depot_type="regular",
        payment_type="card", payment_id="FAKE_CARD", raw_cart=cart,
    )
    assert payload["serviceFee"] == "3990"


def test_zero_fee_and_matching_top_level_are_preserved_without_mutation():
    cart = valid_cart("0")
    cart["serviceFeeV2"] = {"amount": "0"}
    original = copy.deepcopy(cart)
    assert build(cart)["serviceFee"] == "0"
    assert cart == original


@pytest.mark.parametrize("paid", [None, {}, [], {"serviceFeeV2": None},
                                  {"serviceFeeV2": {}}, {"serviceFeeV2": {"amount": 3990}},
                                  {"serviceFeeV2": {"amount": True}}, {"serviceFeeV2": {"amount": "-1"}},
                                  {"serviceFeeV2": {"amount": "1.0"}}, {"serviceFeeV2": {"amount": ""}},
                                  {"serviceFeeV2": {"amount": "١"}}])
def test_missing_or_invalid_fee_fails_closed(paid):
    cart = valid_cart()
    cart["paidServices"] = paid
    with pytest.raises(ValueError, match="service fee"):
        build(cart)


@pytest.mark.parametrize("cart_change", [{"cartId": "OTHER"}, {"cartVersion": 8},
                                          {"cartVersion": True}])
def test_fee_cannot_be_reused_with_different_cart_or_version(cart_change):
    cart = valid_cart()
    cart.update(cart_change)
    with pytest.raises(ValueError, match="identity and version"):
        build(cart)


def test_service_fee_option_cannot_override_cart():
    with pytest.raises(ValueError, match="override"):
        build(valid_cart(), options={"serviceFee": "4640"})


def test_malformed_paid_services_fails_closed():
    cart = {"cartId": "FAKE_CART", "cartVersion": 7, "paidServices": None}
    with pytest.raises(ValueError, match="service fee"):
        build_provider_payload(cart_id="FAKE_CART", cart_version=7, flow_version="FAKE_FLOW",
                               position={"location": [69.1, 41.3]}, depot_type="regular",
                               payment_type="card", payment_id="FAKE_CARD", raw_cart=cart)


def test_conflicting_top_level_fee_is_rejected():
    cart = {"cartId": "FAKE_CART", "cartVersion": 7,
            "serviceFeeV2": {"amount": "2000"},
            "paidServices": {"serviceFeeV2": {"amount": "3990"}}}
    with pytest.raises(ValueError, match="conflict"):
        build_provider_payload(cart_id="FAKE_CART", cart_version=7, flow_version="FAKE_FLOW",
                               position={"location": [69.1, 41.3]}, depot_type="regular",
                               payment_type="card", payment_id="FAKE_CARD", raw_cart=cart)
