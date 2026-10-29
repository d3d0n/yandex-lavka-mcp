import base64
import pytest


@pytest.mark.asyncio
async def test_server_registers_qr_and_returns_image_and_opt_in_link(monkeypatch, tmp_path):
    import lavka_uz
    import qr_runtime
    class FakeManager:
        def __init__(self, session_path, image_path):
            self.session_path, self.image_path, self.auth = session_path, image_path, None
        async def start(self):
            self.auth = object()
            self.image_path.write_bytes(b'fake-png')
            return {'qr_image': str(self.image_path), 'qr_url': 'https://example.test/SECRET'}
        async def close(self):
            self.auth = None
            self.image_path.unlink(missing_ok=True)
    monkeypatch.setattr(qr_runtime, 'QRManager', FakeManager)
    from mcp.server.fastmcp import FastMCP
    from qr_mcp import register_qr_tools
    assert 'login_start' in {t.name for t in await lavka_uz.mcp.list_tools()}
    server = FastMCP('test')
    register_qr_tools(server, tmp_path / 'session')
    result = await server.call_tool('login_start', {})
    assert 'https://example.test/SECRET' in str(result)
    assert any(x.type == 'image' and base64.b64decode(x.data) == b'fake-png' for x in result)
    await server.call_tool('qr_login_cancel', {})


@pytest.mark.asyncio
@pytest.mark.parametrize('region', ['RU', 'KZ'])
async def test_pending_login_can_be_cancelled_after_switching_region(monkeypatch, tmp_path, region):
    import lavka_uz
    import qr_runtime
    from mcp.server.fastmcp import FastMCP
    from qr_mcp import register_qr_tools

    class FakeManager:
        def __init__(self, session_path, image_path):
            self.session_path, self.image_path, self.auth = session_path, image_path, None
        async def start(self):
            self.auth = object()
            self.image_path.write_bytes(b'qr')
            self.session_path.write_text('staged')
            return {'qr_image': str(self.image_path), 'qr_url': 'secret'}
        async def close(self):
            self.auth = None
            self.image_path.unlink(missing_ok=True)

    monkeypatch.setattr(qr_runtime, 'QRManager', FakeManager)
    server = FastMCP('test')
    login = register_qr_tools(server, tmp_path / 'session', lavka_uz.uz_only)
    try:
        await lavka_uz.select_region('UZ')
        await server.call_tool('login_start', {})
        await lavka_uz.select_region(region)
        result = await server.call_tool('qr_login_cancel', {})
        assert 'cancelled' in str(result)
        assert login.started is None and login.manager.auth is None
        assert not login.manager.image_path.exists()
        assert not login.manager.session_path.exists()
    finally:
        await lavka_uz.select_region('UZ')
