import json
import pytest
import httpx
from lavka_uz import Lavka, UpstreamError

@pytest.mark.asyncio
async def test_search_uses_uz_currency_and_surfaces_csrf_failure():
    def handle(request):
        if request.url.host == "yandex.uz":
            return httpx.Response(200, headers={"set-cookie": "yandexuid=anonymous; Domain=.yandex.uz; Path=/"})
        if request.method == "GET":
            assert "yandexuid=anonymous" in request.headers.get("cookie", "")
            return httpx.Response(200, text='<script id="__page_props__-data">{ "csrfToken":"bff", "authProxyCsrfToken":"proxy", "pageEnv":{"cityId":10335,"locale":{"lang":"ru","region":"RU"}}, "pageData":{"serviceInfo":{"currency":"UZS","currencySign":"сум"}} }</script>')
        assert request.url.host == "lavka.yandex.uz"
        assert request.headers["X-Csrf-Token"] == "proxy"
        assert request.headers["X-Csrf-Token-Bff"] == "bff"
        assert json.loads(request.content)["currencySign"] == "сум"
        return httpx.Response(401, json={"data":{"message":"[Csrf] Invalid token"}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = Lavka(http)
        with pytest.raises(UpstreamError, match="CSRF"):
            await client.search("молоко", 3, (65.0, 40.0))


def test_existing_cookie_jar_is_loaded_without_widening_domain(tmp_path, monkeypatch):
    import lavka_uz
    import http.cookiejar
    cookie = http.cookiejar.Cookie(0, "Session_id", "secret", None, False, ".yandex.ru", True, True, "/", True, True, None, True, None, None, {}, False)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"cookies": [cookie.__dict__]}))
    monkeypatch.setattr(lavka_uz, "STATE", str(state))
    client = lavka_uz.create_http()
    assert next(iter(client.cookies.jar)).domain == ".yandex.ru"
    request = client.build_request("GET", "https://lavka.yandex.uz/")
    assert "cookie" not in request.headers


@pytest.mark.asyncio
async def test_authenticated_search_uses_independent_anonymous_region_confirmation():
    def handle(request):
        if request.url.host == "yandex.uz":
            return httpx.Response(200, headers={"set-cookie": "yandexuid=anon; Domain=.yandex.uz; Path=/"})
        if request.method == "GET":
            auth = "Session_id=valid" in request.headers.get("cookie", "")
            page = {"csrfToken": "bff", "authProxyCsrfToken": "proxy", "pageData": {"passportInfo": {"status": "VALID"}, "needInitStartupRequest": False} if auth else {"serviceInfo": {"currency": "UZS", "currencySign": "сум"}}}
            return httpx.Response(200, text='<script id="__page_props__-data">' + json.dumps(page) + '</script>')
        assert "Session_id=valid" in request.headers.get("cookie", "")
        assert json.loads(request.content)["currencySign"] == "сум"
        return httpx.Response(200, json={"cacheProducts": [{"id": "x", "title": "Milk", "currentPrice": 100}]})
    transport = httpx.MockTransport(handle)
    async with httpx.AsyncClient(transport=transport) as http, httpx.AsyncClient(transport=transport) as region_http:
        http.cookies.set("Session_id", "valid", domain=".yandex.uz", path="/")
        client = Lavka(http, region_http=region_http)
        result = await client.search("milk", 3, (65.0, 40.0))
        assert result["products"][0]["currency"] == "UZS"
