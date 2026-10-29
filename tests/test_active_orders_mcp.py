import json
import httpx
import pytest
import lavka_uz


@pytest.mark.asyncio
async def test_active_orders_reads_authenticated_verified_empty_array(monkeypatch):
    calls = []
    def handle(request):
        calls.append((request.method, request.url.path))
        if request.url.host == 'yandex.uz':
            return httpx.Response(200, headers={'set-cookie': 'yandexuid=anon; Domain=.yandex.uz; Path=/'})
        if request.url.path == '/':
            props = {'pageData': {'passportInfo': {'status': 'VALID'}}}
            return httpx.Response(200, text='<script id="__page_props__-data">' + json.dumps(props) + '</script>')
        assert request.url.path == '/api/v1/providers/orders-tracking/v1/tracked-orders'
        return httpx.Response(200, json=[])
    monkeypatch.setattr(lavka_uz, 'create_http', lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    result = await lavka_uz.active_orders()
    assert result['active_order_count'] == 0
    assert result['history_complete'] is False
    assert result['reconciles_uncertain_submission'] is False
    assert calls[-1][0] == 'GET'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,data', [('INVALID', []), ('VALID', {'orders': []})])
async def test_active_orders_rejects_unauthenticated_or_unverified_shapes(monkeypatch, status, data):
    def handle(request):
        if request.url.host == 'yandex.uz':
            return httpx.Response(200, headers={'set-cookie': 'yandexuid=anon; Domain=.yandex.uz; Path=/'})
        if request.url.path == '/':
            props = {'pageData': {'passportInfo': {'status': status}}}
            return httpx.Response(200, text='<script id="__page_props__-data">' + json.dumps(props) + '</script>')
        return httpx.Response(200, json=data)
    monkeypatch.setattr(lavka_uz, 'create_http', lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    with pytest.raises(lavka_uz.UpstreamError) as exc:
        await lavka_uz.active_orders()
    assert 'secret' not in str(exc.value)


@pytest.mark.asyncio
async def test_nonempty_tracking_feed_exposes_only_entry_count(monkeypatch):
    def handle(request):
        if request.url.host == 'yandex.uz':
            return httpx.Response(200, headers={'set-cookie': 'yandexuid=anon; Domain=.yandex.uz; Path=/'})
        if request.url.path == '/':
            props = {'pageData': {'passportInfo': {'status': 'VALID'}}}
            return httpx.Response(200, text='<script id="__page_props__-data">' + json.dumps(props) + '</script>')
        return httpx.Response(200, json=[{'id': 'secret'}])
    monkeypatch.setattr(lavka_uz, 'create_http', lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    result = await lavka_uz.active_orders()
    assert result['feed_entry_count'] == 1
    assert result['active_order_count'] is None
    assert result['reconciles_uncertain_submission'] is False
    assert 'secret' not in str(result)
