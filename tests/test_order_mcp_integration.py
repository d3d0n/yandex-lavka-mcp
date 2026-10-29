import json
import httpx
import pytest
import lavka_uz
import lavka_order_mcp as orders

@pytest.mark.asyncio
async def test_order_tools_are_exposed():
    names = {tool.name for tool in await lavka_uz.mcp.list_tools()}
    assert {'order_preview', 'submit_order', 'cancel_order', 'saved_addresses'} <= names

@pytest.mark.asyncio
async def test_mock_checkout_single_submit_and_cancel(tmp_path, monkeypatch):
    calls = []
    props = {'pageData': {'passportInfo': {'status': 'VALID'}}}
    address = {'location':[69.2,41.3], 'placeId':'p', 'country':'Uzbekistan', 'city':'Tashkent', 'street':'Test', 'house':'1', 'flat':'5', 'floor':'2', 'entrance':'1', 'doorcode':'42'}
    cart = {'cartId':'cart', 'cartVersion':1, 'orderFlowVersion':'v', 'items':[{'id':'item', 'title':'Item', 'quantity':'1', 'price':'100'}], 'availableForCheckout':True, 'totalPriceValue':'100', 'statuses':{'isRover':False}}
    def handle(request):
        path = request.url.path
        calls.append(path)
        if path.endswith('get-favorite-addresses'): return httpx.Response(200,json=[{'address':address}])
        if path.endswith('service-info'): return httpx.Response(200,json={'currency':'UZS','currencySign':'sum','depotId':'depot'})
        if path.endswith('retrieve'): return httpx.Response(200,json=cart)
        if path.endswith('methods'): return httpx.Response(200,json={'methods':[{'type':'card','id':'private','number':'**** 1234','availability':{'available':True}}]})
        if path.endswith('submit'):
            body=json.loads(request.content); assert body['position']['flat']=='5'; assert body['useRover'] is False; assert body['paymentMethodId']=='private'
            return httpx.Response(200,json={'orderId':'o1','newbie':False,'trackPayment':{'modalPlace':'none'}})
        if path.endswith('cancel'): return httpx.Response(200,json={})
        raise AssertionError(path)
    async def boot(self): self.props=props; return props
    monkeypatch.setattr(lavka_uz.Lavka,'bootstrap',boot)
    monkeypatch.setattr(orders,'GUARD',tmp_path/'guard')
    monkeypatch.setattr(orders,'STATE',tmp_path/'previews')
    monkeypatch.setattr(orders,'CANCEL_STATE',tmp_path/'cancel')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        http.cookies.set('Session_id','test',domain='.yandex.uz',path='/')
        preview=await orders.preview(http,0,'1234')
        assert preview['address']['flat']=='5' and preview['total_uzs']=='100'
        result=await orders.submit(http,preview['preview_token'],'100',True)
        assert result['order_id']=='o1'
        with pytest.raises(Exception): await orders.submit(http,preview['preview_token'],'100',True)
        async def history(): return {'orders':[{'order_id':'o1','status':'cancelled'}]}
        result=await orders.cancel(http,'o1',True,history)
        assert result['refund_status']=='unknown'
    assert calls.count('/api/v1/providers/orders/v2/submit')==1
    assert calls.count('/api/v1/providers/orders/v1/cancel')==1

@pytest.mark.asyncio
async def test_checkout_timeout_blocks_new_preview_across_instances(tmp_path, monkeypatch):
    monkeypatch.setattr(orders, 'GUARD', tmp_path/'guard')
    monkeypatch.setattr(orders, 'STATE', tmp_path/'previews')
    cart = {'cartId':'c','cartVersion':1,'orderFlowVersion':'v','totalPriceValue':'10','items':[{'id':'x'}]}
    binding={'cart':cart, 'position':{'location':[69.2,41.3]}, 'card':{'type':'card','id':'id'}, 'index':0,'suffix':'1234'}
    async def snap(*args): return binding, {'pageData':{'passportInfo':{'status':'VALID'}}}
    monkeypatch.setattr(orders, 'snapshot', snap)
    writes=[]
    def handle(request):
        writes.append(request.url.path)
        raise httpx.ReadTimeout('secret-token and private address')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        http.cookies.set('Session_id','test',domain='.yandex.uz',path='/')
        p=await orders.preview(http,0,'1234')
        result = await orders.submit(http,p['preview_token'],'10',True)
        assert result['outcome'] == 'unknown'
        assert result['transport_error'] == 'ReadTimeout'
        assert 'secret-token' not in str(result) and 'private address' not in str(result)
        with pytest.raises(ValueError,match='quarantined'): await orders.preview(http,0,'1234')
    assert writes==['/api/v1/providers/orders/v2/submit']

@pytest.mark.asyncio
async def test_expiry_during_fresh_preflight_prevents_write(tmp_path, monkeypatch):
    monkeypatch.setattr(orders, 'GUARD', tmp_path/'guard')
    monkeypatch.setattr(orders, 'STATE', tmp_path/'previews')
    now=[1000.0]
    monkeypatch.setattr(orders.time,'time',lambda: now[0])
    binding={'cart':{'cartId':'c','cartVersion':1,'orderFlowVersion':'v','totalPriceValue':'10','items':[{'id':'x'}]},'position':{'location':[69.2,41.3]},'card':{'type':'card','id':'id'},'index':0,'suffix':'1234'}
    async def snap(*args):
        now[0]+=200
        return binding, {'pageData':{'passportInfo':{'status':'VALID'}}}
    monkeypatch.setattr(orders,'snapshot',snap)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: pytest.fail('expired preview wrote'))) as http:
        http.cookies.set('Session_id','test',domain='.yandex.uz',path='/')
        p=await orders.preview(http,0,'1234')
        now[0]+=150
        with pytest.raises(ValueError,match='expired'): await orders.submit(http,p['preview_token'],'10',True)

@pytest.mark.asyncio
async def test_cancel_timeout_never_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(orders, 'CANCEL_STATE', tmp_path/'cancel')
    async def boot(self):
        self.props={'pageData':{'passportInfo':{'status':'VALID'}}}; return self.props
    monkeypatch.setattr(lavka_uz.Lavka,'bootstrap',boot)
    calls=[]
    def handle(request):
        calls.append(request.url.path)
        raise httpx.ReadTimeout('ambiguous')
    async def history(): raise RuntimeError('history unavailable')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        assert (await orders.cancel(http,'o1',True,history))['outcome']=='unknown'
        with pytest.raises(Exception): await orders.cancel(http,'o1',True,history)
    assert calls==['/api/v1/providers/orders/v1/cancel']

@pytest.mark.asyncio
async def test_preview_bound_to_unchanged_authenticated_session(tmp_path, monkeypatch):
    monkeypatch.setattr(orders, 'GUARD', tmp_path/'guard')
    monkeypatch.setattr(orders, 'STATE', tmp_path/'previews')
    binding={'cart':{'cartId':'c','cartVersion':1,'orderFlowVersion':'v','totalPriceValue':'10','items':[{'id':'x'}]},'position':{'location':[69.2,41.3]},'card':{'type':'card','id':'id'},'index':0,'suffix':'1234'}
    async def snap(*args): return binding, {'pageData':{'passportInfo':{'status':'VALID'}}}
    monkeypatch.setattr(orders,'snapshot',snap)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: pytest.fail('write attempted'))) as http:
        http.cookies.set('Session_id','first',domain='.yandex.uz',path='/')
        p=await orders.preview(http,0,'1234')
        http.cookies.set('Session_id','different',domain='.yandex.uz',path='/')
        with pytest.raises(ValueError,match='session'): await orders.submit(http,p['preview_token'],'10',True)


@pytest.mark.asyncio
async def test_success_allows_fresh_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(orders, "GUARD", tmp_path / "guard")
    monkeypatch.setattr(orders, "STATE", tmp_path / "previews")
    binding = {"cart":{"cartId":"c","cartVersion":1,"orderFlowVersion":"v","totalPriceValue":"10","items":[{"id":"x"}]},"position":{"location":[69.2,41.3]},"card":{"type":"card","id":"id"},"index":0,"suffix":"1234"}
    async def snap(*args): return binding, {}
    monkeypatch.setattr(orders, "snapshot", snap)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200,json={"orderId":"one"}))) as http:
        http.cookies.set("Session_id","test",domain=".yandex.uz",path="/")
        p = await orders.preview(http, 0, "1234")
        assert (await orders.submit(http,p["preview_token"],"10",True))["outcome"] == "submitted"
        assert (await orders.preview(http, 0, "1234"))["preview_token"]


@pytest.mark.asyncio
async def test_rejection_exposes_safe_codes_and_releases(tmp_path, monkeypatch):
    monkeypatch.setattr(orders, "GUARD", tmp_path / "guard")
    monkeypatch.setattr(orders, "STATE", tmp_path / "previews")
    binding = {"cart":{"cartId":"c","cartVersion":1,"orderFlowVersion":"v","totalPriceValue":"10","items":[{"id":"x"}]},"position":{"location":[69.2,41.3]},"card":{"type":"card","id":"id"},"index":0,"suffix":"1234"}
    async def snap(*args): return binding, {}
    monkeypatch.setattr(orders, "snapshot", snap)
    body = {"code":"grocery_unavailable_for_checkout", "detail":"bad_service_fee_v2", "secret":"private"}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(400,json=body))) as http:
        http.cookies.set("Session_id","test",domain=".yandex.uz",path="/")
        p = await orders.preview(http,0,"1234")
        result = await orders.submit(http,p["preview_token"],"10",True)
        assert result["outcome"] == "rejected"
        assert set(result["codes"]) == {"grocery_unavailable_for_checkout", "bad_service_fee_v2"}
        assert "private" not in str(result)
        assert (await orders.preview(http,0,"1234"))["preview_token"]

def test_unknown_reconciliation_requires_acknowledgement_and_audit(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setattr(orders, "GUARD", tmp_path / "guard")
    old = orders._reserve()
    args = dict(history_checked=True, payment_checked=True, acknowledge_uncertainty=True, no_request_in_progress=True, explicit_confirmation=True)
    with pytest.raises(ValueError): orders.reconcile_checkout(**(args | {"payment_checked":False}))
    assert orders.reconcile_checkout(**args)["released"]
    new = orders._reserve()
    orders._finish(old, "submitted", "late response")
    with pytest.raises(ValueError, match="quarantined"): orders._check_guard()
    with sqlite3.connect(orders.GUARD) as db:
        assert db.execute("select count(*) from mcp_attempt_audit where event='user_reconciled'").fetchone()[0] == 1
    orders._finish(new, "submitted", "test")

@pytest.mark.asyncio
async def test_reconciliation_tool_exposed():
    assert "reconcile_checkout" in {tool.name for tool in await lavka_uz.mcp.list_tools()}


def test_prior_known_rejection_released_without_bank_claim(tmp_path, monkeypatch):
    import sqlite3
    from lavka_live_transport import AttemptGuard
    monkeypatch.setattr(orders, "GUARD", tmp_path / "guard")
    guard = AttemptGuard(orders.GUARD)
    guard.reserve()
    guard.record_rejection()
    orders._check_guard()
    with sqlite3.connect(orders.GUARD) as db:
        assert db.execute("select count(*) from attempts").fetchone()[0] == 0
        assert db.execute("select detail from mcp_attempt_audit where event='rejected_release'").fetchone()[0] == "Previously recorded upstream rejection"

@pytest.mark.asyncio
async def test_unclassified_http_failure_stays_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(orders, "GUARD", tmp_path / "guard")
    monkeypatch.setattr(orders, "STATE", tmp_path / "previews")
    binding = {"cart":{"cartId":"c","cartVersion":1,"orderFlowVersion":"v","totalPriceValue":"10","items":[{"id":"x"}]},"position":{"location":[69.2,41.3]},"card":{"type":"card","id":"id"},"index":0,"suffix":"1234"}
    async def snap(*args): return binding, {}
    monkeypatch.setattr(orders, "snapshot", snap)
    calls=[]
    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(500, text="private error")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        http.cookies.set("Session_id","test",domain=".yandex.uz",path="/")
        p=await orders.preview(http,0,"1234")
        result=await orders.submit(http,p["preview_token"],"10",True)
        assert result["outcome"] == "unknown" and "cannot be determined" in result["note"]
        assert "private error" not in str(result)
        with pytest.raises(ValueError, match="quarantined"): await orders.preview(http,0,"1234")
    assert len(calls) == 1
