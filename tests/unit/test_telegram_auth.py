"""Regression tests for Mini App initData validation — HMAC signature + replay/expiry.

This guards the single front door every authenticated endpoint trusts; a regression here would let a
forged or stale initData through. Covers: valid, field-order independence, tampered hash, missing
hash, expired auth_date (replay window), garbage input, and a signature made with the wrong token.
"""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException

import apps.api.app.services.telegram_auth as ta

TOKEN = "999999:TEST-BOT-TOKEN"


class _Settings:
    telegram_bot_token = TOKEN


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch):
    monkeypatch.setattr(ta, "get_settings", lambda: _Settings())


def _sign(fields: dict, token: str = TOKEN) -> str:
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()


def _init_data(*, auth_date=None, user=None, token=TOKEN, hash_first=False) -> str:
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "user": json.dumps(user or {"id": 7, "first_name": "Ann"}, separators=(",", ":")),
    }
    h = _sign(fields, token)
    items = list(fields.items())
    return urlencode([("hash", h), *items] if hash_first else [*items, ("hash", h)])


def test_valid_init_data_returns_user():
    user = ta.validate_init_data(_init_data(user={"id": 7, "first_name": "Ann"}))
    assert user["id"] == 7


def test_field_order_is_irrelevant():
    # hash placed first, declared order shuffled — still valid (the check string is sorted).
    user = ta.validate_init_data(_init_data(hash_first=True))
    assert user["id"] == 7


def test_tampered_hash_rejected():
    raw = _init_data()
    bad = raw[:-1] + ("0" if raw[-1] != "0" else "1")
    with pytest.raises(HTTPException) as e:
        ta.validate_init_data(bad)
    assert e.value.status_code == 401


def test_missing_hash_rejected():
    fields = {"auth_date": str(int(time.time())), "user": json.dumps({"id": 7})}
    with pytest.raises(HTTPException) as e:
        ta.validate_init_data(urlencode(fields))
    assert e.value.status_code == 400


def test_expired_auth_date_rejected():
    old = int(time.time()) - 48 * 3600  # past the 24h replay window
    with pytest.raises(HTTPException) as e:
        ta.validate_init_data(_init_data(auth_date=old))
    assert e.value.status_code == 401


def test_garbage_rejected():
    with pytest.raises(HTTPException):
        ta.validate_init_data("not%20init%20data%20at%20all")


def test_signature_with_wrong_token_rejected():
    with pytest.raises(HTTPException) as e:
        ta.validate_init_data(_init_data(token="111111:OTHER-TOKEN"))
    assert e.value.status_code == 401
