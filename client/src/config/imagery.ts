/** NASA GIBS — official imagery tile service (no key). FIRMS has no imagery; GIBS does. */
export const GIBS_LAYERS = {
  truecolor: { id: 'VIIRS_SNPP_CorrectedReflectance_TrueColor', maxZ: 9, label: 'VIIRS True-Color (day)' },
  night: { id: 'VIIRS_Black_Marble', maxZ: 8, label: 'Black Marble (night)' },
} as const;

export type GibsKey = keyof typeof GIBS_LAYERS;

/** GIBS is daily-composited; yesterday's date is the safest "latest". */
export function gibsDate(offsetDays = 1): string {
  return new Date(Date.now() - offsetDays * 86_400_000).toISOString().slice(0, 10);
}

export function gibsTileUrl(layer: GibsKey, z: number, x: number, y: number): string {
  const L = GIBS_LAYERS[layer];
  return `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/${L.id}/default/${gibsDate()}/GoogleMapsCompatible_Level${L.maxZ}/${z}/${y}/${x}.jpg`;
}

export const GIBS_ATTRIBUTION = 'Imagery: NASA EOSDIS GIBS (VIIRS Suomi-NPP)';