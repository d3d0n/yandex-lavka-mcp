import json
import httpx
import pytest
from lavka_uz import Lavka, UpstreamError

@pytest.mark.asyncio
async def test_saved_address_count_requires_valid_session_and_hides_details():
    def handle(request):
        if request.url.host == 'yandex.uz':
            return httpx.Response(200, headers={'set-cookie': 'yandexuid=anon; Domain=.yandex.uz; Path=/'})
        if request.method == 'GET':
            page = {'csrfToken': 'x', 'authProxyCsrfToken': 'y', 'pageData': {'passportInfo': {'status': 'VALID'}}}
            return httpx.Response(200, text='<script id="__page_props__-data">' + json.dumps(page) + '</script>')
        assert request.url.path == '/api/v1/providers/address/v1/get-favorite-addresses'
        return httpx.Response(200, json=[{'id': 'private', 'address': 'private'}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        assert await Lavka(http).saved_address_count() == {'count': 1}

@pytest.mark.asyncio
async def test_saved_address_count_rejects_anonymous_session():
    async with httpx.AsyncClient() as http:
        l = Lavka(http)
        l.props = {'pageData': {'passportInfo': {'status': 'INVALID_PARAMS'}}}
        with pytest.raises(UpstreamError, match='authenticated'):
            await l.saved_address_count()
