import pytest
import lavka_uz


@pytest.mark.asyncio
async def test_search_routes_requested_country_to_isolated_regional_client(monkeypatch):
    seen = []
    class Regional:
        def __init__(self, country, http):
            seen.append((country, len(list(http.cookies.jar))))
        async def search(self, query, limit, longitude, latitude):
            return {'country': seen[-1][0], 'products': []}
    monkeypatch.setattr('regional_storefront.RegionalStorefront', Regional)
    result = await lavka_uz.search_products('milk', 5, 76.945, 43.2389, country='KZ')
    assert result['country'] == 'KZ'
    assert seen == [('KZ', 0)]


@pytest.mark.asyncio
async def test_status_routes_country_to_anonymous_client(monkeypatch):
    class Regional:
        def __init__(self, country, http):
            assert country == 'RU'
            assert not list(http.cookies.jar)
        async def status(self):
            return {'country': 'RU', 'currency': 'RUB'}
    monkeypatch.setattr('regional_storefront.RegionalStorefront', Regional)
    assert (await lavka_uz.service_status(country='RU'))['currency'] == 'RUB'
