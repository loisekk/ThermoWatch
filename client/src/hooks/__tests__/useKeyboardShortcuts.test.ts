import { describe, expect, it } from 'vitest';
import { isTypingTarget } from '../useKeyboardShortcuts';

const el = (tagName: string, contentEditable = false) => ({ tagName, isContentEditable: contentEditable } as HTMLElement);
const ev = (target: HTMLElement | null) => ({ target, isComposing: false } as unknown as KeyboardEvent);

describe('isTypingTarget', () => {
  it('silences shortcuts inside text entry surfaces', () => {
    expect(isTypingTarget(ev(el('input')))).toBe(true);
    expect(isTypingTarget(ev(el('textarea')))).toBe(true);
    expect(isTypingTarget(ev(el('select')))).toBe(true);
    expect(isTypingTarget(ev(el('div', true)))).toBe(true);
  });
  it('allows shortcuts from the page body', () => {
    expect(isTypingTarget(ev(el('body')))).toBe(false);
    expect(isTypingTarget(ev(null))).toBe(false);
  });
});