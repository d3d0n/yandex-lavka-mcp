"""Offline checkout safety prototype. This module cannot place orders.

Snapshots are an internal contract, NOT a verified Lavka Uzbekistan API schema.
Do not expose this as an ordering capability or use it as a live submit gate.
"""
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import stat
import time


class CheckoutError(Exception):
    """Invalid, stale, changed, or already consumed checkout preview."""


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _amount(value):
    # String decimals only: reject floats, exponents, signs and special values.
    return isinstance(value, str) and bool(re.fullmatch(r"(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,2})?", value))


def _validated(snapshot):
    if not isinstance(snapshot, dict):
        raise CheckoutError("Snapshot must be an object")
    if set(snapshot) != {"account_id", "cart_id", "cart_version", "currency", "total_uzs", "items", "address", "payment", "delivery", "available_for_checkout"}:
        raise CheckoutError("Unexpected or missing snapshot fields")
    if not all(_text(snapshot.get(k)) for k in ("account_id", "cart_id")):
        raise CheckoutError("Account and cart identities are required")
    v = snapshot.get("cart_version")
    if type(v) is not int or v < 0:
        raise CheckoutError("Cart version must be a nonnegative integer")
    if snapshot.get("currency") != "UZS" or not _amount(snapshot.get("total_uzs")):
        raise CheckoutError("Exact nonnegative UZS total required as a decimal string")
    if snapshot.get("available_for_checkout") is not True:
        raise CheckoutError("Cart availability for checkout is not confirmed")
    items = snapshot.get("items")
    if not isinstance(items, list) or not items:
        raise CheckoutError("A nonempty item list is required")
    for item in items:
        if not isinstance(item, dict) or set(item) != {"id", "title", "quantity", "price_uzs"} or not all(_text(item.get(k)) for k in ("id", "title", "quantity")) or not _amount(item.get("price_uzs")):
            raise CheckoutError("Every item requires id, title, quantity, and exact price")
        if not re.fullmatch(r"(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,3})?", item["quantity"]) or not any(c in "123456789" for c in item["quantity"]):
            raise CheckoutError("Item quantity must be a positive decimal string")
    for key, fields in (("address", ("id", "label")), ("payment", ("id", "type", "label")), ("delivery", ("type", "label"))):
        obj = snapshot.get(key)
        if not isinstance(obj, dict) or set(obj) != set(fields) or not all(_text(obj.get(field)) for field in fields):
            raise CheckoutError(f"Complete {key} identity and label required")
    try:
        return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise CheckoutError("Snapshot must contain only JSON values") from None


class CheckoutSafety:
    """Persist and atomically consume a local preview; never contacts Lavka.

    The caller must pass a freshly fetched, independently normalized snapshot to
    confirm. No such authenticated Uzbekistan reader exists here yet. State must
    live on durable local storage in a trusted private directory, not scratch.
    """
    def __init__(self, path, *, clock=time.time, max_age_seconds=300):
        self.path = os.fspath(path)
        if self.path == ":memory:":
            raise CheckoutError("A durable state database is required")
        if not isinstance(max_age_seconds, (int, float)) or isinstance(max_age_seconds, bool) or not math.isfinite(max_age_seconds) or not 0 < max_age_seconds <= 300:
            raise CheckoutError("Preview lifetime must be between 0 and 300 seconds")
        self.clock = clock
        self.max_age_seconds = max_age_seconds
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.path, flags, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise CheckoutError("State database must be a private owner-only regular file")
        finally:
            os.close(fd)
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS previews (token TEXT PRIMARY KEY, snapshot TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, state TEXT NOT NULL)")

    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA synchronous=FULL")
        return db

    def preview(self, snapshot):
        encoded = _validated(snapshot)
        created = self.clock()
        if not isinstance(created, (int, float)) or not math.isfinite(created):
            raise CheckoutError("Clock unavailable")
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_uncertain(db, snapshot["account_id"])
            db.execute("INSERT INTO previews VALUES (?, ?, ?, ?, 'staged')", (digest, encoded, created, created + self.max_age_seconds))
        return {"snapshot": json.loads(encoded), "preview_token": token, "expires_at": created + self.max_age_seconds, "order_submission_enabled": False}

    @staticmethod
    def _check_uncertain(db, account_id):
        rows = db.execute("SELECT snapshot FROM previews WHERE state = 'uncertain'")
        if any(json.loads(row[0])["account_id"] == account_id for row in rows):
            raise CheckoutError("An earlier attempt is uncertain; reconcile with Lavka before proceeding")

    def mark_uncertain(self, token):
        """Quarantine an account locally; never use as a submit authorization.

        This is a conservative placeholder for reconciliation research, not a
        transaction wrapper. No API for clearing uncertainty is implemented.
        """
        if not _text(token):
            raise CheckoutError("Unknown preview")
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM previews WHERE token = ?", (digest,)).fetchone():
                raise CheckoutError("Unknown preview")
            db.execute("UPDATE previews SET state = 'uncertain' WHERE token = ?", (digest,))

    def confirm(self, token, snapshot, *, confirmed_total_uzs, explicit_confirmation):
        if not _text(token) or explicit_confirmation is not True:
            raise CheckoutError("Explicit confirmation and preview token required")
        encoded = _validated(snapshot)
        if not _amount(confirmed_total_uzs) or confirmed_total_uzs != snapshot["total_uzs"]:
            raise CheckoutError("Confirmed total does not match preview")
        now = self.clock()
        if not isinstance(now, (int, float)) or not math.isfinite(now):
            raise CheckoutError("Clock unavailable")
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT snapshot, created, expires, state FROM previews WHERE token = ?", (digest,)).fetchone()
            if not row:
                raise CheckoutError("Unknown preview")
            if row[3] != "staged":
                raise CheckoutError("Preview already consumed")
            self._check_uncertain(db, snapshot["account_id"])
            if now < row[1] or now >= row[2] or now - row[1] >= self.max_age_seconds:
                raise CheckoutError("Preview expired")
            if row[0] != encoded:
                raise CheckoutError("Confirmation does not match preview")
            db.execute("UPDATE previews SET state = 'confirmed_offline' WHERE token = ?", (digest,))
            # Other snapshots for the same cart version are not independent
            # authorizations, even when separately staged.
            for other_token, other_snapshot in db.execute("SELECT token, snapshot FROM previews WHERE state = 'staged'").fetchall():
                other = json.loads(other_snapshot)
                if (other["account_id"], other["cart_id"], other["cart_version"]) == (snapshot["account_id"], snapshot["cart_id"], snapshot["cart_version"]):
                    db.execute("UPDATE previews SET state = 'consumed' WHERE token = ?", (other_token,))
        return {"status": "confirmed_offline", "order_submission_enabled": False}
