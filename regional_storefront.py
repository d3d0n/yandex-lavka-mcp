"""Anonymous, isolated read-only clients for verified regional storefronts.

Do not pass authenticated or shared cookie jars: this client is intentionally
separate from the Uzbekistan account and order clients.
"""
import html
import json
import math
import re
import time

from lavka_errors import UpstreamError

REGIONS = {
    'RU': ('ru', 'RUB'),
    'KZ': ('kz', 'KZT'),
    'UZ': ('uz', 'UZS'),
}


class RegionalStorefront:
    def __init__(self, country, http):
        if country not in REGIONS:
            raise ValueError('Supported countries: RU, KZ, UZ')
        self.country = country
        self.domain, self.currency = REGIONS[country]
        self.base = f'https://lavka.yandex.{self.domain}'
        self.http = http
        self.props = None

    async def bootstrap(self):
        identity = await self.http.get(f'https://yandex.{self.domain}/favicon.ico', follow_redirects=True)
        if identity.status_code != 200 or not any(c.name == 'yandexuid' and c.domain in (f'.yandex.{self.domain}', f'yandex.{self.domain}') for c in self.http.cookies.jar):
            raise UpstreamError('Regional identity bootstrap failed')
        response = await self.http.get(self.base + '/', params={'_lavka_mcp': str(time.time_ns())})
        if response.status_code != 200:
            raise UpstreamError(f'Regional homepage HTTP {response.status_code}')
        match = re.search(r'<script id="__page_props__-data"[^>]*>(.*?)</script>', response.text, re.S)
        if not match:
            raise UpstreamError('Regional homepage bootstrap data missing')
        try:
            props = json.loads(match.group(1))
            info = props['pageData']['serviceInfo']
            if info['currency'] != self.currency or not info['currencySign']:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise UpstreamError('Regional currency not confirmed by upstream') from None
        self.props = props
        return props

    async def status(self):
        p = self.props or await self.bootstrap()
        info = p['pageData']['serviceInfo']
        return {'country': self.country, 'currency': self.currency, 'currency_sign': info['currencySign'], 'is_open': info.get('isOpen'), 'is_disabled': info.get('isDisabled'), 'advertised_delivery_time': info.get('deliveryTimeText'), 'address_coverage_verified': False, 'note': 'Anonymous homepage default; not a quote for an address.'}

    async def search(self, query, limit, longitude, latitude):
        if not isinstance(query, str) or not query.strip() or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('Query required; limit must be 1–50')
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (longitude, latitude)) or not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError('Valid longitude and latitude required')
        p = self.props or await self.bootstrap()
        info = p['pageData']['serviceInfo']
        locale = p.get('pageEnv', {}).get('locale', 'ru-RU')
        if isinstance(locale, dict):
            locale = f"{locale.get('lang', 'ru')}-{locale.get('region', 'RU')}"
        headers = {'Origin': self.base, 'Referer': self.base + '/', 'X-Requested-With': 'XMLHttpRequest', 'X-Csrf-Token': p.get('authProxyCsrfToken') or '', 'X-Csrf-Token-Bff': p.get('csrfToken') or '', 'X-Lavka-Web-Locale': locale, 'X-Lavka-Web-City': str(p.get('pageEnv', {}).get('cityId', ''))}
        body = {'depotType':'regular', 'currencySign':info['currencySign'], 'text':query, 'productsLimit':limit, 'subcategoriesLimit':0, 'useRetail':True, 'source':'manual_input', 'position':{'location':[longitude, latitude]}}
        r = await self.http.post(self.base + '/api/v1/providers/search/v3/lavka', headers=headers, json=body)
        if r.status_code != 200:
            raise UpstreamError(f'Regional search HTTP {r.status_code}; coverage not established')
        try:
            raw = r.json()
            entries = raw['cacheProducts']
            if not isinstance(entries, list):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise UpstreamError('Unexpected regional search response') from None
        products = [{'id': i.get('id'), 'title': html.unescape(re.sub(r'</?notr>', '', str(i.get('title') or ''))), 'price': i.get('currentPrice'), 'currency': self.currency, 'quantity': i.get('amount'), 'available': i.get('available')} for i in entries[:limit] if isinstance(i, dict)]
        return {'country': self.country, 'products': products, 'currency_source': 'anonymous_regional_homepage', 'note': 'Availability and price depend on coordinates; delivery coverage is not established.'}
