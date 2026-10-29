import asyncio
import httpx
import pytest
from lavka_cancel import cancel_order, CancellationBlocked


def test_canceled_history_verifies_and_never_resubmits(tmp_path):
    calls = []
    async def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={})
    async def history():
        return {'orders': [{'order_id': 'test-order', 'status': 'canceled'}]}
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            kw = dict(http=http, props={'pageData': {'passportInfo': {'status': 'VALID'}}},
                      order_id='test-order', confirmed=True, state_path=tmp_path / 'cancel.sqlite', history=history)
            result = await cancel_order(**kw)
            assert result['cancellation_verified'] is True
            assert result['outcome'] == 'canceled'
            assert result['refund_status'] == 'unknown'
            again = await cancel_order(**kw)
            assert again['cancellation_verified'] is True
    asyncio.run(run())
    assert calls == ['/api/v1/providers/orders/v1/cancel']


def test_timeout_can_be_reconciled_only_by_exact_canceled_history(tmp_path):
    calls = []
    state = {'orders': []}
    async def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout('simulated')
    async def history(): return state
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            kw = dict(http=http, props={'pageData': {'passportInfo': {'status': 'VALID'}}},
                      order_id='o1', confirmed=True, state_path=tmp_path / 'cancel.sqlite', history=history)
            assert (await cancel_order(**kw))['outcome'] == 'unknown'
            state['orders'] = [{'order_id': 'o2', 'status': 'canceled'}]
            with pytest.raises(CancellationBlocked): await cancel_order(**kw)
            state['orders'] = [{'order_id': 'o1', 'status': 'canceled'}]
            assert (await cancel_order(**kw))['outcome'] == 'canceled'
    asyncio.run(run())
    assert len(calls) == 1


def test_error_response_reports_sanitized_diagnostics_without_retry(tmp_path):
    calls = []
    async def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"code": "order_cannot_cancel", "message": "private phone 123", "phone": "secret"})
    async def history(): return {"orders": []}
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            kw = dict(http=http, props={"pageData": {"passportInfo": {"status": "VALID"}}}, order_id="o1", confirmed=True, state_path=tmp_path / "s.sqlite", history=history)
            result = await cancel_order(**kw)
            assert result["http_status"] == 400
            assert result["upstream_error"]["error"]["code"] == "order_cannot_cancel"
            assert "private" not in str(result) and "secret" not in str(result)
            assert result["outcome"] == "unknown"
            with pytest.raises(CancellationBlocked): await cancel_order(**kw)
    asyncio.run(run())
    assert len(calls) == 1
