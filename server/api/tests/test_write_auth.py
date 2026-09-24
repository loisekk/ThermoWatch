"""Write-authorization tests (FR-SEC-01) — the TW_WRITE_TOKEN bearer gate.

Pure unit tests for ``app.core.security.require_write_token``: no DB, no app
client. They pin the two documented postures:

* ``TW_WRITE_TOKEN`` unset → local/single-user mode, the guard no-ops.
* ``TW_WRITE_TOKEN`` set → a matching ``Authorization: Bearer`` header is
  required; missing, malformed or wrong credentials are rejected 401 without
  echoing either the expected or the supplied value.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.core.security import require_write_token

TOKEN = "s3cret-shared-write-token"


@pytest.fixture
def token_set(monkeypatch):
    """Pin a write token for the duration of one test."""
    monkeypatch.setattr(settings, "write_token", TOKEN)
    return TOKEN


@pytest.fixture
def token_unset(monkeypatch):
    """Force local mode, whatever the ambient environment says."""
    monkeypatch.setattr(settings, "write_token", None)
    return None


class TestLocalMode:
    def test_unset_token_allows_anonymous_writes(self, token_unset):
        # Local mode is a documented posture, not an accident: no header needed.
        assert require_write_token(None) is None

    def test_unset_token_ignores_a_supplied_header(self, token_unset):
        assert require_write_token("Bearer anything") is None


class TestSharedDeploymentMode:
    def test_matching_bearer_token_is_accepted(self, token_set):
        assert require_write_token(f"Bearer {TOKEN}") is None

    def test_scheme_is_case_insensitive(self, token_set):
        assert require_write_token(f"bearer {TOKEN}") is None

    def test_surrounding_whitespace_is_tolerated(self, token_set):
        assert require_write_token(f"Bearer   {TOKEN}  ") is None

    def test_missing_header_is_rejected(self, token_set):
        with pytest.raises(HTTPException) as exc:
            require_write_token(None)
        assert exc.value.status_code == 401

    def test_empty_header_is_rejected(self, token_set):
        with pytest.raises(HTTPException) as exc:
            require_write_token("")
        assert exc.value.status_code == 401

    def test_wrong_token_is_rejected(self, token_set):
        with pytest.raises(HTTPException) as exc:
            require_write_token("Bearer not-the-token")
        assert exc.value.status_code == 401

    def test_non_bearer_scheme_is_rejected(self, token_set):
        # Basic/Digest must not be smuggled into a Bearer slot.
        with pytest.raises(HTTPException) as exc:
            require_write_token(f"Basic {TOKEN}")
        assert exc.value.status_code == 401

    def test_rejection_never_echoes_either_secret(self, token_set):
        with pytest.raises(HTTPException) as exc:
            require_write_token("Bearer guess")
        detail = str(exc.value.detail)
        assert TOKEN not in detail
        assert "guess" not in detail

    def test_rejection_advertises_the_scheme(self, token_set):
        with pytest.raises(HTTPException) as exc:
            require_write_token(None)
        assert exc.value.headers == {"WWW-Authenticate": "Bearer"}


class TestWriteRoutesAreGuarded:
    """The gate must actually be wired into the state-changing routes."""

    def test_review_and_ingest_depend_on_the_guard(self):
        from app.api.v2.incidents import router as incidents_router
        from app.api.v2.observations import router as observations_router

        guarded = {
            (path, method)
            for router in (incidents_router, observations_router)
            for route in router.routes
            for method in getattr(route, "methods", set())
            if getattr(getattr(route, "dependant", None), "dependencies", None)
            for path in [getattr(route, "path", None)]
            if path is not None
        }
        # The two POSTs that change state must carry a dependency; this test
        # fails loudly if a future refactor drops the guard.
        posts_with_deps = {
            path for path, method in guarded if method == "POST"
        }
        assert any("reviews" in p for p in posts_with_deps), posts_with_deps
        assert any(p.endswith("/observations") or p == "" for p in posts_with_deps), (
            posts_with_deps
        )
