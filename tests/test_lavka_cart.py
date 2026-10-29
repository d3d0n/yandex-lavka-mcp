import json
import httpx
import pytest

@pytest.mark.asyncio
async def test_retrieve_requires_authenticated_session_and_returns_live_cart():
    from lavka_cart import CartClient
    async def handle(request):
        assert request.url.path == '/api/v1/providers/cart/v1/retrieve'
        assert json.loads(request.content)['position']['location'] == [65.0, 40.0]
        return httpx.Response(200, json={'cartId': 'cart', 'cartVersion': 1, 'items': []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = CartClient(http, {'pageData': {'passportInfo': {'status': 'VALID'}}, 'csrfToken': 'a', 'authProxyCsrfToken': 'b'}, [65.0, 40.0], 'сум')
        assert (await client.retrieve())['items'] == []


@pytest.mark.asyncio
async def test_set_item_uses_uzs_and_readback_verifies_absolute_quantity():
    from lavka_cart import CartClient
    calls = []
    def handle(request):
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path.endswith('/update'):
            assert body['items'][0]['currency'] == 'UZS'
            assert body['items'][0]['quantity'] == '1'
            assert body['cartVersion'] == 1
            return httpx.Response(200, json={'ok': True})
        items = [] if len(calls) == 1 else [{'id': 'p', 'quantity': '1'}]
        return httpx.Response(200, json={'cartId': 'cart', 'cartVersion': 1 if len(calls) == 1 else 2, 'items': items})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = CartClient(http, {'pageData': {'passportInfo': {'status': 'VALID'}}}, [65.0, 40.0], 'сум')
        result = await client.set_item('p', 1, 100)
        assert result['items'] == [{'id': 'p', 'quantity': '1'}]
        assert len(calls) == 3


@pytest.mark.asyncio
async def test_unverified_readback_fails_closed():
    from lavka_cart import CartClient
    from lavka_uz import UpstreamError
    def handle(request):
        if request.url.path.endswith('/update'):
            return httpx.Response(200, json={'ok': True})
        return httpx.Response(200, json={'cartId': 'cart', 'cartVersion': 1, 'items': []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        c = CartClient(http, {'pageData': {'passportInfo': {'status': 'VALID'}}}, [65.0, 40.0], 'сум')
        with pytest.raises(UpstreamError, match='readback'):
            await c.set_item('p', 1, 100)


def test_rejects_unauthenticated_and_ruble_context():
    from lavka_cart import CartClient
    from lavka_uz import UpstreamError
    with pytest.raises(UpstreamError, match='authenticated'):
        CartClient(None, {'pageData': {'passportInfo': {'status': 'INVALID_PARAMS'}}}, [69, 41], 'сум')
    with pytest.raises(ValueError, match='currency'):
        CartClient(None, {'pageData': {'passportInfo': {'status': 'VALID'}}}, [69, 41], '₽')
