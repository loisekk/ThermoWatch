import { describe, expect, it } from 'vitest';
import { probeWebGL } from '../WebGLProbe';

describe('probe context hygiene (node env)', () => {
  it('repeated probes never throw and never accumulate state', () => {
    for (let i = 0; i < 25; i++) {
      const s = probeWebGL();
      expect(s.context).toBe(false); // no DOM in node
      expect(s.renderer).toBe('none');
    }
  });
});