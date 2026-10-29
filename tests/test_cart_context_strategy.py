"""Safety regressions exposed by the read-only cart context investigation.

Fixtures are synthetic; no network traffic or real cart writes occur.
"""
import json

import httpx
import pytest

from lavka_cart import CartClient
from lavka_uz import UpstreamError


PROPS = {"pageData": {"passportInfo": {"status": "VALID"}}}
LOCATION = [69.1, 41.3]


@pytest.mark.asyncio
async def test_write_fails_closed_when_verification_switched_cart_identity():
    calls = []

    def handle(request):
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path.endswith("/update"):
            return httpx.Response(200, json={"ok": True})
        if len(calls) == 1:
            return httpx.Response(200, json={"cartId": "synthetic-A", "cartVersion": 1, "items": []})
        return httpx.Response(200, json={"cartId": "synthetic-B", "cartVersion": 2,
                                        "items": [{"id": "p", "quantity": "1"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        c = CartClient(http, PROPS, LOCATION, "сум")
        with pytest.raises(UpstreamError, match="(?i)(context|identity|cart)"):
            await c.set_item("p", 1, 100)


@pytest.mark.asyncio
async def test_write_fails_closed_when_unrelated_item_disappears():
    calls = []

    def handle(request):
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path.endswith("/update"):
            return httpx.Response(200, json={"ok": True})
        if len(calls) == 1:
            return httpx.Response(200, json={"cartId": "synthetic-A", "cartVersion": 1,
                                            "items": [{"id": "q", "quantity": "2"}]})
        return httpx.Response(200, json={"cartId": "synthetic-A", "cartVersion": 2,
                                        "items": [{"id": "p", "quantity": "1"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        c = CartClient(http, PROPS, LOCATION, "сум")
        with pytest.raises(UpstreamError, match="(?i)(unrelated|changed|preserv|cart)"):
            await c.set_item("p", 1, 100)
