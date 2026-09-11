import type { IndustrialSubtype } from '@/types/domain';

/** NBC 2016 Part F industrial hazard classes. */
export const NBC_HAZARD: Record<string, { label: string; desc: string }> = {
  'G-I': { label: 'Low hazard', desc: 'Low combustibility contents; minimal fire load.' },
  'G-II': { label: 'Moderate hazard', desc: 'Burns moderately; smoke generation, no toxic fumes.' },
  'G-III': { label: 'High hazard', desc: 'Extremely rapid burn; toxic fumes / explosion risk.' },
};

export const OSM_TAGS: Record<IndustrialSubtype, string> = {
  refinery: 'industrial=refinery',
  steel: 'industrial=steel_mill',
  gas_flare: 'man_made=flare',
  cement: 'industrial=cement_kiln',
  smelter: 'industrial=smelter',
  chemical: 'industrial=chemical',
  power_plant: 'power=plant',
};

export const OCEMS_CATEGORIES = ['Power Plants', 'Cement', 'Steel', 'Oil Refineries', 'Chemicals', 'Sugar', 'Pharma', 'Textiles'];

/** Live OSM query for this location — deep-linkable forensic helper. */
export function overpassTurboUrl(lat: number, lon: number, radiusKm = 2): string {
  const r = Math.round(radiusKm * 1000);
  const q = `[out:json][timeout:60];(node["industrial"](around:${r},${lat},${lon});way["industrial"](around:${r},${lat},${lon});node["man_made"="flare"](around:${r},${lat},${lon}););out center 50;`;
  return `https://overpass-turbo.eu/?Q=${encodeURIComponent(q)}`;
}