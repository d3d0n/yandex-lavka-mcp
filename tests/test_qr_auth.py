import json
from urllib.parse import parse_qs

import httpx
import pytest

from lavka_uz import UpstreamError


@pytest.mark.asyncio
async def test_qr_start_returns_validated_link_and_pending_status():
    from qr_auth import PassportQR
    def handle(request):
        assert request.url.host == 'passport.yandex.uz'
        if request.method == 'GET':
            return httpx.Response(200, text='<script>window.__CSRF__ = "csrf-value"</script>')
        assert request.headers['x-csrf-token'] == 'csrf-value'
        if request.url.path.endswith('/password/submit'):
            assert json.loads(request.content)['retpath'] == 'https://lavka.yandex.uz/'
            return httpx.Response(200, json={'track_id': 'track', 'csrf_token': 'opaque'})
        if request.url.path.endswith('/magic/code'):
            assert parse_qs(request.content.decode())['magic_track_id'] == ['track']
            return httpx.Response(200, json={'link': 'https://passport.yandex.uz/auth/magic/code/?track_id=track'})
        assert request.url.path.endswith('/magic/code/status')
        return httpx.Response(200, json={})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        auth = PassportQR(http)
        link = await auth.start()
        assert link.startswith('https://passport.yandex.uz/')
        assert await auth.poll() is False


@pytest.mark.asyncio
async def test_qr_rejects_external_link():
    from qr_auth import PassportQR
    def handle(request):
        if request.method == 'GET':
            return httpx.Response(200, text='__CSRF__ = "csrf-value"')
        if request.url.path.endswith('/password/submit'):
            return httpx.Response(200, json={'track_id': 'track'})
        return httpx.Response(200, json={'link': 'https://evil.example/qr'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(UpstreamError):
            await PassportQR(http).start()


@pytest.mark.asyncio
async def test_qr_completion_requires_confirmed_state_and_session_cookie():
    from qr_auth import PassportQR
    def handle(request):
        if request.method == 'GET':
            return httpx.Response(200, text='__CSRF__ = "csrf-value"')
        if request.url.path.endswith('/password/submit'):
            return httpx.Response(200, json={'track_id': 'track'})
        if request.url.path.endswith('/magic/code/status'):
            return httpx.Response(200, json={'state': 'otp_auth_finished', 'trackId': 'confirmed'})
        if request.url.path.endswith('/sessions/get_session'):
            assert parse_qs(request.content.decode())['track_id'] == ['confirmed']
            return httpx.Response(200, json={'status': 'ok'}, headers={'set-cookie': 'Session_id=secret; Domain=.yandex.uz; Path=/; Secure; HttpOnly'})
        return httpx.Response(200, json={'link': 'https://passport.yandex.uz/qr'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        auth = PassportQR(http)
        await auth.start()
        assert await auth.poll() is True
        assert 'Session_id' in http.cookies
