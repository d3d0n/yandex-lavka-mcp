import pytest
import json
import lavka_uz
import lavka_order_mcp
import httpx


@pytest.mark.asyncio
async def test_detect_location_requires_unambiguous_favorite(monkeypatch):
    entries = [{'address': {'location': [69.2, 41.3], 'flat': 'private'}}]
    async def addresses(http):
        return None, entries
    monkeypatch.setattr(lavka_order_mcp, 'addresses', addresses)
    monkeypatch.setattr(lavka_uz, 'create_http', lambda: httpx.AsyncClient())
    result = await lavka_uz.detect_delivery_location('UZ')
    assert result['source'] == 'single_saved_address'
    assert result['longitude'] == 69.2 and result['address_selected'] is False
    assert 'private' not in str(result)
    entries.append({'address': {'location': [69.2, 41.3]}})
    result = await lavka_uz.detect_delivery_location('UZ')
    assert result['source'] == 'ambiguous' and 'longitude' not in result
    selected = await lavka_uz.detect_delivery_location('UZ', address_index=1)
    assert selected['source'] == 'saved_address_index'


@pytest.mark.asyncio
async def test_country_selection_fails_closed_without_network(monkeypatch):
    monkeypatch.setattr(lavka_uz, 'create_http', lambda: pytest.fail('network not expected'))
    for country in ('UZ', 'RU', 'KZ'):
        result = await lavka_uz.select_region(country)
        assert result['country'] == country and result['persistent'] is False
        assert result['read_only_tools'] == ['service_status', 'search_products']
        assert result['uz_account_and_checkout_tools_available'] is (country == 'UZ')
    with pytest.raises(ValueError, match='Unsupported'):
        await lavka_uz.select_region('US')
    await lavka_uz.select_region('UZ')
    for country in ('RU', 'KZ'):
        with pytest.raises(ValueError, match='UZ-only'):
            await lavka_uz.detect_delivery_location(country)


@pytest.mark.asyncio
async def test_explicit_location_is_stateless_and_not_coverage():
    result = await lavka_uz.delivery_location('UZ', longitude=69.2, latitude=41.3)
    assert result['longitude'] == 69.2 and result['latitude'] == 41.3
    assert result['coverage_verified'] is False and result['address_selected'] is False
    assert result['source'] == 'coordinates'
    assert 'cart' in result['note'].lower()


@pytest.mark.asyncio
async def test_location_bounds_and_invalid_values_fail_closed():
    for lon, lat in [(54, 41), (69, 47), (float('nan'), 41), (True, 41)]:
        with pytest.raises(ValueError):
            await lavka_uz.delivery_location('UZ', lon, lat)
    with pytest.raises(ValueError, match='Unsupported'):
        await lavka_uz.delivery_location('RU', 69, 41)


@pytest.mark.asyncio
async def test_detection_uses_authenticated_read_only_endpoint(monkeypatch):
    calls = []
    def handle(request):
        calls.append((request.method, request.url.path))
        if request.url.host == 'yandex.uz':
            return httpx.Response(200, headers={'set-cookie': 'yandexuid=123; Domain=.yandex.uz; Path=/'})
        if request.method == 'GET':
            props = {'pageData': {'passportInfo': {'status': 'VALID'}}}
            return httpx.Response(200, text='<script id="__page_props__-data">' + json.dumps(props) + '</script>')
        assert request.url.path.endswith('get-favorite-addresses')
        return httpx.Response(200, json=[{'address': {'location': [69.2, 41.3], 'flat': 'secret'}}])
    monkeypatch.setattr(lavka_uz, 'create_http', lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    result = await lavka_uz.detect_delivery_location('UZ')
    assert result['source'] == 'single_saved_address' and 'secret' not in str(result)
    assert calls == [('GET', '/favicon.ico'), ('GET', '/'), ('POST', '/api/v1/providers/address/v1/get-favorite-addresses')]
    names = {tool.name for tool in await lavka_uz.mcp.list_tools()}
    assert {'select_region', 'delivery_location', 'detect_delivery_location'} <= names
