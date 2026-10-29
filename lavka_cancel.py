"""Single-attempt cancellation transport; never retries an ambiguous write."""
import hashlib
import os
import re
import sqlite3
import stat

from lavka_uz import BASE


class CancellationBlocked(RuntimeError):
    pass


async def _canceled_in_history(history, order_id):
    try:
        data = await history()
        orders = data['orders']
        if not isinstance(orders, list) or any(not isinstance(o, dict) for o in orders):
            return False
        matches = [o for o in orders if o.get('order_id') == order_id]
        return len(matches) == 1 and matches[0].get('status') == 'canceled'
    except Exception:
        return False


async def cancel_order(*, http, props, order_id, confirmed, state_path, history):
    if confirmed is not True or not isinstance(order_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', order_id):
        raise ValueError('Explicit confirmation and an exact order identifier are required')
    if props.get('pageData', {}).get('passportInfo', {}).get('status') != 'VALID':
        raise ValueError('Authenticated Uzbekistan session required')
    fd = os.open(state_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise CancellationBlocked('Cancellation state must be private and owner-only')
    finally:
        os.close(fd)
    with sqlite3.connect(state_path, timeout=30) as db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS cancellation_attempts (order_hash TEXT PRIMARY KEY)')
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute('INSERT INTO cancellation_attempts VALUES (?)', (hashlib.sha256(order_id.encode()).hexdigest(),))
            reserved = True
        except sqlite3.IntegrityError:
            reserved = False
    if not reserved:
        if await _canceled_in_history(history, order_id):
            return {'cancellation_verified': True, 'history_match': True, 'outcome': 'canceled', 'refund_status': 'unknown'}
        raise CancellationBlocked('Cancellation already attempted; inspect official history, do not retry')
    headers = {'Origin': BASE, 'Referer': BASE + '/', 'X-Requested-With': 'XMLHttpRequest',
               'X-Csrf-Token': props.get('authProxyCsrfToken') or '', 'X-Csrf-Token-Bff': props.get('csrfToken') or ''}
    try:
        response = await http.post(BASE + '/api/v1/providers/orders/v1/cancel', headers=headers, json={'orderId': order_id})
    except Exception:
        return {'cancellation_verified': False, 'outcome': 'unknown', 'refund_status': 'unknown'}
    verified = await _canceled_in_history(history, order_id)
    result = {'cancellation_verified': verified, 'history_match': verified, 'outcome': 'canceled' if verified else 'unknown', 'refund_status': 'unknown', 'http_status': response.status_code}
    if 400 <= response.status_code <= 599:
        from lavka_rejection_capture import sanitize_upstream_error
        try:
            data = response.json()
        except ValueError:
            data = None
        result['upstream_error'] = sanitize_upstream_error(response.status_code, data)
        result['diagnostic_note'] = 'Sanitized error details may be incomplete; this response alone does not establish cancellation outcome.'
    return result
