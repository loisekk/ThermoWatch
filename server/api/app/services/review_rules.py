"""Analyst review state machine (Phase 4) — the single server-side source of
truth for which disposition changes are legal.

``ALLOWED_TRANSITIONS`` is mirrored by the ReviewControls UI (client-side
hint only) — the server always re-validates before persisting. Review events
are append-only, so an illegal transition attempt is rejected with 422 and
never recorded.
"""
from __future__ import annotations

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "needs_review": {"reviewed", "escalated", "dismissed"},
    "reviewed": {"needs_review", "escalated", "dismissed"},
    "escalated": {"needs_review"},
    "dismissed": {"needs_review"},
}

# A substantive rationale is mandatory before escalating or dismissing —
# the audit trail must record WHY a source was written off or promoted.
NOTE_REQUIRED_FOR: frozenset[str] = frozenset({"escalated", "dismissed"})
MIN_NOTE_CHARS = 10


def allowed_actions(status: str) -> list[str]:
    """Sorted list of dispositions reachable from ``status`` (UI hint + 422 detail)."""
    return sorted(ALLOWED_TRANSITIONS.get(status, set()))


def is_transition_valid(current: str, target: str) -> bool:
    """True when ``current -> target`` is an allowed disposition change."""
    return target in ALLOWED_TRANSITIONS.get(current, set())


def note_required(action: str) -> bool:
    """True when ``action`` demands a substantive rationale note."""
    return action in NOTE_REQUIRED_FOR


def note_sufficient(note: str | None) -> bool:
    """True when the note exists and meets the minimum substantive length."""
    return note is not None and len(note.strip()) >= MIN_NOTE_CHARS
