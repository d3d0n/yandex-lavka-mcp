import json
import httpx
import pytest
import lavka_uz


@pytest.mark.asyncio
async def test_cart_mcp_read_update_preview_and_masked_cards(monkeypatch):
    calls = []
    def handle(request):
        path = request.url.path
        calls.append(path)
        if request.url.host == 'yandex.uz':
            return httpx.Response(200, headers={'set-cookie': 'yandexuid=anon; Domain=.yandex.uz; Path=/'})
        if request.method == 'GET':
            props = {'pageData': {'passportInfo': {'status': 'VALID'}, 'serviceInfo': {'currency': 'UZS', 'currencySign': 'сум'}}}
            return httpx.Response(200, text='<script id="__page_props__-data">' + json.dumps(props) + '</script>')
        if path.endswith('/retrieve'):
            items = [{'id': 'product', 'title': 'Milk', 'quantity': '1', 'price': '100'}] if '/api/v1/providers/cart/v1/update' in calls else []
            return httpx.Response(200, json={'cartId': 'secret-cart', 'cartVersion': 1, 'items': items, 'availableForCheckout': True})
        if path.endswith('/update'):
            assert json.loads(request.content)['items'][0]['quantity'] == '1'
            return httpx.Response(200, json={})
        if path.endswith('/methods'):
            return httpx.Response(200, json={'methods': [{'type': 'card', 'availability': {'available': True}, 'id': 'secret-card', 'number': '1234567890123456'}]})
        raise AssertionError(path)
    monkeypatch.setattr(lavka_uz, 'create_http', lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    assert (await lavka_uz.get_cart(69, 41))['items'] == []
    result = await lavka_uz.set_cart_item(69, 41, 'product', 1, '100')
    assert result['items'][0]['quantity'] == '1'
    assert 'secret-cart' not in json.dumps(result)
    assert (await lavka_uz.saved_cards(69, 41))['cards'] == ['**** 3456']
    preview = await lavka_uz.checkout_preview(69, 41)
    assert preview['order_submission_enabled'] is False
    assert preview['address_selected'] is False
    assert preview['payment_selected'] is False
    assert 'secret-cart' not in json.dumps(preview)
    assert not any('submit' in path for path in calls)
