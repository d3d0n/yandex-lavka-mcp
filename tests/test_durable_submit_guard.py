import asyncio
import httpx
import pytest
from lavka_live_transport import submit_once, AttemptGuard, AttemptBlocked


def test_durable_guard_blocks_second_submission_across_instances(tmp_path):
    calls = []
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: (calls.append(1), httpx.Response(400, json={'message': 'grocery_unavailable_for_checkout'}))[1])) as http:
            props = {'pageData': {'passportInfo': {'status': 'VALID'}}}
            await submit_once(http, props, {'cartId': 'one'}, guard=AttemptGuard(tmp_path / 'attempt.sqlite'))
            with pytest.raises(AttemptBlocked):
                await submit_once(http, props, {'cartId': 'two'}, guard=AttemptGuard(tmp_path / 'attempt.sqlite'))
    asyncio.run(run())
    assert len(calls) == 1
