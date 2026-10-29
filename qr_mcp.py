"""Local-only QR login tools; returns an image and short-lived link."""
import asyncio
import hashlib
import os
import time
from pathlib import Path


class QRLogin:
    def __init__(self, session_path, manager, verify=None, ttl=180):
        self.session = Path(session_path)
        self.manager = manager
        self.verify = verify
        self.ttl = ttl
        self.lock = asyncio.Lock()
        self.started = None
        self.original = None

    def _fingerprint(self):
        try:
            return hashlib.sha256(self.session.read_bytes()).digest()
        except FileNotFoundError:
            return None

    async def start(self, replace_existing=False):
        async with self.lock:
            if self.started is not None:
                if time.monotonic() - self.started < self.ttl:
                    return {'status': 'already_pending'}
                await self.manager.close()
                self.started = None
            original = self._fingerprint()
            if original is not None and not replace_existing:
                return {'status': 'replacement_requires_approval'}
            try:
                result = await self.manager.start()
            except Exception:
                return {'status': 'error', 'note': 'Could not start QR login.'}
            self.original = original
            self.started = time.monotonic()
            return {'status': 'pending', 'qr_image': result['qr_image'], 'qr_url': result['qr_url'], 'note': 'Private login capability: share only with the intended user.'}

    async def status(self):
        async with self.lock:
            if self.started is None:
                if not self.session.exists():
                    return {'status': 'login_required'}
                try:
                    valid = await self.verify(self.session)
                except Exception:
                    return {'status': 'verification_unavailable'}
                return {'status': 'authenticated' if valid else 'login_required'}
            if time.monotonic() - self.started >= self.ttl:
                await self.manager.close()
                self.started = None
                return {'status': 'expired'}
            try:
                result = await self.manager.poll()
                if result['status'] == 'pending':
                    return {'status': 'pending'}
                staged = self.manager.session_path
                if not await self.verify(staged):
                    return {'status': 'verification_failed'}
                if self._fingerprint() != self.original:
                    return {'status': 'session_changed', 'note': 'Existing session was not replaced.'}
                if self.original is None:
                    os.link(staged, self.session)
                    staged.unlink()
                else:
                    os.replace(staged, self.session)
                return {'status': 'authenticated'}
            except Exception:
                return {'status': 'error', 'note': 'Login or verification failed; existing session was not replaced.'}
            finally:
                if self.manager.auth is None:
                    self.started = None
                    self.manager.session_path.unlink(missing_ok=True)

    async def cancel(self):
        async with self.lock:
            await self.manager.close()
            self.manager.session_path.unlink(missing_ok=True)
            self.started = None
            return {'status': 'cancelled'}


def register_qr_tools(mcp, session_path, guard=None):
    """Register once on a trusted, local stdio server; QR file is owner-only."""
    from http.cookiejar import Cookie
    import json
    import httpx
    from qr_runtime import QRManager

    if guard is None:
        guard = lambda fn: fn

    session = Path(session_path).expanduser()
    session.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Per-process paths avoid clobbering another server's pending login.
    import secrets
    suffix = secrets.token_hex(12)
    manager = QRManager(session.parent / ('.qr-session-' + suffix), session.parent / ('.qr-image-' + suffix + '.png'))

    async def verify(path):
        from lavka_uz import Lavka
        async with httpx.AsyncClient(timeout=25, follow_redirects=False, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}) as http:
            data = json.loads(path.read_text())
            for item in data['cookies']:
                params = dict(item)
                params['rest'] = params.pop('_rest', {})
                http.cookies.jar.set_cookie(Cookie(**params))
            props = await Lavka(http).bootstrap()
            return props.get('pageData', {}).get('passportInfo', {}).get('status') == 'VALID'

    login = QRLogin(session, manager, verify)

    @mcp.tool()
    @guard
    async def login_start(replace_existing: bool = False):
        """Start login and return a QR image plus its short-lived link. Share only with the intended user; client logs may contain the link. Set replace_existing only with approval."""
        from mcp.types import TextContent, ImageContent
        import base64
        result = await login.start(replace_existing)
        image_path = result.pop('qr_image', None)
        content = [TextContent(type='text', text=json.dumps(result))]
        if image_path:
            try:
                image = Path(image_path).read_bytes()
            except OSError:
                await login.cancel()
                return [TextContent(type='text', text='{"status":"error","note":"QR image unavailable; login cancelled."}')]
            content.append(ImageContent(type='image', data=base64.b64encode(image).decode('ascii'), mimeType='image/png'))
        return content

    @mcp.tool()
    @guard
    async def qr_login_status() -> dict:
        """Poll QR login and verify Lavka session; never reveals credentials."""
        return await login.status()

    @mcp.tool()
    async def qr_login_cancel() -> dict:
        """Cancel pending login and delete its QR image, regardless of selected region."""
        return await login.cancel()

    return login
