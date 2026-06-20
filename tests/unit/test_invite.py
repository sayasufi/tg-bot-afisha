"""Regression tests for signed «Пойдём?» invite tokens.

These guard the anti-spoof property: only a (event_id, inviter_id) pair our own share endpoint signed
verifies, so a forged inviter can't be replayed to DM-spam a user or probe their taste via warm-start.
A regression that weakened the HMAC (or compared the wrong fields) would reopen both abuse vectors.
"""
import core.invite as invite

TOKEN = "123456:INVITE-TEST-TOKEN"


class _Settings:
    telegram_bot_token = TOKEN


def _patch(monkeypatch):
    monkeypatch.setattr(invite, "get_settings", lambda: _Settings())


def test_sign_verify_roundtrip(monkeypatch):
    _patch(monkeypatch)
    sig = invite.sign("evt-1", 555)
    assert invite.verify("evt-1", 555, sig)


def test_rejects_wrong_inviter(monkeypatch):
    _patch(monkeypatch)
    sig = invite.sign("evt-1", 555)
    assert not invite.verify("evt-1", 556, sig)


def test_rejects_wrong_event(monkeypatch):
    _patch(monkeypatch)
    sig = invite.sign("evt-1", 555)
    assert not invite.verify("evt-2", 555, sig)


def test_rejects_tampered_sig(monkeypatch):
    _patch(monkeypatch)
    sig = invite.sign("evt-1", 555)
    tampered = sig[:-1] + ("0" if sig[-1] != "0" else "1")
    assert not invite.verify("evt-1", 555, tampered)


def test_rejects_missing_inputs(monkeypatch):
    _patch(monkeypatch)
    assert not invite.verify("evt-1", 555, None)
    assert not invite.verify("evt-1", 555, "")
    assert not invite.verify("evt-1", None, "abc")


def test_sig_fits_telegram_start_param(monkeypatch):
    _patch(monkeypatch)
    # 12 hex chars keeps «<uuid>_<inviter>_<sig>» well under Telegram's 64-char start_param.
    assert len(invite.sign("evt-1", 555)) == 12
