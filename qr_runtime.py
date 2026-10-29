"""Single-process QR login manager; no account or checkout writes."""
import asyncio
from pathlib import Path

import httpx
import qr_auth
from lavka_errors import UpstreamError

# HTTPX's default INFO logger includes full URLs. QR URL query strings are
# temporary login capabilities, so never emit them through this client.
import logging
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)


class QRManager:
    def __init__(self, session_path, image_path):
        self.session_path = Path(session_path)
        self.image_path = Path(image_path)
        self.http = None
        self.auth = None
        self.lock = asyncio.Lock()

    async def start(self):
        async with self.lock:
            if self.auth is not None:
                raise UpstreamError('An active QR login already exists')
            self.http = httpx.AsyncClient(timeout=25, follow_redirects=False, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
            try:
                self.auth = qr_auth.PassportQR(self.http)
                link = await self.auth.start()
                qr_auth.write_qr_image(link, self.image_path)
                return {'status': 'pending', 'qr_image': str(self.image_path), 'qr_url': link}
            except BaseException:
                await self.close()
                raise

    async def poll(self):
        async with self.lock:
            if self.auth is None:
                raise UpstreamError('No active QR login')
            if not await self.auth.poll():
                return {'status': 'pending'}
            qr_auth.save_session(self.http, self.session_path)
            await self.close()
            return {'status': 'session_saved_not_verified_by_lavka'}

    async def close(self):
        if self.http is not None:
            await self.http.aclose()
        self.http = self.auth = None
        self.image_path.unlink(missing_ok=True)
