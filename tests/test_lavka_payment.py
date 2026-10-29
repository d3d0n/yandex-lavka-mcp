import json
import httpx
import pytest
from lavka_uz import UpstreamError
from lavka_payment import PaymentClient

PROPS = {'pageData': {'passportInfo': {'status': 'VALID'}}}
LOCATION = [69.2, 41.3]

@pytest.mark.asyncio
async def test_lookup_uses_location_and_returns_masked_available_cards():
    def handler(request):
        assert request.url.path == '/api/v1/providers/payments/v1/methods'
        assert json.loads(request.content) == {'location': LOCATION, 'countryIso3': 'UZB'}
        return httpx.Response(200, json={'methods': [
            {'type': 'card', 'id': 'secret-id', 'number': '**** 1234', 'availability': {'available': True}},
            {'type': 'card', 'id': 'disabled', 'number': '**** 9999', 'availability': {'available': False}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await PaymentClient(http, PROPS, LOCATION).lookup()
    assert result.masked_cards == ['**** 1234']
    assert 'secret-id' not in repr(result)
    assert result.select(0) == {'type': 'card', 'id': 'secret-id'}
    with pytest.raises(ValueError): result.select(-1)
    with pytest.raises(ValueError): result.select(True)

def test_rejects_invalid_auth_and_location():
    with pytest.raises(UpstreamError): PaymentClient(None, {}, LOCATION)
    for loc in ([float('nan'), 41], [True, 41], [69], [1, 2]):
        with pytest.raises(ValueError): PaymentClient(None, PROPS, loc)

@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(400), httpx.Response(200, text='bad'), httpx.Response(200, json={}), httpx.Response(200, json={'methods':[{'type':'card','id':'secret','number':'invalid','availability':{'available':True}}]})])
async def test_fail_closed_on_invalid_upstream(response):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as http:
        with pytest.raises(UpstreamError): await PaymentClient(http, PROPS, LOCATION).lookup()
