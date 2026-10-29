import httpx
import pytest

import lavka_order_mcp as orders


@pytest.mark.asyncio
async def test_fee_rejection_gives_safe_fresh_confirmation_guidance(tmp_path, monkeypatch):
    monkeypatch.setattr(orders, 'GUARD', tmp_path / 'guard')
    monkeypatch.setattr(orders, 'STATE', tmp_path / 'previews')
    binding = {'cart': {'cartId': 'c', 'cartVersion': 1, 'orderFlowVersion': 'v', 'totalPriceValue': '100', 'items': [{'id': 'x'}]}, 'position': {'location': [69.2, 41.3]}, 'card': {'type': 'card', 'id': 'id'}, 'index': 0, 'suffix': '1234'}
    async def snap(*args): return binding, {}
    monkeypatch.setattr(orders, 'snapshot', snap)
    calls = []
    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(400, json={'message': 'grocery_unavailable_for_checkout', 'details': {'error': {'code': 'bad_service_fee_v2'}}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        http.cookies.set('Session_id', 'test', domain='.yandex.uz', path='/')
        preview = await orders.preview(http, 0, '1234')
        result = await orders.submit(http, preview['preview_token'], '100', True)
        assert result['outcome'] == 'rejected'
        assert result['recovery']['kind'] == 'checkout_price_or_fee_changed'
        assert result['recovery']['old_total_uzs'] == '100'
        assert result['recovery']['automatic_retry'] is False
        assert result['recovery']['fresh_preview_required'] is True
        assert result['recovery']['explicit_confirmation_required'] is True
        guidance = ' '.join(result['recovery']['instructions']).lower()
        for term in ('cart', 'preview', 'old', 'new', 'change', 'budget', 'confirm'):
            assert term in guidance
        assert 'bad_service_fee_v2' in result['codes']
        with pytest.raises(ValueError, match='consumed'):
            await orders.submit(http, preview['preview_token'], '100', True)
        assert (await orders.preview(http, 0, '1234'))['preview_token'] != preview['preview_token']
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body,expected_recovery', [
    (400, {'message': 'grocery_unavailable_for_checkout', 'details': {'error': {'code': 'bad_service_fee'}}}, True),
    (500, {'message': 'grocery_unavailable_for_checkout', 'details': {'error': {'code': 'bad_service_fee_v2'}}}, False),
    (400, {'code': 'other_error', 'detail': 'bad_service_fee_v2'}, False),
    (400, {'code': 'grocery_unavailable_for_checkout', 'detail': 'other_error'}, False),
])
async def test_guidance_only_for_recognized_rejections(tmp_path, monkeypatch, status, body, expected_recovery):
    monkeypatch.setattr(orders, 'GUARD', tmp_path / 'guard')
    monkeypatch.setattr(orders, 'STATE', tmp_path / 'previews')
    binding = {'cart': {'cartId': 'c', 'cartVersion': 1, 'orderFlowVersion': 'v', 'totalPriceValue': '10', 'items': [{'id': 'x'}]}, 'position': {'location': [69.2, 41.3]}, 'card': {'type': 'card', 'id': 'id'}, 'index': 0, 'suffix': '1234'}
    async def snap(*args): return binding, {}
    monkeypatch.setattr(orders, 'snapshot', snap)
    calls = []
    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(status, json=body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        http.cookies.set('Session_id', 'test', domain='.yandex.uz', path='/')
        preview = await orders.preview(http, 0, '1234')
        result = await orders.submit(http, preview['preview_token'], '10', True)
        assert ('recovery' in result) is expected_recovery
        if expected_recovery:
            assert 'bad_service_fee' in result['codes']
        if result['outcome'] == 'unknown':
            with pytest.raises(ValueError, match='quarantined'):
                await orders.preview(http, 0, '1234')
    assert len(calls) == 1
