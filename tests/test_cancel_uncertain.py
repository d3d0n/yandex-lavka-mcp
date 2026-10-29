import asyncio
import httpx
import pytest
from lavka_cancel import cancel_order, CancellationBlocked


def test_uncertain_attempt_blocks_same_order_but_not_different_order(tmp_path):
    calls = []
    async def handler(request):
        calls.append(request.content)
        raise httpx.ReadTimeout('simulated')
    async def history():
        return {'orders': []}
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            kw = dict(http=http, props={'pageData': {'passportInfo': {'status': 'VALID'}}},
                      order_id='test-order', confirmed=True, state_path=tmp_path / 'cancel.sqlite', history=history)
            assert (await cancel_order(**kw))['outcome'] == 'unknown'
            with pytest.raises(CancellationBlocked):
                await cancel_order(**kw)
            kw['order_id'] = 'another-order'
            assert (await cancel_order(**kw))['outcome'] == 'unknown'
    asyncio.run(run())
    assert len(calls) == 2
