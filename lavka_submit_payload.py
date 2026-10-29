"""Offline serialization of the locally intercepted provider branch only.

Not a verified server contract or a safe checkout gate. Never transmits a request.
"""
import json
import math


OPTIONAL_FIELDS = frozenset({"secondaryPaymentMethod", "cashback", "serviceFee",
    "timeslot", "useRover", "giftByPhone", "charity", "useNotVerifiedPhone",
    "commentForPicker", "dispatchPassParams"})


def build_provider_payload(*, cart_id, cart_version, flow_version, position,
                           depot_type, payment_type=None, payment_id=None,
                           payment_method=None, options=None, raw_cart=None):
    """Build a non-transmitting fixture; raw_cart opts into an unverified bridge.

    Cart identity/version equality is not proof of freshness, server pricing
    enforcement, or authorization. The nested fee mapping is a hypothesis,
    not a validated backend contract.
    """
    def text(value):
        return isinstance(value, str) and bool(value.strip())

    if not all(text(v) for v in (cart_id, flow_version, depot_type)):
        raise ValueError("Cart, flow, and depot identifiers are required")
    if type(cart_version) is not int or cart_version <= 0:
        raise ValueError("A positive cart version is required")
    location = position.get("location") if isinstance(position, dict) else None
    if (not isinstance(location, list) or len(location) != 2 or
        any(type(v) not in (int, float) or not math.isfinite(v) for v in location) or
        not (55 <= location[0] <= 74 and 37 <= location[1] <= 46)):
        raise ValueError("A finite Uzbekistan position is required")
    if payment_method is None:
        if not text(payment_type) or not text(payment_id):
            raise ValueError("Selected legacy payment type and ID are required")
        payment = {"paymentMethodType": payment_type,
                   "paymentMethodId": {"sbp": "sbp_qr", "sbp_bind_token": "sbp_bind_token"}.get(payment_type, payment_id)}
    else:
        if payment_type is not None or payment_id is not None or not isinstance(payment_method, dict) or not payment_method:
            raise ValueError("Provide exactly one selected payment branch")
        payment = {"paymentMethod": payment_method}
    if options is None:
        options = {}
    if not isinstance(options, dict) or not options.keys() <= OPTIONAL_FIELDS:
        raise ValueError("Unknown checkout option")
    if raw_cart is not None:
        if (not isinstance(raw_cart, dict) or raw_cart.get("cartId") != cart_id or
            type(raw_cart.get("cartVersion")) is not int or raw_cart["cartVersion"] != cart_version):
            raise ValueError("Raw cart identity and version must match the payload")
        if "serviceFee" in options:
            raise ValueError("Do not override the cart service fee")
        paid = raw_cart.get("paidServices")
        fee_v2 = paid.get("serviceFeeV2") if isinstance(paid, dict) else None
        fee = fee_v2.get("amount") if isinstance(fee_v2, dict) else None
        if not isinstance(fee, str) or not fee or not fee.isascii() or not fee.isdigit():
            raise ValueError("A nonnegative integer-string service fee is required")
        if "serviceFeeV2" in raw_cart:
            top = raw_cart["serviceFeeV2"]
            if not isinstance(top, dict) or top.get("amount") != fee:
                raise ValueError("Top-level and nested service fees conflict")
        options = {**options, "serviceFee": fee}
    result = {"cartId": cart_id, "cartVersion": cart_version, "flowVersion": flow_version,
              "position": position, **payment,
              "depotOrderContext": {"depotType": depot_type, "position": location}, **options}
    try:
        # JSON round-trip deep-copies and rejects NaN/non-JSON objects.
        return json.loads(json.dumps(result, allow_nan=False, ensure_ascii=False))
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Payload must contain finite JSON values") from None
