import asyncio
import httpx
from lavka_live_transport import submit_once, AttemptGuard


def test_submit_rejection_is_sanitized_and_not_retried(tmp_path):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(400, json={"message":"grocery_unavailable_for_checkout", "details":{"error":{"code":"bad_service_fee_v2", "phone":"secret"}}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await submit_once(client, {"pageData":{"passportInfo":{"status":"VALID"}}}, {"cartId":"test"}, guard=AttemptGuard(tmp_path / 'state.sqlite'))
    result = asyncio.run(run())
    assert result == {"outcome":"rejected", "http_status":400, "codes":["grocery_unavailable_for_checkout", "bad_service_fee_v2"]}
    assert len(calls) == 1
    assert calls[0].url.path == "/api/v1/providers/orders/v2/submit"
    assert "secret" not in str(result)


def test_network_error_is_unknown_and_not_retried(tmp_path):
    calls = []
    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout('secret url')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await submit_once(client, {'pageData': {'passportInfo': {'status': 'VALID'}}}, {'cartId': 'test'}, guard=AttemptGuard(tmp_path / 'state.sqlite'))
    assert asyncio.run(run()) == {'outcome': 'unknown'}
    assert len(calls) == 1


def test_nonstandard_server_error_does_not_claim_rejection(tmp_path):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500, json={'error': {'message': 'secret'}}))) as client:
            return await submit_once(client, {'pageData': {'passportInfo': {'status': 'VALID'}}}, {'cartId': 'test'}, guard=AttemptGuard(tmp_path / 'state.sqlite'))
    result = asyncio.run(run())
    assert result['outcome'] == 'unknown'
    assert result['unrecognized_code'] is True
    assert 'secret' not in str(result)
