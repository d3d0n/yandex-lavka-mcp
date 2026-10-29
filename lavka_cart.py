"""Experimental Uzbekistan cart access, without an order-submission endpoint."""
import uuid
from decimal import Decimal, InvalidOperation

from lavka_uz import BASE, UpstreamError


class CartClient:
    def __init__(self, http, props, location, currency_sign):
        if props.get('pageData', {}).get('passportInfo', {}).get('status') != 'VALID':
            raise UpstreamError('An authenticated Uzbekistan session is required')
        if not isinstance(location, (list, tuple)) or len(location) != 2 or not (55 <= location[0] <= 74 and 37 <= location[1] <= 46):
            raise ValueError('A valid Uzbekistan location is required')
        if not currency_sign or currency_sign in ('₽', 'руб'):
            raise ValueError('Uzbekistan currency sign is required')
        self.http, self.props, self.location, self.currency_sign = http, props, list(location), currency_sign

    async def _post(self, path, body):
        if path not in ('/api/v1/providers/cart/v1/retrieve', '/api/v1/providers/cart/v1/update'):
            raise ValueError('Endpoint is not allowlisted')
        p = self.props
        headers = {'Origin': BASE, 'Referer': BASE + '/', 'X-Requested-With': 'XMLHttpRequest',
                   'X-Csrf-Token': p.get('authProxyCsrfToken') or '', 'X-Csrf-Token-Bff': p.get('csrfToken') or ''}
        try:
            r = await self.http.post(BASE + path, headers=headers, json=body)
        except Exception:
            raise UpstreamError('Cart request failed; update outcome may be unknown') from None
        if r.status_code != 200:
            raise UpstreamError(f'Cart endpoint HTTP {r.status_code}')
        try:
            result = r.json()
        except ValueError:
            raise UpstreamError('Cart endpoint returned non-JSON') from None
        if not isinstance(result, dict) or result.get('type') == 'captcha':
            raise UpstreamError('Cart endpoint returned CAPTCHA or unexpected data')
        return result

    async def retrieve(self):
        raw = await self._post('/api/v1/providers/cart/v1/retrieve', {'depotType': 'regular', 'currencySign': self.currency_sign, 'position': {'location': self.location}})
        cart = raw.get('cart', raw)
        if not isinstance(cart, dict) or not isinstance(cart.get('items'), list) or not cart.get('cartId') or cart.get('cartVersion') is None:
            raise UpstreamError('Unexpected cart response')
        return cart

    async def set_item(self, product_id, quantity, price):
        if not isinstance(product_id, str) or not product_id or isinstance(quantity, bool) or not isinstance(quantity, int) or not 0 <= quantity <= 50:
            raise ValueError('A product id and a quantity between 0 and 50 are required')
        try:
            amount = Decimal(str(price))
            if not amount.is_finite() or amount < 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            raise ValueError('A nonnegative price is required') from None
        def quantities(items):
            result = {}
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'] or item['id'] in result:
                    raise UpstreamError('Cart items cannot be safely verified')
                try:
                    count = Decimal(str(item.get('quantity')))
                    if not count.is_finite() or count < 0:
                        raise ValueError
                except (InvalidOperation, ValueError):
                    raise UpstreamError('Cart item quantity cannot be safely verified') from None
                result[item['id']] = count
            return result

        cart = await self.retrieve()
        before = quantities(cart['items'])
        body = {'items': [{'id': product_id, 'quantity': str(quantity), 'pricePerCount': '1', 'quantityType': 'unit', 'price': str(amount), 'title': '', 'currency': 'UZS'}],
                'deliveryTimeInfo': cart.get('deliveryTimeInfo'), 'deliveryType': cart.get('deliveryType'),
                'position': {'location': self.location}, 'additionalData': {}, 'cartId': cart['cartId'],
                'cartVersion': cart['cartVersion'], 'idempotencyToken': uuid.uuid4().hex,
                'isUserOrderEdit': False, 'depotType': 'regular'}
        await self._post('/api/v1/providers/cart/v1/update', body)
        fresh = await self.retrieve()
        if fresh['cartId'] != cart['cartId']:
            raise UpstreamError('Cart identity changed during update; outcome is uncertain')
        after = quantities(fresh['items'])
        if after.get(product_id, 0) != quantity:
            raise UpstreamError('Cart readback did not verify requested item quantity')
        before.pop(product_id, None)
        after.pop(product_id, None)
        if before != after:
            raise UpstreamError('Unrelated cart items changed during update; outcome is uncertain')
        return fresh
