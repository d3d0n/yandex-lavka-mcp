"""Unofficial, read-only Yandex Lavka Uzbekistan MCP server."""
import html
import json
import logging
import os
import re
from http.cookiejar import Cookie
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP
from lavka_errors import UpstreamError

BASE = "https://lavka.yandex.uz"
STATE = os.path.expanduser(os.environ.get("YANDEX_SESSION_FILE", "~/.local/share/yandex-lavka-mcp/session.json"))
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

class Lavka:
    def __init__(self, http, region_http=None):
        self.http = http
        self.region_http = region_http
        self.props = None

    async def bootstrap(self):
        # The frontend receives a .yandex.uz identity cookie before API calls.
        # Without it the homepage's BFF CSRF token fails validation.
        if not any(c.name == "yandexuid" and c.domain in (".yandex.uz", "yandex.uz") for c in self.http.cookies.jar):
            identity = await self.http.get("https://yandex.uz/favicon.ico", follow_redirects=True)
            if identity.status_code != 200 or not any(c.name == "yandexuid" and c.domain in (".yandex.uz", "yandex.uz") for c in self.http.cookies.jar):
                raise UpstreamError("Uzbekistan identity bootstrap failed")
        r = await self.http.get(BASE + "/", params={"_lavka_mcp": str(__import__('time').time_ns())})
        if r.status_code != 200:
            raise UpstreamError(f"Homepage HTTP {r.status_code}")
        m = re.search(r'<script id="__page_props__-data"[^>]*>(.*?)</script>', r.text, re.S)
        if not m:
            raise UpstreamError("Homepage bootstrap data missing")
        self.props = json.loads(m.group(1))
        return self.props

    async def call(self, path, body):
        if path not in ("/api/v1/providers/search/v3/lavka", "/api/v1/providers/geo/v1/suggest", "/api/v1/providers/address/v1/get-favorite-addresses", "/api/v1/providers/order-log/v1/retrieve"):
            raise ValueError("Endpoint is not allowlisted")
        p = self.props or await self.bootstrap()
        locale = p.get("pageEnv", {}).get("locale", "ru-RU")
        if isinstance(locale, dict):
            locale = f"{locale.get('lang', 'ru')}-{locale.get('region', 'RU')}"
        headers = {"Origin": BASE, "Referer": BASE + "/", "X-Requested-With": "XMLHttpRequest", "X-Csrf-Token": p.get("authProxyCsrfToken") or "", "X-Csrf-Token-Bff": p.get("csrfToken") or "", "X-Lavka-Web-Locale": locale, "X-Lavka-Web-City": str(p.get("pageEnv", {}).get("cityId", ""))}
        r = await self.http.post(BASE + path, headers=headers, json=body)
        if r.status_code in (401, 403):
            raise UpstreamError(f"Upstream HTTP {r.status_code}: authorization or CSRF rejected; session/API bootstrap is not verified")
        if r.status_code != 200:
            raise UpstreamError(f"Upstream HTTP {r.status_code}")
        try:
            data = r.json()
        except ValueError:
            raise UpstreamError("Upstream returned non-JSON") from None
        if isinstance(data, dict) and data.get("type") == "captcha":
            raise UpstreamError("Upstream requires CAPTCHA")
        return data

    async def search(self, query, limit, location):
        if not query.strip() or not 1 <= limit <= 50:
            raise ValueError("Query required; limit must be 1–50")
        if location is None:
            raise ValueError("Both longitude and latitude are required for search")
        p = self.props or await self.bootstrap()
        info = p.get("pageData", {}).get("serviceInfo", {})
        region_source = "session_homepage"
        if not info:
            if self.region_http is not None:
                anon = await Lavka(self.region_http).bootstrap()
            else:
                async with httpx.AsyncClient(timeout=25, follow_redirects=False, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}) as anonymous_http:
                    anon = await Lavka(anonymous_http).bootstrap()
            info = anon.get("pageData", {}).get("serviceInfo", {})
            region_source = "independent_anonymous_uz_homepage"
        if info.get("currency") != "UZS":
            raise UpstreamError("Uzbekistan currency not confirmed by upstream")
        body = {"depotType": "regular", "currencySign": info.get("currencySign"), "text": query, "productsLimit": limit, "subcategoriesLimit": 0, "useRetail": True, "source": "manual_input"}
        if location is not None:
            lon, lat = location
            if not (55 <= lon <= 74 and 37 <= lat <= 46):
                raise ValueError("Coordinates must be within Uzbekistan bounding box")
            body["position"] = {"location": [lon, lat]}
        raw = await self.call("/api/v1/providers/search/v3/lavka", body)
        if not isinstance(raw, dict) or not isinstance(raw.get("cacheProducts"), list):
            raise UpstreamError("Unexpected search response; results unavailable")
        products = []
        for item in raw["cacheProducts"][:limit]:
            if isinstance(item, dict):
                products.append({"id": item.get("id"), "title": html.unescape(re.sub(r"</?notr>", "", str(item.get("title") or ""))), "price": item.get("currentPrice"), "currency": "UZS", "quantity": item.get("amount"), "available": item.get("available")})
        return {"products": products, "location_supplied": location is not None, "currency_source": region_source, "note": "Availability and price are location dependent; no delivery coverage is implied."}

    async def suggest(self, query):
        if not query.strip():
            raise ValueError("Address query required")
        return await self.call("/api/v1/providers/geo/v1/suggest", {"query": query, "action": "user_input", "lang": "ru"})

    async def saved_address_count(self):
        p = self.props or await self.bootstrap()
        if p.get("pageData", {}).get("passportInfo", {}).get("status") != "VALID":
            raise UpstreamError("An authenticated Uzbekistan session is required")
        result = await self.call("/api/v1/providers/address/v1/get-favorite-addresses", {})
        if not isinstance(result, list):
            raise UpstreamError("Unexpected saved addresses response")
        return {"count": len(result)}

    async def order_history(self, count=21, older_than=None):
        from datetime import datetime
        if type(count) is not int or not 1 <= count <= 21:
            raise ValueError('count must be between 1 and 21')
        if older_than is not None:
            try:
                if not isinstance(older_than, str) or len(older_than) > 64:
                    raise ValueError()
                dt = datetime.fromisoformat(older_than.replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise ValueError('older_than must be a timezone-aware ISO timestamp') from None
        p = self.props or await self.bootstrap()
        if p.get('pageData', {}).get('passportInfo', {}).get('status') != 'VALID':
            raise UpstreamError('An authenticated Uzbekistan session is required')
        uids = [c.value for c in self.http.cookies.jar if c.name == 'yandexuid' and c.domain in ('.yandex.uz', 'yandex.uz') and c.path == '/' and not c.is_expired()]
        if len(uids) != 1 or not re.fullmatch(r'[0-9]{1,64}', uids[0]):
            raise UpstreamError('Uzbekistan identity cookie missing or ambiguous')
        range_ = {'count': count}
        if older_than is not None:
            range_['olderThan'] = older_than
        data = await self.call('/api/v1/providers/order-log/v1/retrieve', {'range': range_, 'userIdentity': {'yandexUid': uids[0], 'boundYandexUids': []}, 'includeServiceMetadata': False})
        if not isinstance(data, dict) or not isinstance(data.get('orders'), list) or not isinstance(data.get('tabs'), dict) or len(data['orders']) > count:
            raise UpstreamError('Unexpected order history response')
        orders = []
        fields = {'order_id':'orderId', 'short_order_id':'shortOrderId', 'created_at':'createdAt', 'status':'status', 'status_text':'statusText', 'closed_at':'closedAt'}
        for item in data['orders']:
            if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k] for k in ('orderId', 'createdAt', 'status')):
                raise UpstreamError('Unexpected order history entry')
            view = {k: item.get(v) for k, v in fields.items()}
            if any(v is not None and (not isinstance(v, str) or len(v) > 256 or any(ord(c) < 32 for c in v)) for v in view.values()):
                raise UpstreamError('Unexpected order history field')
            orders.append(view)
        return {'orders': orders, 'next_older_than': orders[-1]['created_at'] if len(orders) == count else None, 'note': 'Point-in-time history; pagination uses the last creation timestamp and may not capture tied timestamps.'}


def create_http():
    client = httpx.AsyncClient(timeout=25, follow_redirects=False, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    # Preserve original domain scope; never copy .yandex.ru credentials to .uz.
    if Path(STATE).is_file():
        data = json.loads(Path(STATE).read_text())
        for item in data.get("cookies", []):
            try:
                params = dict(item)
                params["rest"] = params.pop("_rest", {})
                client.cookies.jar.set_cookie(Cookie(**params))
            except (TypeError, KeyError, ValueError):
                raise UpstreamError("Invalid saved cookie jar") from None
    return client

mcp = FastMCP("Yandex Lavka Uzbekistan")

@mcp.tool()
async def service_status() -> dict:
    """Get homepage storefront status. Does not confirm a specific address."""
    async with create_http() as http:
        p = await Lavka(http).bootstrap()
        data = p.get("pageData", {})
        service = data.get("serviceInfo", {})
        return {"currency": service.get("currency"), "currency_sign": service.get("currencySign"), "advertised_delivery_time": service.get("deliveryTimeText"), "is_open": service.get("isOpen"), "is_disabled": service.get("isDisabled"), "passport_status": data.get("passportInfo", {}).get("status"), "address_coverage_verified": False, "note": "Homepage default storefront only; not a quote for your address."}

@mcp.tool()
async def search_products(query: str, limit: int = 20, longitude: float | None = None, latitude: float | None = None) -> dict:
    """Search products at supplied coordinates, if upstream API accepts bootstrap."""
    if (longitude is None) != (latitude is None):
        raise ValueError("Both longitude and latitude are required")
    async with create_http() as http:
        return await Lavka(http).search(query, limit, None if longitude is None else (longitude, latitude))

@mcp.tool()
async def suggest_address(query: str) -> dict:
    """Suggest addresses; never changes the account's delivery address."""
    async with create_http() as http:
        result = await Lavka(http).suggest(query)
        if not isinstance(result, (dict, list)):
            raise UpstreamError("Unexpected address response")
        return {"suggestions": result, "coverage_verified": False}

@mcp.tool()
async def saved_address_count() -> dict:
    """Count saved favorite addresses without exposing their details."""
    async with create_http() as http:
        return await Lavka(http).saved_address_count()

async def _cart_client(http, longitude, latitude):
    from lavka_cart import CartClient
    client = Lavka(http)
    props = await client.bootstrap()
    if props.get('pageData', {}).get('passportInfo', {}).get('status') != 'VALID':
        raise UpstreamError('An authenticated Uzbekistan session is required')
    info = props.get('pageData', {}).get('serviceInfo', {})
    if not info:
        async with httpx.AsyncClient(timeout=25, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}) as anonymous:
            info = (await Lavka(anonymous).bootstrap()).get('pageData', {}).get('serviceInfo', {})
    if info.get('currency') != 'UZS' or not info.get('currencySign'):
        raise UpstreamError('Uzbekistan currency and sign not confirmed by upstream')
    return CartClient(http, props, [longitude, latitude], info['currencySign'])


def _cart_view(cart):
    items = []
    for item in cart['items']:
        if not isinstance(item, dict):
            raise UpstreamError('Unexpected cart item')
        items.append({k: item.get(k) for k in ('id', 'title', 'quantity', 'price')})
    return {'items': items, 'currency': 'UZS',
            'total_uzs': cart.get('totalPriceValue'),
            'available_for_checkout': cart.get('availableForCheckout'),
            'checkout_unavailable_reason': cart.get('checkoutUnavailableReason'),
            'note': 'Point-in-time cart at supplied coordinates; address and payment selection are not established.'}


@mcp.tool()
async def get_cart(longitude: float, latitude: float) -> dict:
    """Read the cart for these coordinates; does not select an address."""
    async with create_http() as http:
        client = await _cart_client(http, longitude, latitude)
        return _cart_view(await client.retrieve())


@mcp.tool()
async def set_cart_item(longitude: float, latitude: float, product_id: str, quantity: int, price: str) -> dict:
    """Change cart item to an absolute quantity (0 removes). Explicit cart write; price must be from current search. Never retries ambiguous writes."""
    async with create_http() as http:
        client = await _cart_client(http, longitude, latitude)
        return _cart_view(await client.set_item(product_id, quantity, price))


@mcp.tool()
async def saved_cards(longitude: float, latitude: float) -> dict:
    """List available saved cards by masked suffix only; this does not select one."""
    from lavka_payment import PaymentClient
    async with create_http() as http:
        props = await Lavka(http).bootstrap()
        cards = await PaymentClient(http, props, [longitude, latitude]).lookup()
        return {'cards': cards.masked_cards, 'payment_selected': False}


@mcp.tool()
async def order_history(count: int = 21, older_than: str | None = None) -> dict:
    """Read authenticated order history; older_than is a timezone-aware ISO timestamp."""
    async with create_http() as http:
        return await Lavka(http).order_history(count, older_than)


@mcp.tool()
async def active_orders() -> dict:
    """Read the active tracking feed; an empty feed is not order history or reconciliation."""
    async with create_http() as http:
        props = await Lavka(http).bootstrap()
        if props.get('pageData', {}).get('passportInfo', {}).get('status') != 'VALID':
            raise UpstreamError('An authenticated Uzbekistan session is required')
        headers = {'Origin': BASE, 'Referer': BASE + '/', 'X-Requested-With': 'XMLHttpRequest',
                   'X-Csrf-Token': props.get('authProxyCsrfToken') or '',
                   'X-Csrf-Token-Bff': props.get('csrfToken') or ''}
        try:
            response = await http.get(BASE + '/api/v1/providers/orders-tracking/v1/tracked-orders', headers=headers)
            if response.status_code != 200:
                raise UpstreamError(f'Active-order endpoint HTTP {response.status_code}')
            data = response.json()
        except UpstreamError:
            raise
        except Exception:
            raise UpstreamError('Active-order read failed or was not JSON') from None
        from lavka_tracking_projection import project_tracking_response, TrackingShapeError
        try:
            return project_tracking_response(data)
        except TrackingShapeError:
            raise UpstreamError('Unverified active-order response; no conclusion possible') from None


@mcp.tool()
async def checkout_preview(longitude: float, latitude: float) -> dict:
    """Read a cart quote only; no address/card selection, confirmation, order or payment."""
    cart = await get_cart(longitude, latitude)
    return {'cart': cart, 'address_selected': False, 'payment_selected': False,
            'order_submission_enabled': False,
            'limitation': 'This quote is not an order or a confirmation token. Use order_preview for a bound address/card checkout preview; server-side price enforcement is unknown.'}


@mcp.tool()
async def saved_addresses() -> dict:
    """List saved addresses with selection indexes; includes private address details."""
    from lavka_order_mcp import addresses
    async with create_http() as http:
        _, entries = await addresses(http)
        return {'addresses': [{'index': i, 'address': entry['address']} for i, entry in enumerate(entries)]}


@mcp.tool()
async def order_preview(address_index: int, card_suffix: str) -> dict:
    """Stage an exact checkout preview for a saved-address index and four-digit card suffix. Not an order."""
    from lavka_order_mcp import preview
    async with create_http() as http:
        return await preview(http, address_index, card_suffix)


@mcp.tool()
async def submit_order(preview_token: str, confirmed_total_uzs: str, explicit_confirmation: bool) -> dict:
    """Place one paid order only after explicit user confirmation of the exact preview; never retries. Outcomes may be uncertain."""
    from lavka_order_mcp import submit
    async with create_http() as http:
        return await submit(http, preview_token, confirmed_total_uzs, explicit_confirmation)


@mcp.tool()
async def reconcile_checkout(history_checked: bool, payment_checked: bool, acknowledge_uncertainty: bool, no_request_in_progress: bool, explicit_confirmation: bool) -> dict:
    """Acknowledge an uncertain checkout after checking official history and payment. This cannot rule out delayed processing or duplicates; never retries or places an order."""
    from lavka_order_mcp import reconcile_checkout as reconcile
    return reconcile(history_checked=history_checked, payment_checked=payment_checked,
                     acknowledge_uncertainty=acknowledge_uncertainty,
                     no_request_in_progress=no_request_in_progress, explicit_confirmation=explicit_confirmation)


@mcp.tool()
async def cancel_order(order_id: str, explicit_confirmation: bool) -> dict:
    """Cancel the exact order once only after explicit user confirmation. Refund status is unknown."""
    from lavka_order_mcp import cancel
    async with create_http() as http:
        async def history():
            return await Lavka(http).order_history()
        return await cancel(http, order_id, explicit_confirmation, history)


from qr_mcp import register_qr_tools
register_qr_tools(mcp, STATE)

if __name__ == "__main__":
    mcp.run(transport="stdio")
