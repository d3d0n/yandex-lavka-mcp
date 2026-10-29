import httpx
import pytest
from lavka_uz import Lavka

@pytest.mark.asyncio
async def test_history_uses_authenticated_identity_and_returns_only_safe_fields():
    seen = []
    async def handler(request):
        import json
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'orders': [{'orderId':'order-1', 'shortOrderId':'1', 'createdAt':'2026-01-01T00:00:00Z', 'status':'canceled', 'statusText':'Canceled', 'contact':{'phone':'secret'}, 'yandexUid':'123'}], 'tabs':{'deliveryOrders':['order-1']}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        http.cookies.set('yandexuid', '123', domain='.yandex.uz', path='/')
        client = Lavka(http)
        client.props = {'pageData': {'passportInfo': {'status': 'VALID'}}}
        result = await client.order_history(count=21, older_than='2026-02-01T00:00:00Z')
    assert seen == [{'range': {'count':21, 'olderThan':'2026-02-01T00:00:00Z'}, 'userIdentity':{'yandexUid':'123','boundYandexUids':[]}, 'includeServiceMetadata':False}]
    assert result['orders'] == [{'order_id':'order-1', 'short_order_id':'1', 'created_at':'2026-01-01T00:00:00Z', 'status':'canceled', 'status_text':'Canceled', 'closed_at':None}]
    assert 'secret' not in str(result) and '123' not in str(result)

@pytest.mark.asyncio
async def test_mcp_history_tool_delegates_to_authenticated_client(monkeypatch):
    import lavka_uz
    async def fake_history(self, count, older_than):
        return {"orders": [], "count": count, "cursor": older_than}
    monkeypatch.setattr(lavka_uz.Lavka, "order_history", fake_history)
    result = await lavka_uz.order_history(5, None)
    assert result == {"orders": [], "count": 5, "cursor": None}

@pytest.mark.asyncio
async def test_history_rejects_ambiguous_uid_without_request():
    from lavka_uz import UpstreamError
    async def handler(request):
        pytest.fail("unexpected network request")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        http.cookies.set("yandexuid", "123", domain=".yandex.uz", path="/")
        http.cookies.set("yandexuid", "456", domain="yandex.uz", path="/")
        client = Lavka(http)
        client.props = {"pageData": {"passportInfo": {"status": "VALID"}}}
        with pytest.raises(UpstreamError, match="identity"):
            await client.order_history()

@pytest.mark.asyncio
async def test_cancel_route_is_not_allowlisted_even_with_mock_transport():
    async def handler(request):
        pytest.fail("cancel request must not be sent")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ValueError, match="allowlisted"):
            await Lavka(http).call("/api/v1/providers/orders/v1/cancel", {"orderId": "test"})
