import { describe, expect, it } from 'vitest';
import { HEAT_RAMP, makeWorldVectorStyle } from '@/config/worldStyle';
import { WORLD_IMAGE_COORDS } from '@/config/basemap';

describe('makeWorldVectorStyle', () => {
  it('is fully bundled: zero external urls, tiles or glyphs', () => {
    const spec = JSON.stringify(makeWorldVectorStyle());
    expect(spec).not.toContain('http');
    expect(spec).not.toContain('.jpg');
    expect(spec).not.toContain('tiles');
    expect(spec).not.toContain('glyphs');
  });
  it('paints ocean → land → borders → graticule', () => {
    expect(makeWorldVectorStyle().layers.map((l) => l.id)).toEqual(['ocean', 'countries-fill', 'countries-line', 'graticule']);
  });
  it('heat ramp keys off feature-state count', () => {
    expect(JSON.stringify(HEAT_RAMP)).toContain('feature-state');
  });
});

describe('WORLD_IMAGE_COORDS', () => {
  it('is an exact TL,TR,BR,BL 4-tuple', () => {
    expect(WORLD_IMAGE_COORDS).toHaveLength(4);
    expect(WORLD_IMAGE_COORDS[0]).toEqual([-180, 85]);
    expect(WORLD_IMAGE_COORDS[2]).toEqual([180, -60]);
  });
});
