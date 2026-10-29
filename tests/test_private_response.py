import asyncio
import os
import stat
import httpx
import pytest
from lavka_live_transport import AttemptGuard, submit_once


def test_full_response_written_privately_without_headers(tmp_path):
    path = tmp_path / 'response.json'
    body = b'{"unknown":{"sensitive":"value"},"error":"bad"}'
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(400, content=body, headers={'set-cookie': 'secret'}))) as http:
            return await submit_once(http, {'pageData': {'passportInfo': {'status': 'VALID'}}}, {'x': 1}, guard=AttemptGuard(tmp_path / 'guard'), response_path=path)
    asyncio.run(run())
    assert path.read_bytes() == body
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert b'set-cookie' not in path.read_bytes()


def test_existing_capture_is_never_overwritten_or_submitted(tmp_path):
    path = tmp_path / 'response.json'
    path.write_text('existing')
    calls = []
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r))) as http:
            with pytest.raises(FileExistsError):
                await submit_once(http, {'pageData': {'passportInfo': {'status': 'VALID'}}}, {'x': 1}, guard=AttemptGuard(tmp_path / 'guard'), response_path=path)
    asyncio.run(run())
    assert not calls
    assert path.read_text() == 'existing'
