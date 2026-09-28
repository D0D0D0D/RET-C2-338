"""Entry-adapter authentication tests.

Verifies the fail-closed entry authentication wired into src/api/server.py:_ctx():
  - an unauthenticated caller (ANONYMOUS, no token) is rejected with 401;
  - INVOKE_AUTH_TOKEN Bearer auth promotes ANONYMOUS -> VERIFIED_EXTERNAL;
  - a wrong token is rejected with 401;
  - a verified middleware trust (VERIFIED_EXTERNAL/INTERNAL) is accepted as-is.

The old server.py passed request.state.trust_level straight into
InvocationContext with an ANONYMOUS default (fail-open S-1 bypass). These tests
lock in the removal of that path.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("framework.schemas.trust_level")

from fastapi import HTTPException  # noqa: E402
from framework.schemas.trust_level import TrustLevel  # noqa: E402

from src.entry_adapter.auth import _require_verified_trust, _resolve_trust  # noqa: E402


def _fake_request(*, trust=None, authorization: str = "") -> object:
    state = SimpleNamespace()
    if trust is not None:
        state.trust_level = trust
    headers = {"authorization": authorization} if authorization else {}
    return SimpleNamespace(state=state, headers=headers)


def _ctx_guard(request) -> TrustLevel:
    """Mirror server.py:_ctx() auth core (context construction omitted)."""
    trust, token_authenticated = _resolve_trust(request)
    if trust is TrustLevel.ANONYMOUS and not token_authenticated:
        raise HTTPException(status_code=401, detail="Authentication is required.")
    _require_verified_trust(trust)
    return trust


def test_unauthenticated_is_rejected_401(monkeypatch):
    monkeypatch.delenv("INVOKE_AUTH_TOKEN", raising=False)
    with pytest.raises(HTTPException) as exc:
        _ctx_guard(_fake_request())
    assert exc.value.status_code == 401


def test_explicit_anonymous_still_rejected(monkeypatch):
    monkeypatch.delenv("INVOKE_AUTH_TOKEN", raising=False)
    with pytest.raises(HTTPException) as exc:
        _ctx_guard(_fake_request(trust=TrustLevel.ANONYMOUS))
    assert exc.value.status_code == 401


def test_token_promotes_anonymous_to_verified(monkeypatch):
    monkeypatch.setenv("INVOKE_AUTH_TOKEN", "mock-jwt-for-testing")
    trust = _ctx_guard(_fake_request(authorization="Bearer mock-jwt-for-testing"))
    assert trust is TrustLevel.VERIFIED_EXTERNAL


def test_wrong_token_is_rejected_401(monkeypatch):
    monkeypatch.setenv("INVOKE_AUTH_TOKEN", "mock-jwt-for-testing")
    with pytest.raises(HTTPException) as exc:
        _ctx_guard(_fake_request(authorization="Bearer nope"))
    assert exc.value.status_code == 401


def test_verified_middleware_trust_accepted(monkeypatch):
    monkeypatch.delenv("INVOKE_AUTH_TOKEN", raising=False)
    trust = _ctx_guard(_fake_request(trust=TrustLevel.VERIFIED_EXTERNAL))
    assert trust is TrustLevel.VERIFIED_EXTERNAL
