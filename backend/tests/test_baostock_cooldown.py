"""Baostock 登录黑名单冷却: 10001011 后不应继续高频 login。"""
from __future__ import annotations

import app.plugins.baostock.provider as provider


def _reset() -> None:
    provider._bs_session_refs = 0
    provider._login_blocked_until = 0.0
    provider._last_login_error = ""


def test_blacklist_sets_cooldown_and_skips_login(monkeypatch):
    _reset()
    calls: list[int] = []

    def fake_login():
        calls.append(1)
        return False, "[10001011] 黑名单用户,请与管理员联系"

    monkeypatch.setattr(provider, "_do_login", fake_login)

    ok, msg = provider._session_acquire()
    assert not ok
    assert "10001011" in msg
    assert len(calls) == 1
    assert provider._login_blocked_until > 0

    ok, _ = provider._session_acquire()
    assert not ok
    assert len(calls) == 1
    _reset()


def test_non_blacklist_failure_retries_next_call(monkeypatch):
    _reset()
    calls: list[int] = []

    def fake_login():
        calls.append(1)
        return False, "[10002007] 网络接收错误"

    monkeypatch.setattr(provider, "_do_login", fake_login)

    assert not provider._session_acquire()[0]
    assert provider._login_blocked_until == 0.0
    assert not provider._session_acquire()[0]
    assert len(calls) == 2
    _reset()
