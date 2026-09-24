/**
 * Review state-machine mirror tests — must track server
 * app/services/review_rules.py (the server always re-validates; this copy
 * only hints which buttons and note prompts the UI shows).
 */
import { describe, expect, it } from 'vitest';
import {
  ACTION_LABELS,
  ALLOWED_TRANSITIONS,
  MIN_NOTE_CHARS,
  allowedActions,
  isNoteRequired,
  isNoteSufficient,
  newIdempotencyKey,
} from '../reviewRules';
import type { Disposition } from '@/services/api/v2Types';

describe('allowedActions', () => {
  it('offers the closed transition set from needs_review', () => {
    expect(allowedActions('needs_review')).toEqual(['reviewed', 'escalated', 'dismissed']);
  });

  it('allows reopening reviewed rows back to any disposition', () => {
    expect(allowedActions('reviewed')).toEqual(['needs_review', 'escalated', 'dismissed']);
  });

  it('only allows reopening escalated/dismissed rows', () => {
    expect(allowedActions('escalated')).toEqual(['needs_review']);
    expect(allowedActions('dismissed')).toEqual(['needs_review']);
  });

  it('never offers a self-transition', () => {
    for (const status of Object.keys(ALLOWED_TRANSITIONS) as Disposition[]) {
      expect(allowedActions(status)).not.toContain(status);
    }
  });

  it('degrades to no actions for an unknown status', () => {
    expect(allowedActions('rotated' as Disposition)).toEqual([]);
  });
});

describe('note rules', () => {
  it('demands a note only for terminal judgements', () => {
    expect(isNoteRequired('escalated')).toBe(true);
    expect(isNoteRequired('dismissed')).toBe(true);
    expect(isNoteRequired('reviewed')).toBe(false);
    expect(isNoteRequired('needs_review')).toBe(false);
  });

  it('requires trimmed length >= MIN_NOTE_CHARS', () => {
    expect(MIN_NOTE_CHARS).toBe(10);
    expect(isNoteSufficient('')).toBe(false);
    expect(isNoteSufficient('   ')).toBe(false);
    expect(isNoteSufficient('123456789')).toBe(false);
    expect(isNoteSufficient('1234567890')).toBe(true);
    expect(isNoteSufficient('  1234567890  ')).toBe(true);
  });
});

describe('ACTION_LABELS', () => {
  it('labels every disposition for button copy', () => {
    for (const status of Object.keys(ALLOWED_TRANSITIONS) as Disposition[]) {
      expect(ACTION_LABELS[status]).toBeTruthy();
    }
  });
});

describe('newIdempotencyKey', () => {
  it('is namespaced and unique per call', () => {
    const a = newIdempotencyKey();
    const b = newIdempotencyKey();
    expect(a).toMatch(/^rv-\d+-[a-z0-9]+$/);
    expect(a).not.toBe(b);
  });
});
