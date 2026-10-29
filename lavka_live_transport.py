"""Low-level checkout transport with a durable single-attempt quarantine.

The caller must independently verify checkout, use one private durable guard
for every submission, and reconcile independently. Other clients or guard files
are not protected. A response is not proof of order or payment state.
"""
import os
import sqlite3
import time
from pathlib import Path

from lavka_uz import BASE
from lavka_rejection_capture import sanitize_rejection

# Preserve the existing shared quarantine; never silently switch guard databases.
GUARD = Path.home() / '.local/share/yandex-lavka-mcp/fee-experiment-20261029.sqlite'


class AttemptBlocked(RuntimeError):
    pass


class AttemptGuard:
    """One durable account-wide slot; reconciliation is explicit, never automatic.

    Evidence is operator-attested, not independently fetched or authenticated here.
    History is point-in-time and cannot rule out delayed processing. Other DBs or
    checkout channels bypass this guard. Preserve this database and its audit trail.
    """
    def __init__(self, path):
        self.path = Path(path)

    def _connect(self):
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(fd)
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS attempts (slot INTEGER PRIMARY KEY CHECK (slot = 1))')
        db.execute('CREATE TABLE IF NOT EXISTS attempt_state (slot INTEGER PRIMARY KEY CHECK (slot = 1), state TEXT NOT NULL, rejected_at REAL)')
        db.execute('''CREATE TABLE IF NOT EXISTS reconciliation_audit (
            id INTEGER PRIMARY KEY, reconciled_at REAL NOT NULL, legacy INTEGER NOT NULL,
            http_status INTEGER NOT NULL, rejection_code TEXT NOT NULL, detail_code TEXT NOT NULL,
            rejection_ref TEXT NOT NULL UNIQUE, rejected_at REAL NOT NULL,
            history_source TEXT NOT NULL, history_count INTEGER NOT NULL,
            history_observed_at REAL NOT NULL, history_ref TEXT NOT NULL UNIQUE,
            bank_no_debit INTEGER NOT NULL, bank_observed_at REAL NOT NULL, bank_ref TEXT NOT NULL UNIQUE)''')
        db.commit()
        return db

    def reserve(self):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                db.execute('INSERT INTO attempts VALUES (1)')
            except sqlite3.IntegrityError:
                raise AttemptBlocked('Previous attempt quarantined; no retry permitted') from None
            db.execute("INSERT INTO attempt_state VALUES (1, 'unknown', NULL)")

    def record_rejection(self):
        # Called only after parsing the exact known rejection from this response.
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE attempt_state SET state='rejected', rejected_at=? WHERE slot=1 AND state='unknown'", (time.time(),))

    def reconcile_operator(self, *, approved, http_status, note):
        """Release a legacy slot on explicit operator attestation; preserve the audit."""
        if approved is not True or http_status != 400 or not isinstance(note, str) or len(note.strip()) < 20:
            raise ValueError('Explicit approval, HTTP 400 and an evidence note are required')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM attempts WHERE slot=1').fetchone():
                raise AttemptBlocked('No quarantined attempt')
            if db.execute('SELECT 1 FROM attempt_state WHERE slot=1').fetchone():
                raise AttemptBlocked('Only the prior legacy slot may be reconciled this way')
            db.execute('CREATE TABLE IF NOT EXISTS operator_reconciliation_audit (id INTEGER PRIMARY KEY, reconciled_at REAL NOT NULL, http_status INTEGER NOT NULL, note TEXT NOT NULL)')
            db.execute('INSERT INTO operator_reconciliation_audit (reconciled_at,http_status,note) VALUES (?,?,?)', (time.time(), http_status, note.strip()))
            db.execute('DELETE FROM attempts WHERE slot=1')

    def reconcile(self, *, http_status, rejection_code, detail_code, rejection_ref,
                  rejected_at, history_source, history_count, history_observed_at,
                  history_ref, bank_no_debit, bank_observed_at, bank_ref):
        """Explicit attestation for the exact rejection; never reconciles unknowns.

        Legacy slots have no machine outcome, so require independent external
        evidence for the historical rejection. Times are Unix seconds. References
        identify private evidence without copying sensitive data into this DB.
        """
        refs = (rejection_ref, history_ref, bank_ref)
        times = (rejected_at, history_observed_at, bank_observed_at)
        if (type(http_status) is not int or http_status != 400 or
            rejection_code != 'grocery_unavailable_for_checkout' or detail_code != 'bad_service_fee_v2' or
            history_source != 'official-history' or type(history_count) is not int or history_count != 0 or
            bank_no_debit is not True or any(not isinstance(x, str) or not x.strip() for x in refs) or
            len(set(refs)) != 3 or any(type(x) not in (int, float) or not 0 < x < float('inf') for x in times) or
            history_observed_at <= rejected_at or bank_observed_at <= rejected_at):
            raise ValueError('Insufficient independent reconciliation evidence')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM attempts WHERE slot=1').fetchone():
                raise AttemptBlocked('No quarantined attempt')
            state = db.execute('SELECT state, rejected_at FROM attempt_state WHERE slot=1').fetchone()
            if state is not None and (state[0] != 'rejected' or history_observed_at <= state[1] or bank_observed_at <= state[1]):
                raise AttemptBlocked('Unknown or insufficiently observed attempt remains quarantined')
            try:
                db.execute('INSERT INTO reconciliation_audit (reconciled_at, legacy, http_status, rejection_code, detail_code, rejection_ref, rejected_at, history_source, history_count, history_observed_at, history_ref, bank_no_debit, bank_observed_at, bank_ref) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (time.time(), int(state is None), http_status, rejection_code, detail_code, rejection_ref, rejected_at, history_source, history_count, history_observed_at, history_ref, 1, bank_observed_at, bank_ref))
            except sqlite3.IntegrityError:
                raise AttemptBlocked('Evidence already used') from None
            db.execute('DELETE FROM attempt_state WHERE slot=1')
            db.execute('DELETE FROM attempts WHERE slot=1')


async def submit_once(http, props, payload, *, guard, response_path=None):
    if props.get('pageData', {}).get('passportInfo', {}).get('status') != 'VALID':
        raise ValueError('Authenticated Uzbekistan session required')
    if not isinstance(payload, dict) or not payload:
        raise ValueError('Checkout payload required')
    if not isinstance(guard, AttemptGuard):
        raise ValueError('A durable attempt guard is required')
    # Open before reservation and transmission; never overwrite an earlier capture.
    fd = None
    if response_path is not None:
        fd = os.open(response_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        guard.reserve()  # Commit before even attempting the network write.
        headers = {'Origin': BASE, 'Referer': BASE + '/', 'X-Requested-With': 'XMLHttpRequest',
                   'X-Csrf-Token': props.get('authProxyCsrfToken') or '',
                   'X-Csrf-Token-Bff': props.get('csrfToken') or ''}
        try:
            response = await http.post(BASE + '/api/v1/providers/orders/v2/submit', headers=headers, json=payload)
        except Exception:
            return {'outcome': 'unknown'}
        if fd is not None:
            try:
                with os.fdopen(fd, 'wb') as output:
                    fd = None
                    output.write(response.content)
                    output.flush()
                    os.fsync(output.fileno())
            except OSError:
                return {'outcome': 'unknown', 'http_status': response.status_code, 'capture_failed': True}
    finally:
        if fd is not None:
            os.close(fd)
    status = response.status_code
    if 400 <= status <= 599:
        try:
            body = response.json()
        except ValueError:
            body = None
        result = sanitize_rejection(status, body)
        # This known code describes a rejection; all other errors remain uncertain.
        result['outcome'] = 'rejected' if status == 400 and 'grocery_unavailable_for_checkout' in result['codes'] else 'unknown'
        if status == 400 and {'grocery_unavailable_for_checkout', 'bad_service_fee_v2'} <= set(result['codes']):
            guard.record_rejection()
        return result
    return {'outcome': 'unknown', 'http_status': status}
