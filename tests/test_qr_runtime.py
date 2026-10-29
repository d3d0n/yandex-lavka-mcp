import pytest


@pytest.mark.asyncio
async def test_qr_pending_status_keeps_live_session_and_writes_private_image(tmp_path, monkeypatch):
    import qr_auth
    from qr_runtime import QRManager
    class FakeAuth:
        def __init__(self, http): pass
        async def start(self): return 'https://passport.yandex.uz/qr'
        async def poll(self): return False
    monkeypatch.setattr(qr_auth, 'PassportQR', FakeAuth)
    manager = QRManager(tmp_path / 'state.json', tmp_path / 'qr.png')
    result = await manager.start()
    assert result['qr_image'] == str(tmp_path / 'qr.png')
    assert result['status'] == 'pending'
    assert (await manager.poll())['status'] == 'pending'
    await manager.close()


@pytest.mark.asyncio
async def test_qr_confirmation_saves_private_session_and_closes(tmp_path, monkeypatch):
    import qr_auth
    from qr_runtime import QRManager
    class FakeAuth:
        def __init__(self, http): self.http = http
        async def start(self): return 'https://passport.yandex.uz/qr'
        async def poll(self):
            self.http.cookies.set('Session_id', 'secret', domain='.yandex.uz', path='/')
            return True
    monkeypatch.setattr(qr_auth, 'PassportQR', FakeAuth)
    manager = QRManager(tmp_path / 'state.json', tmp_path / 'qr.png')
    await manager.start()
    assert (await manager.poll())['status'] == 'session_saved_not_verified_by_lavka'
    assert (tmp_path / 'state.json').exists()
    assert not (tmp_path / 'qr.png').exists()
