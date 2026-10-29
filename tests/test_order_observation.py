import pytest


def test_active_order_feed_requires_verified_array():
    from lavka_order_observation import summarize_active_orders, ObservationError
    assert summarize_active_orders({"orders": []}) == {"active_order_count": 0, "statuses": []}
    with pytest.raises(ObservationError):
        summarize_active_orders({"unrelated": []})


def test_active_order_feed_exposes_only_statuses_not_identifiers():
    from lavka_order_observation import summarize_active_orders
    result = summarize_active_orders({"orders": [{"id": "private", "status": "delivering"}]})
    assert result == {"active_order_count": 1, "statuses": ["delivering"]}
    assert "private" not in str(result)
