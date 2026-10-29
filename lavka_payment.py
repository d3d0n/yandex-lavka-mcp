"""Read-only Uzbekistan saved-card lookup. Never sends an order or payment."""
import math
import re
from dataclasses import dataclass, field
from lavka_uz import BASE, UpstreamError

@dataclass
class PaymentResults:
    masked_cards: list[str]
    _ids: list[str] = field(repr=False)

    def select(self, index):
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(self._ids):
            raise ValueError('Invalid card selection')
        return {'type': 'card', 'id': self._ids[index]}

class PaymentClient:
    def __init__(self, http, props, location):
        if props.get('pageData', {}).get('passportInfo', {}).get('status') != 'VALID':
            raise UpstreamError('An authenticated Uzbekistan session is required')
        if (not isinstance(location, (list, tuple)) or len(location) != 2 or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in location) or
            not (55 <= location[0] <= 74 and 37 <= location[1] <= 46)):
            raise ValueError('A valid Uzbekistan location is required')
        self.http, self.props, self.location = http, props, list(location)

    async def lookup(self):
        p = self.props
        headers = {'Origin': BASE, 'Referer': BASE + '/', 'X-Requested-With': 'XMLHttpRequest',
                   'X-Csrf-Token': p.get('authProxyCsrfToken') or '', 'X-Csrf-Token-Bff': p.get('csrfToken') or ''}
        try:
            r = await self.http.post(BASE + '/api/v1/providers/payments/v1/methods', headers=headers,
                                     json={'location': self.location, 'countryIso3': 'UZB'})
        except Exception:
            raise UpstreamError('Payment lookup request failed') from None
        if r.status_code != 200:
            raise UpstreamError(f'Payment lookup HTTP {r.status_code}')
        try:
            data = r.json()
        except ValueError:
            raise UpstreamError('Payment lookup returned non-JSON') from None
        if not isinstance(data, dict) or not isinstance(data.get('methods'), list):
            raise UpstreamError('Unexpected payment lookup response')
        masked, ids = [], []
        for method in data['methods']:
            if not isinstance(method, dict):
                raise UpstreamError('Unexpected payment method')
            if method.get('type') != 'card' or not isinstance(method.get('availability'), dict) or method['availability'].get('available') is not True:
                continue
            number, card_id = method.get('number'), method.get('id')
            if not isinstance(number, str) or not isinstance(card_id, str) or not card_id:
                raise UpstreamError('Available card is missing required details')
            match = re.search(r'([0-9]{4})\s*$', number)
            if not match:
                raise UpstreamError('Available card number cannot be safely masked')
            masked.append('**** ' + match.group(1))
            ids.append(card_id)
        return PaymentResults(masked, ids)
