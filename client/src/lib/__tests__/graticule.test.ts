import { describe, expect, it } from 'vitest';
import { makeGraticule } from '@/lib/geo/graticule';

describe('makeGraticule', () => {
  it('emits 25 meridians + 10 parallels at 15°', () => {
    const g = makeGraticule();
    expect(g.features).toHaveLength(35);
  });
  it('flags equator and prime meridian as major', () => {
    const majors = makeGraticule().features.filter((f) => f.properties?.major === 1);
    expect(majors).toHaveLength(2);
  });
  it('closes the world span with 5° sampling density', () => {
    const g = makeGraticule();
    const meridian = g.features[0];
    expect(meridian.geometry.coordinates[0][0]).toBe(-180);
    expect(meridian.geometry.coordinates[0][1]).toBe(-60);
    expect(meridian.geometry.coordinates.at(-1)?.[1]).toBe(85);
  });
});
