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
