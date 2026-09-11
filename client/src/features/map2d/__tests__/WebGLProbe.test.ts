import { describe, expect, it } from 'vitest';
import { probeRenderer, probeWebGL } from '../WebGLProbe';

describe('WebGLProbe (node env)', () => {
  it('probeWebGL reports no context without a DOM', () => {
    const s = probeWebGL();
    expect(s.context).toBe(false);
    expect(s.rasterizes).toBe(false);
    expect(s.renderer).toBe('none');
  });

  it('probeRenderer resolves the full capability shape', async () => {
    const c = await probeRenderer();
    expect(typeof c.rafFps).toBe('number');
    expect(typeof c.shimmed).toBe('boolean');
    expect(c.ok).toBe(false); // no GL context in node
  });
});
