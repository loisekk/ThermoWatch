/**
 * Review state machine — CLIENT-SIDE MIRROR of the server's
 * app/services/review_rules.py. The server always re-validates; this copy
 * exists purely to hint the UI (which buttons to offer, when a note is due).
 */
import type { Disposition } from '@/services/api/v2Types';

export const ALLOWED_TRANSITIONS: Record<Disposition, Disposition[]> = {
  needs_review: ["reviewed", "escalated", "dismissed"],
  reviewed: ["needs_review", "escalated", "dismissed"],
  escalated: ["needs_review"],
  dismissed: ["needs_review"],
};

export const NOTE_REQUIRED: readonly Disposition[] = ["escalated", "dismissed"];
export const MIN_NOTE_CHARS = 10;

export function allowedActions(status: Disposition): Disposition[] {
  return ALLOWED_TRANSITIONS[status] ?? [];
}

export function isNoteRequired(action: Disposition): boolean {
  return NOTE_REQUIRED.includes(action);
}

export function isNoteSufficient(note: string): boolean {
  return note.trim().length >= MIN_NOTE_CHARS;
}

export const ACTION_LABELS: Record<Disposition, string> = {
  needs_review: "Reopen (needs review)",
  reviewed: "Mark reviewed",
  escalated: "Escalate",
  dismissed: "Dismiss",
};

/** Generate a fresh idempotency key — one per intended submission. */
export function newIdempotencyKey(): string {
  return `rv-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}
