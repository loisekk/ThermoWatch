"""Write authorization (FR-SEC-01) — one optional shared bearer token.

Posture, stated plainly:

* **Local / single-user mode** (``TW_WRITE_TOKEN`` unset, the default): the
  v2 write endpoints accept anonymous callers. This is the mode the demo runs
  in and it is documented as such in ``docs/SECURITY.md`` — it is NOT
  authentication, and it must never be used on a shared host.
* **Shared deployment** (``TW_WRITE_TOKEN`` set): every state-changing v2
  endpoint requires ``Authorization: Bearer <token>``. Constant-time compare,
  no token echo in errors, no token in logs.

This deliberately does not model roles, sessions or identity — those are the
documented next step. It closes the gap where an anonymous caller could inject
detections or forge an analyst disposition.
"""
from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.core.config import settings

_BEARER_PREFIX = "bearer "


def require_write_token(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """FastAPI dependency guarding state-changing endpoints.

    No-ops when ``TW_WRITE_TOKEN`` is unset so local dev and the demo keep
    working; otherwise requires a matching bearer token (401 on missing or
    mismatched credentials). The comparison is constant-time and the failure
    detail never echoes the expected or supplied value.
    """
    expected = settings.write_token
    if not expected:
        return  # local mode — documented in docs/SECURITY.md, never for shared hosts

    supplied = ""
    if authorization and authorization.lower().startswith(_BEARER_PREFIX):
        supplied = authorization[len(_BEARER_PREFIX):].strip()

    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "unauthorized",
                "message": "A valid bearer token is required for this endpoint",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
