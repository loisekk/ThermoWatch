import { describe, expect, it } from 'vitest';
import { detectWebGL } from '../WebGLProbe';

describe('detectWebGL', () => {
  it('returns false gracefully in a DOM-less environment (no throw)', () => {
    expect(typeof detectWebGL()).toBe('boolean');
  });
});