/** T9 cartographic palette + scale-bar math — every colour a deliberate choice
 *  over REAL OSM data, never invented geometry. Pure (no three import) so it is
 *  vitest-node safe and shared by the WebGL + canvas parity paths. */

export const CARTO = {
  ground: 0x10141a, gridOpacity: 0.15,
  building: { industrial: 0x4b5563, commercial: 0x5b6472, residential: 0x6e5a49, generic: 0x565e6a },
  buildingOutline: 0x9fb0c1, roofBoost: 1.18, // roof albedo × (1 + boost)
  roadCasing: 0x1c2126, roadFill: 0x8a949e, roadFillRes: 0x6b7480,
  water: 0x1d3a52, waterShore: 0x2b5a7a,
  wood: 0x24422a, canopy: 0x3f7a3c,
  landuse: { farmland: 0x2c3a2e, orchard: 0x33402c, industrial: 0x3a3f46,
             commercial: 0x40454e, residential: 0x363b42, forest: 0x24422a },
  label: { fill: '#e8eef4', halo: '#0b0e13', road: '#c3cbd4' },
} as const;

export const LABEL_CAP = 12;

/** Hex number → '#rrggbb' (canvas parity path). */
export const hexStr = (n: number): string => `#${n.toString(16).padStart(6, '0')}`;

/** Pick a round scale-bar length whose on-screen width is closest to 120 px.
 *  distUnits: camera→target distance in scene units (1 unit = 100 m). */
export function scaleBarMeters(distUnits: number, fovDeg: number, canvasHpx: number): number {
  const mPerPx = (2 * distUnits * Math.tan((fovDeg * Math.PI) / 360) * 100) / canvasHpx;
  const targets = [50, 100, 200, 500, 1000, 2000];
  return targets.reduce((a, b) =>
    Math.abs(b / mPerPx - 120) < Math.abs(a / mPerPx - 120) ? b : a);
}

/** Bottom-left legend swatches (order = reading order). */
export const LEGEND: { color: string; text: string }[] = [
  { color: '#4b5563', text: 'industrial' },
  { color: '#5b6472', text: 'commercial' },
  { color: '#6e5a49', text: 'residential' },
  { color: '#1d3a52', text: 'water' },
  { color: '#24422a', text: 'wood + illustrative canopy' },
  { color: '#8a949e', text: 'road (cased)' },
];
