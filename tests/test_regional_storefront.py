import httpx
import pytest

from regional_storefront import RegionalStorefront


@pytest.mark.asyncio
async def test_regional_search_isolates_host_and_currency():
    calls = []
    async def handle(request):
        calls.append((request.url.host, request.url.path))
        if request.url.host == 'yandex.kz':
            return httpx.Response(200, headers={'Set-Cookie': 'yandexuid=123; Domain=.yandex.kz; Path=/'})
        if request.method == 'GET':
            return httpx.Response(200, text='<script id="__page_props__-data">{"pageData":{"serviceInfo":{"currency":"KZT","currencySign":"₸"}}}</script>')
        return httpx.Response(200, json={'cacheProducts':[{'id':'1','title':'Молоко','currentPrice':'100'}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        result = await RegionalStorefront('KZ', http).search('молоко', 5, 76.945, 43.2389)
    assert result['country'] == 'KZ'
    assert result['products'][0]['currency'] == 'KZT'
    assert calls == [('yandex.kz','/favicon.ico'), ('lavka.yandex.kz','/'), ('lavka.yandex.kz','/api/v1/providers/search/v3/lavka')]
