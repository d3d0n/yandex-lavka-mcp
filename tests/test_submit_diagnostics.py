import json

import httpx
import pytest

import lavka_order_mcp as orders


@pytest.mark.asyncio
async def test_unknown_structured_error_exposes_sanitized_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(orders, 'GUARD', tmp_path / 'guard')
    monkeypatch.setattr(orders, 'STATE', tmp_path / 'previews')
    binding = {'cart': {'cartId': 'c', 'cartVersion': 1, 'orderFlowVersion': 'v', 'totalPriceValue': '10', 'items': [{'id': 'x'}]}, 'position': {'location': [69.2, 41.3]}, 'card': {'type': 'card', 'id': 'id'}, 'index': 0, 'suffix': '1234'}
    async def snap(*args): return binding, {}
    monkeypatch.setattr(orders, 'snapshot', snap)
    calls = []
    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(409, json={'error': {'code': 'region_not_supported', 'message': 'Private address and phone', 'details': {'reason': 'payment_declined', 'retryable': False}, 'body': {'address': 'secret address'}, 'token': 'secret token'}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        http.cookies.set('Session_id', 'test', domain='.yandex.uz', path='/')
        preview = await orders.preview(http, 0, '1234')
        result = await orders.submit(http, preview['preview_token'], '10', True)
        assert result['outcome'] == 'unknown'
        assert result['codes'] == []
        assert result['upstream_error'] == {'http_status': 409, 'error': {'error': {'code': 'region_not_supported', 'message': '[redacted]', 'details': {'reason': 'payment_declined', 'retryable': False}}}}
        assert 'reason' not in result['note'].lower()
        assert 'Private address' not in json.dumps(result) and 'secret' not in json.dumps(result)
        with pytest.raises(ValueError, match='quarantined'):
            await orders.preview(http, 0, '1234')
    assert len(calls) == 1
