"""Browser-free Yandex Passport Uzbekistan QR flow; opaque state stays local."""
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from lavka_errors import UpstreamError

PASSPORT = 'https://passport.yandex.uz'
BFF = PASSPORT + '/pwl-yandex/api/passport'


def write_qr_image(link, target):
    """Create a private PNG; the image is a temporary login capability."""
    import qrcode
    target = Path(target).expanduser()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.lavka-qr-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            qrcode.make(link).save(stream, format='PNG')
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_session(http, target):
    """Atomically save scoped cookies with owner-only permissions."""
    target = Path(target).expanduser()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.lavka-session-', dir=target.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'cookies': [cookie.__dict__ for cookie in http.cookies.jar]}, stream)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class PassportQR:
    def __init__(self, http):
        self.http = http
        self._csrf = None
        self._state = None
        self._completed = False

    async def _post(self, path, **kwargs):
        response = await self.http.post(BFF + path, headers={
            'X-CSRF-Token': self._csrf,
            'Origin': PASSPORT,
            'Referer': PASSPORT + '/pwl-yandex',
        }, follow_redirects=False, **kwargs)
        if response.status_code != 200:
            raise UpstreamError(f'Passport request failed (HTTP {response.status_code})')
        try:
            data = response.json()
        except ValueError:
            raise UpstreamError('Passport returned non-JSON') from None
        if not isinstance(data, dict):
            raise UpstreamError('Unexpected Passport response')
        if data.get('errors') or data.get('error') or data.get('type') == 'captcha':
            raise UpstreamError('Passport rejected the request or requires verification')
        return data

    async def start(self):
        response = await self.http.get(PASSPORT + '/pwl-yandex', follow_redirects=False)
        if response.status_code != 200:
            raise UpstreamError(f'Passport bootstrap failed (HTTP {response.status_code})')
        match = re.search(r'__CSRF__\s*=\s*"([^\"]+)"', response.text)
        if not match:
            raise UpstreamError('Passport bootstrap CSRF missing or verification required')
        self._csrf = match.group(1)
        state = await self._post('/auth/password/submit', json={'retpath': 'https://lavka.yandex.uz/'})
        if not isinstance(state.get('track_id'), str) or not state['track_id']:
            raise UpstreamError('Passport track missing')
        result = await self._post('/auth/magic/code', data={
            'location_id': '0', 'magic_track_id': state['track_id'], 'track_id': ''})
        link = result.get('link')
        try:
            parsed = urlsplit(link)
            safe = (parsed.scheme == 'https' and parsed.hostname == 'passport.yandex.uz'
                    and parsed.username is None and parsed.password is None
                    and parsed.port in (None, 443))
        except (ValueError, TypeError):
            safe = False
        if not safe:
            raise UpstreamError('Passport returned an unsafe QR link')
        self._state = state
        return link

    async def poll(self):
        if self._state is None or self._completed:
            raise UpstreamError('No active QR session')
        result = await self._post('/auth/magic/code/status', json=self._state)
        if result.get('state') != 'otp_auth_finished':
            return False
        track = result.get('trackId')
        if not isinstance(track, str) or not track:
            raise UpstreamError('Confirmed Passport session missing track')
        await self._post('/sessions/get_session', data={'track_id': track})
        if not any(c.name == 'Session_id' and c.domain in ('yandex.uz', '.yandex.uz') and c.value for c in self.http.cookies.jar):
            raise UpstreamError('Passport did not issue an Uzbekistan session cookie')
        self._completed = True
        self._state = None
        return True
