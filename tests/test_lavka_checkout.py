import copy
import concurrent.futures
import os
import pytest


@pytest.fixture
def snapshot():
    return {
        "account_id": "account-1", "cart_id": "cart-1", "cart_version": 3,
        "currency": "UZS", "total_uzs": "15000.00",
        "items": [{"id": "1", "title": "Milk", "quantity": "1", "price_uzs": "15000.00"}],
        "address": {"id": "addr-1", "label": "Example address"},
        "payment": {"id": "payment-1", "type": "card", "label": "Card ••1234"},
        "delivery": {"type": "delivery", "label": "Today"},
        "available_for_checkout": True,
    }


def test_preview_stages_complete_snapshot(tmp_path, snapshot):
    from lavka_checkout import CheckoutSafety
    store = CheckoutSafety(tmp_path / "checkout.sqlite3")
    preview = store.preview(snapshot)
    assert preview["snapshot"] == snapshot
    assert preview["preview_token"]
    assert preview["order_submission_enabled"] is False


def test_confirmation_consumes_preview_once_and_remains_offline(tmp_path, snapshot):
    from lavka_checkout import CheckoutSafety, CheckoutError
    store = CheckoutSafety(tmp_path / "checkout.sqlite3")
    preview = store.preview(snapshot)
    result = store.confirm(preview["preview_token"], snapshot, confirmed_total_uzs="15000.00", explicit_confirmation=True)
    assert result["order_submission_enabled"] is False
    assert result["status"] == "confirmed_offline"
    with pytest.raises(CheckoutError, match="consumed"):
        CheckoutSafety(tmp_path / "checkout.sqlite3").confirm(preview["preview_token"], snapshot, confirmed_total_uzs="15000.00", explicit_confirmation=True)


@pytest.mark.parametrize("field,value", [
    ("cart_version", None), ("cart_version", True), ("currency", "RUB"),
    ("total_uzs", "NaN"), ("total_uzs", "-1"), ("total_uzs", 15000.0),
    ("items", []), ("address", {}), ("payment", {}), ("delivery", {}),
    ("account_id", ""), ("cart_id", ""), ("available_for_checkout", None),
    ("available_for_checkout", False),
])
def test_preview_rejects_incomplete_or_unsafe_snapshot(tmp_path, snapshot, field, value):
    from lavka_checkout import CheckoutSafety, CheckoutError
    snapshot[field] = value
    with pytest.raises(CheckoutError):
        CheckoutSafety(tmp_path / "state.sqlite3").preview(snapshot)


@pytest.mark.parametrize("field,value", [
    ("account_id", "other"), ("cart_id", "other"), ("cart_version", 4),
    ("total_uzs", "15001.00"), ("address", {"id": "other", "label": "New"}),
    ("payment", {"id": "other", "type": "card", "label": "New"}),
    ("delivery", {"type": "pickup", "label": "New"}),
    ("items", [{"id": "2", "title": "Eggs", "quantity": "1", "price_uzs": "15000.00"}]),
])
def test_confirmation_rejects_snapshot_drift(tmp_path, snapshot, field, value):
    from lavka_checkout import CheckoutSafety, CheckoutError
    store = CheckoutSafety(tmp_path / "state.sqlite3")
    token = store.preview(snapshot)["preview_token"]
    live = copy.deepcopy(snapshot)
    live[field] = value
    with pytest.raises(CheckoutError):
        store.confirm(token, live, confirmed_total_uzs="15000.00", explicit_confirmation=True)


def test_preview_expiry_and_explicit_confirmation(tmp_path, snapshot):
    from lavka_checkout import CheckoutSafety, CheckoutError
    now = [1000.0]
    store = CheckoutSafety(tmp_path / "state.sqlite3", clock=lambda: now[0], max_age_seconds=30)
    token = store.preview(snapshot)["preview_token"]
    with pytest.raises(CheckoutError):
        store.confirm(token, snapshot, confirmed_total_uzs="15000.00", explicit_confirmation=False)
    now[0] += 31
    with pytest.raises(CheckoutError, match="expired"):
        store.confirm(token, snapshot, confirmed_total_uzs="15000.00", explicit_confirmation=True)


def test_concurrent_confirmation_only_one_succeeds(tmp_path, snapshot):
    from lavka_checkout import CheckoutSafety, CheckoutError
    path = tmp_path / "state.sqlite3"
    token = CheckoutSafety(path).preview(snapshot)["preview_token"]
    def confirm():
        try:
            return CheckoutSafety(path).confirm(token, snapshot, confirmed_total_uzs="15000.00", explicit_confirmation=True)["status"]
        except CheckoutError:
            return "blocked"
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: confirm(), range(8)))
    assert results.count("confirmed_offline") == 1
    assert results.count("blocked") == 7


def test_state_database_is_private(tmp_path, snapshot):
    from lavka_checkout import CheckoutSafety
    path = tmp_path / "state.sqlite3"
    CheckoutSafety(path).preview(snapshot)
    assert os.stat(path).st_mode & 0o077 == 0


def test_repreview_does_not_extend_existing_expiry(tmp_path, snapshot):
    from lavka_checkout import CheckoutSafety, CheckoutError
    now = [1000.0]
    path = tmp_path / "state.sqlite3"
    token = CheckoutSafety(path, clock=lambda: now[0], max_age_seconds=10).preview(snapshot)["preview_token"]
    now[0] = 1011.0
    with pytest.raises(CheckoutError, match="expired"):
        CheckoutSafety(path, clock=lambda: now[0], max_age_seconds=300).confirm(token, snapshot, confirmed_total_uzs="15000.00", explicit_confirmation=True)


def test_unknown_token_and_total_mismatch_fail(tmp_path, snapshot):
    from lavka_checkout import CheckoutSafety, CheckoutError
    store = CheckoutSafety(tmp_path / "state.sqlite3")
    token = store.preview(snapshot)["preview_token"]
    for submitted_token, total in [("wrong", "15000.00"), (token, "15000.01"), (token, 15000)]:
        with pytest.raises(CheckoutError):
            store.confirm(submitted_token, snapshot, confirmed_total_uzs=total, explicit_confirmation=True)


def test_preview_unknown_fields_cannot_hide_card_secrets(tmp_path, snapshot):
    from lavka_checkout import CheckoutSafety, CheckoutError
    snapshot["payment"]["card_number"] = "4111111111111111"
    with pytest.raises(CheckoutError):
        CheckoutSafety(tmp_path / "state.sqlite3").preview(snapshot)


def test_preview_duplicate_staged_tokens_are_not_two_authorizations(tmp_path, snapshot):
    from lavka_checkout import CheckoutSafety, CheckoutError
    store = CheckoutSafety(tmp_path / "state.sqlite3")
    a = store.preview(snapshot)["preview_token"]
    b = store.preview(snapshot)["preview_token"]
    store.confirm(a, snapshot, confirmed_total_uzs="15000.00", explicit_confirmation=True)
    with pytest.raises(CheckoutError, match="consumed"):
        store.confirm(b, snapshot, confirmed_total_uzs="15000.00", explicit_confirmation=True)


def test_uncertain_state_cannot_be_retried_or_repreviewed(tmp_path, snapshot):
    from lavka_checkout import CheckoutSafety, CheckoutError
    store = CheckoutSafety(tmp_path / "state.sqlite3")
    token = store.preview(snapshot)["preview_token"]
    other_token = store.preview(snapshot)["preview_token"]
    store.mark_uncertain(token)
    with pytest.raises(CheckoutError, match="uncertain"):
        store.preview(snapshot)
    with pytest.raises(CheckoutError, match="consumed"):
        CheckoutSafety(tmp_path / "state.sqlite3").confirm(token, snapshot, confirmed_total_uzs="15000.00", explicit_confirmation=True)
    with pytest.raises(CheckoutError, match="uncertain"):
        store.confirm(other_token, snapshot, confirmed_total_uzs="15000.00", explicit_confirmation=True)
    with pytest.raises(CheckoutError, match="Unknown preview"):
        store.mark_uncertain("wrong")
