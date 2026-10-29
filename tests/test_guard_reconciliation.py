import asyncio
import concurrent.futures
import sqlite3
import time

import httpx
import pytest
from lavka_live_transport import AttemptGuard, AttemptBlocked, submit_once


def evidence():
    return dict(http_status=400, rejection_code='grocery_unavailable_for_checkout',
                detail_code='bad_service_fee_v2', rejection_ref='private-response-1',
                rejected_at=100, history_source='official-history', history_count=0,
                history_observed_at=101, history_ref='private-history-1',
                bank_no_debit=True, bank_observed_at=102, bank_ref='user-confirmation-1')


def test_legacy_slot_explicit_reconciliation_preserves_audit(tmp_path):
    path = tmp_path / 'guard'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE attempts (slot INTEGER PRIMARY KEY CHECK (slot = 1))')
        db.execute('INSERT INTO attempts VALUES (1)')
    guard = AttemptGuard(path)
    with pytest.raises(AttemptBlocked):
        guard.reserve()
    guard.reconcile(**evidence())
    guard.reserve()
    with pytest.raises(AttemptBlocked):
        guard.reserve()
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM reconciliation_audit').fetchone()[0] == 1
        assert db.execute('SELECT rejection_ref, history_ref, bank_ref FROM reconciliation_audit').fetchone() == ('private-response-1', 'private-history-1', 'user-confirmation-1')


def test_concurrent_reservation_after_reconciliation(tmp_path):
    path = tmp_path / 'guard'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE attempts (slot INTEGER PRIMARY KEY CHECK (slot = 1))')
        db.execute('INSERT INTO attempts VALUES (1)')
    AttemptGuard(path).reconcile(**evidence())
    def reserve(_):
        try:
            AttemptGuard(path).reserve()
            return True
        except AttemptBlocked:
            return False
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(8))) == 1


@pytest.mark.parametrize('changes', [
    {'http_status': 500}, {'rejection_code': 'other'}, {'detail_code': 'other'},
    {'history_count': 1}, {'history_count': False}, {'history_source': 'active-orders'},
    {'history_observed_at': 99}, {'bank_no_debit': False}, {'bank_observed_at': 99},
    {'history_ref': ''}, {'rejection_ref': ''}, {'bank_ref': ''},
])
def test_invalid_evidence_never_clears_guard(tmp_path, changes):
    guard = AttemptGuard(tmp_path / 'guard')
    guard.reserve()
    data = evidence() | changes
    with pytest.raises(ValueError):
        guard.reconcile(**data)
    with pytest.raises(AttemptBlocked):
        guard.reserve()


def test_exact_rejection_and_concurrent_reconciliation(tmp_path):
    guard = AttemptGuard(tmp_path / 'guard')
    async def run():
        body = {'message': 'grocery_unavailable_for_checkout', 'details': {'error': {'code': 'bad_service_fee_v2'}}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(400, json=body))) as client:
            return await submit_once(client, {'pageData': {'passportInfo': {'status': 'VALID'}}}, {'x': 1}, guard=guard)
    assert asyncio.run(run())['outcome'] == 'rejected'
    observed = time.time()
    data = evidence() | {'rejected_at': observed - 1, 'history_observed_at': observed, 'bank_observed_at': observed}
    def reconcile(_):
        try:
            AttemptGuard(guard.path).reconcile(**data)
            return True
        except AttemptBlocked:
            return False
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reconcile, range(8))) == 1
    guard.reserve()
    with sqlite3.connect(guard.path) as db:
        assert db.execute('SELECT legacy FROM reconciliation_audit').fetchone() == (0,)


def test_unknown_transport_cannot_be_reconciled_by_claiming_rejection(tmp_path):
    guard = AttemptGuard(tmp_path / 'guard')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500))) as client:
            await submit_once(client, {'pageData': {'passportInfo': {'status': 'VALID'}}}, {'x': 1}, guard=guard)
    asyncio.run(run())
    with pytest.raises(AttemptBlocked):
        guard.reconcile(**evidence())
    with pytest.raises(AttemptBlocked):
        guard.reserve()
