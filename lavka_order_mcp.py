"""Confirmed, single-attempt Lavka checkout; no automatic write retries."""
import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
import time
from pathlib import Path

from lavka_live_transport import GUARD
from lavka_uz import BASE, Lavka, UpstreamError
from lavka_cart import CartClient
from lavka_payment import PaymentClient
from lavka_submit_payload import build_provider_payload
from lavka_live_transport import AttemptGuard, AttemptBlocked
from lavka_rejection_capture import sanitize_rejection, sanitize_upstream_error
from lavka_cancel import cancel_order as cancel_once

STATE = Path.home() / '.local/share/yandex-lavka-mcp/order-previews.sqlite'
CANCEL_STATE = Path.home() / '.local/share/yandex-lavka-mcp/cancellation.sqlite'
POSITION_FIELDS = ('location','placeId','country','city','street','house','depotId','floor','flat','comment','entrance','doorcode','buildingName','doorbellName','leftAtDoor','meetOutside','noDoorCall')
WARNING = ('Client-side preflight only: server-side total enforcement and idempotency are not established. '
           'Prices may change after preflight. No automatic retry; inspect official order history and bank on uncertainty. '
           'Other clients do not share this guard. Refund status after cancellation is unknown.')


def _ensure_default_state_dir(path):
    directory = Path.home() / '.local/share/yandex-lavka-mcp'
    if Path(path).parent != directory:
        return
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('State directory must be a private owner-only directory')


def _db():
    path = Path(STATE)
    _ensure_default_state_dir(path)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Preview state must be private and owner-only')
    finally:
        os.close(fd)
    db = sqlite3.connect(path, timeout=30)
    db.execute('PRAGMA synchronous=FULL')
    db.execute('CREATE TABLE IF NOT EXISTS order_previews (token TEXT PRIMARY KEY, snapshot TEXT NOT NULL, created REAL NOT NULL, used INTEGER NOT NULL)')
    return db


def _session(http):
    values = [c.value for c in http.cookies.jar if c.name == 'Session_id' and c.domain in ('.yandex.uz', 'yandex.uz') and c.path == '/' and not c.is_expired()]
    if len(values) != 1 or not values[0]:
        raise ValueError('An unambiguous Uzbekistan authenticated session is required')
    return hashlib.sha256(values[0].encode()).hexdigest()


def _token(token):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{40,80}', token):
        raise ValueError('Invalid preview token')
    return hashlib.sha256(token.encode()).hexdigest()


async def addresses(http):
    client = Lavka(http)
    props = await client.bootstrap()
    if props.get('pageData', {}).get('passportInfo', {}).get('status') != 'VALID':
        raise UpstreamError('Authenticated Uzbekistan session required')
    data = await client.call('/api/v1/providers/address/v1/get-favorite-addresses', {})
    if not isinstance(data, list) or any(not isinstance(x, dict) or not isinstance(x.get('address'), dict) for x in data):
        raise UpstreamError('Unexpected favorite addresses')
    return client, data


async def snapshot(http, address_index, suffix):
    client, entries = await addresses(http)
    if type(address_index) is not int or not 0 <= address_index < len(entries) or not isinstance(suffix, str) or not re.fullmatch(r'[0-9]{4}', suffix):
        raise ValueError('Select an exact saved address index and four-digit card suffix')
    entry = entries[address_index]
    address = entry['address']
    loc = address.get('location')
    if not isinstance(loc, list) or len(loc) != 2:
        raise ValueError('Saved address has no usable location')
    props = client.props
    headers = {'Origin': BASE, 'Referer': BASE + '/', 'X-Requested-With': 'XMLHttpRequest',
               'X-Csrf-Token': props.get('authProxyCsrfToken') or '', 'X-Csrf-Token-Bff': props.get('csrfToken') or ''}
    response = await http.get(BASE + '/api/v1/providers/v2/service-info', headers=headers,
        params={'position[location][0]':loc[0], 'position[location][1]':loc[1], 'fallbackCurrencySign':'сум', 'depotType':'regular'})
    if response.status_code != 200:
        raise UpstreamError('Service-info lookup failed')
    info = response.json()
    if not isinstance(info, dict) or info.get('currency') != 'UZS' or not info.get('currencySign') or not info.get('depotId'):
        raise UpstreamError('Service-info location/currency is unverified')
    cart = await CartClient(http, props, loc, info['currencySign']).retrieve()
    cards = await PaymentClient(http, props, loc).lookup()
    indexes = [i for i, mask in enumerate(cards.masked_cards) if mask == '**** ' + suffix]
    if len(indexes) != 1:
        raise ValueError('Card suffix is missing or ambiguous')
    card = cards.select(indexes[0])
    if cart.get('availableForCheckout') is not True or not cart.get('items') or not isinstance(cart.get('totalPriceValue'), str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?', cart['totalPriceValue']):
        raise ValueError('Nonempty available cart and exact total required')
    if cart.get('statuses', {}).get('isRover') is not False:
        raise ValueError('Non-rover delivery is not confirmed')
    if cart.get('timeslot') is not None:
        raise ValueError('Scheduled delivery is not supported')
    position = {k: address[k] for k in POSITION_FIELDS if k in address and address[k] is not None}
    position['depotId'] = info['depotId']
    if not all(position.get(k) for k in ('placeId','country','city','street','house')):
        raise ValueError('Saved address is incomplete')
    # Bind all raw item fields, fees and delivery metadata, not only displayed fields.
    binding = {'entry': entry, 'position':position, 'info':info, 'cart':cart, 'card':card,
               'index':address_index, 'suffix':suffix}
    try:
        return json.loads(json.dumps(binding, sort_keys=True, allow_nan=False)), props
    except (TypeError, ValueError):
        raise UpstreamError('Non-JSON checkout data') from None


def _guard_db():
    _ensure_default_state_dir(GUARD)
    db = AttemptGuard(GUARD)._connect()
    db.execute("CREATE TABLE IF NOT EXISTS mcp_attempt (slot INTEGER PRIMARY KEY, nonce TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS mcp_attempt_audit (id INTEGER PRIMARY KEY, recorded_at REAL NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL)")
    db.commit()
    return db


def _release_known_rejection(db):
    state = db.execute("SELECT state FROM attempt_state WHERE slot=1").fetchone()
    if state == ('rejected',):
        db.execute("INSERT INTO mcp_attempt_audit (recorded_at,event,detail) VALUES (?,?,?)", (time.time(), 'rejected_release', 'Previously recorded upstream rejection'))
        db.execute("DELETE FROM mcp_attempt WHERE slot=1")
        db.execute("DELETE FROM attempt_state WHERE slot=1")
        db.execute("DELETE FROM attempts WHERE slot=1")


def _check_guard():
    with _guard_db() as db:
        db.execute('BEGIN IMMEDIATE')
        _release_known_rejection(db)
        if db.execute('SELECT 1 FROM attempts WHERE slot=1').fetchone():
            raise ValueError('Previous checkout outcome is quarantined and unknown; server reason cannot be known. Check official order history and payment, then explicitly reconcile; delayed processing remains possible.')


def _reserve():
    nonce = secrets.token_hex(32)
    with _guard_db() as db:
        db.execute('BEGIN IMMEDIATE')
        _release_known_rejection(db)
        if db.execute('SELECT 1 FROM attempts WHERE slot=1').fetchone():
            raise AttemptBlocked('Previous checkout outcome is quarantined and unknown; reconcile before another attempt')
        db.execute('INSERT INTO attempts VALUES (1)')
        db.execute("INSERT INTO attempt_state VALUES (1, 'unknown', NULL)")
        db.execute('INSERT INTO mcp_attempt VALUES (1, ?)', (nonce,))
        db.execute('INSERT INTO mcp_attempt_audit (recorded_at,event,detail) VALUES (?,?,?)', (time.time(), 'reserved', 'Outcome unknown until response classified'))
    return nonce


def _finish(nonce, outcome, detail):
    with _guard_db() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT nonce FROM mcp_attempt WHERE slot=1').fetchone() != (nonce,):
            return
        db.execute('INSERT INTO mcp_attempt_audit (recorded_at,event,detail) VALUES (?,?,?)', (time.time(), outcome, detail))
        if outcome in ('submitted', 'rejected'):
            db.execute('DELETE FROM mcp_attempt WHERE slot=1')
            db.execute('DELETE FROM attempt_state WHERE slot=1')
            db.execute('DELETE FROM attempts WHERE slot=1')


def reconcile_checkout(*, history_checked, payment_checked, acknowledge_uncertainty, no_request_in_progress, explicit_confirmation):
    """Record user attestation, not verified evidence, and release an unknown slot."""
    if any(x is not True for x in (history_checked, payment_checked, acknowledge_uncertainty, no_request_in_progress, explicit_confirmation)):
        raise ValueError('Explicitly confirm history and payment checked, no request in progress, and acknowledge delayed processing and duplicate-order risk')
    with _guard_db() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM attempts WHERE slot=1').fetchone():
            raise ValueError('No checkout attempt to reconcile')
        db.execute('INSERT INTO mcp_attempt_audit (recorded_at,event,detail) VALUES (?,?,?)', (time.time(), 'user_reconciled', 'User attests history and payment checked, no request in progress, and accepts delayed processing and duplicate risk; not independently verified'))
        db.execute('DELETE FROM mcp_attempt WHERE slot=1')
        db.execute('DELETE FROM attempt_state WHERE slot=1')
        db.execute('DELETE FROM attempts WHERE slot=1')
    return {'released': True, 'warning': 'User attestation is not proof; delayed processing and duplicate orders remain possible. Obtain a fresh preview and explicit confirmation.'}


async def preview(http, address_index, card_suffix):
    binding, _ = await snapshot(http, address_index, card_suffix)
    _check_guard()
    binding = {'data': binding, 'session': _session(http)}
    token = secrets.token_urlsafe(32)
    with _db() as db:
        db.execute('INSERT INTO order_previews VALUES (?, ?, ?, 0)', (_token(token), json.dumps(binding, sort_keys=True, ensure_ascii=False), time.time()))
    binding = binding['data']
    cart = binding['cart']
    return {'preview_token':token, 'expires_in_seconds':300, 'address':binding['position'],
            'items':cart['items'], 'total_uzs':cart['totalPriceValue'], 'currency':'UZS',
            'card':'**** '+card_suffix, 'delivery':'non-rover', 'warning':WARNING}


async def submit(http, token, confirmed_total_uzs, explicit_confirmation):
    if explicit_confirmation is not True or not isinstance(confirmed_total_uzs, str):
        raise ValueError('Explicit confirmation and exact total string required')
    digest = _token(token)
    with _db() as db:
        row = db.execute('SELECT snapshot, created, used FROM order_previews WHERE token=?', (digest,)).fetchone()
    if not row or row[2] or not 0 <= time.time()-row[1] < 300:
        raise ValueError('Preview expired, consumed, or unknown')
    stored = json.loads(row[0])
    if stored['session'] != _session(http):
        raise ValueError('Authenticated session changed; obtain a new preview')
    old = stored['data']
    if confirmed_total_uzs != old['cart']['totalPriceValue']:
        raise ValueError('Confirmed total differs from preview')
    fresh, props = await snapshot(http, old['index'], old['suffix'])
    if not 0 <= time.time()-row[1] < 300:
        raise ValueError('Preview expired during preflight')
    if stored['session'] != _session(http):
        raise ValueError('Authenticated session changed during preflight')
    if fresh != old:
        raise ValueError('Checkout data changed; obtain and confirm a new preview')
    cart, pos, card = fresh['cart'], fresh['position'], fresh['card']
    payload = build_provider_payload(cart_id=cart['cartId'], cart_version=cart['cartVersion'], flow_version=cart['orderFlowVersion'], position=pos, depot_type='regular', payment_type=card['type'], payment_id=card['id'], options={'useRover':False})
    # Consume first, then commit the existing account-wide quarantine before I/O.
    with _db() as db:
        db.execute('BEGIN IMMEDIATE')
        cur = db.execute('UPDATE order_previews SET used=1 WHERE token=? AND used=0', (digest,))
        if cur.rowcount != 1:
            raise ValueError('Preview already consumed')
    nonce = _reserve()
    headers = {'Origin':BASE, 'Referer':BASE+'/', 'X-Requested-With':'XMLHttpRequest',
               'X-Csrf-Token':props.get('authProxyCsrfToken') or '', 'X-Csrf-Token-Bff':props.get('csrfToken') or ''}
    try:
        response = await http.post(BASE+'/api/v1/providers/orders/v2/submit', headers=headers, json=payload)
    except Exception as exc:
        _finish(nonce, 'unknown', 'Transport failure; server reason unavailable')
        return {'outcome':'unknown', 'transport_error': type(exc).__name__, 'warning':WARNING + ' No server response was received; reconcile before a fresh attempt.'}
    try:
        data = response.json()
    except ValueError:
        data = None
    result = {'outcome':'unknown', 'http_status':response.status_code, 'warning':WARNING}
    if response.status_code == 200 and isinstance(data, dict) and isinstance(data.get('orderId'), str) and data['orderId']:
        _finish(nonce, 'submitted', 'Order ID returned; payment unverified')
        result.update(outcome='submitted', order_id=data['orderId'], payment_status='unverified', note='Order ID returned; independently check order status and payment.')
    elif 400 <= response.status_code <= 599:
        projection = sanitize_rejection(response.status_code, data)
        result.update(projection)
        result['upstream_error'] = sanitize_upstream_error(response.status_code, data)
        if response.status_code == 400 and 'grocery_unavailable_for_checkout' in projection['codes']:
            _finish(nonce, 'rejected', json.dumps(projection, sort_keys=True))
            result['outcome'] = 'rejected'
            if {'bad_service_fee', 'bad_service_fee_v2'} & set(projection['codes']):
                result['recovery'] = {
                    'kind': 'checkout_price_or_fee_changed',
                    'old_total_uzs': old['cart']['totalPriceValue'],
                    'automatic_retry': False,
                    'fresh_preview_required': True,
                    'explicit_confirmation_required': True,
                    'instructions': [
                        'Yandex rejected checkout with a fee validation error; its storefront displays a generic price-changed alert. The cause and any product price change are not established.',
                        'Obtain a fresh cart and order_preview for the same address and card; do not reuse the consumed preview.',
                        'Compare and inform the user of old and new totals and item, fee, delivery, and availability changes; do not invent unavailable details.',
                        'Respect the user’s price budget and constraints; if the new total exceeds them, do not submit unless the user explicitly changes the budget.',
                        'Ask for explicit confirmation of the new preview and total before a new submit; never submit automatically.',
                    ],
                }
        else:
            _finish(nonce, 'unknown', 'Unclassified upstream response')
            result['note'] = 'Order outcome cannot be determined from this response; reconcile before a fresh attempt.'
    else:
        _finish(nonce, 'unknown', 'Unclassified upstream response')
        result['note'] = 'Server reason and order outcome cannot be determined; reconcile before a fresh attempt.'
    return result


async def cancel(http, order_id, explicit_confirmation, history):
    client = Lavka(http)
    props = await client.bootstrap()
    _ensure_default_state_dir(CANCEL_STATE)
    result = await cancel_once(http=http, props=props, order_id=order_id, confirmed=explicit_confirmation, state_path=CANCEL_STATE, history=history)
    result['warning'] = WARNING
    return result
