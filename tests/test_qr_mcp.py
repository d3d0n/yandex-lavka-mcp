import pytest

@pytest.mark.asyncio
async def test_start_hides_qr_link_and_prevents_existing_session_replacement(tmp_path):
    from qr_mcp import QRLogin
    class Manager:
        def __init__(self): self.auth = None
        async def start(self):
            self.auth = object()
            return {'status': 'pending', 'qr_image': str(tmp_path / 'qr.png'), 'qr_url': 'SECRET'}
        async def close(self): self.auth = None
    session = tmp_path / 'session.json'
    session.write_text('existing')
    login = QRLogin(session, Manager())
    assert (await login.start())['status'] == 'replacement_requires_approval'
    result = await login.start(replace_existing=True)
    assert result['status'] == 'pending'
    assert result['qr_url'] == 'SECRET'


@pytest.mark.asyncio
async def test_verified_session_is_saved_and_status_checked(tmp_path):
    from qr_mcp import QRLogin
    class Manager:
        auth = None
        session_path = tmp_path / 'staged'
        async def start(self):
            self.auth = object()
            return {'qr_image': 'local.png', 'qr_url': 'SECRET'}
        async def poll(self):
            self.session_path.write_text('new session')
            self.auth = None
            return {'status': 'session_saved_not_verified_by_lavka'}
        async def close(self): self.auth = None
    async def verify(path): return path.read_text() == 'new session'
    session = tmp_path / 'session'
    login = QRLogin(session, Manager(), verify)
    await login.start()
    assert (await login.status())['status'] == 'authenticated'
    assert session.read_text() == 'new session'
    assert (await login.status())['status'] == 'authenticated'


@pytest.mark.asyncio
async def test_concurrent_session_change_is_not_overwritten(tmp_path):
    from qr_mcp import QRLogin
    class Manager:
        auth = None
        session_path = tmp_path / 'staged'
        async def start(self):
            self.auth = object()
            return {'qr_image': 'local.png', 'qr_url': 'SECRET'}
        async def poll(self):
            self.session_path.write_text('new')
            self.auth = None
            return {'status': 'session_saved_not_verified_by_lavka'}
        async def close(self): self.auth = None
    async def verify(path): return True
    session = tmp_path / 'session'
    login = QRLogin(session, Manager(), verify)
    await login.start()
    session.write_text('other')
    assert (await login.status())['status'] == 'session_changed'
    assert session.read_text() == 'other'


@pytest.mark.asyncio
async def test_registered_tools_are_discoverable(tmp_path):
    from mcp.server.fastmcp import FastMCP
    from qr_mcp import register_qr_tools
    server = FastMCP('test')
    register_qr_tools(server, tmp_path / 'session')
    names = {tool.name for tool in await server.list_tools()}
    assert {'login_start', 'qr_login_status', 'qr_login_cancel'} <= names
