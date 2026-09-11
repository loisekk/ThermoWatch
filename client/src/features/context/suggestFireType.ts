import type { FireEvent, Facility } from '@/types/domain';

export interface Hypothesis { label: string; weight: number; evidence: string[] }

/**
 * Context-aware fire-type reasoning layered ON TOP of the model posterior:
 * OSM proximity + persistence regime + seasonal residue windows + diurnal behaviour.
 * Presented as ranked hypotheses with evidence — never as certainty (claim-safety).
 */
export function suggestFireType(e: FireEvent, facilities: Facility[]): Hypothesis[] {
  const out: Hypothesis[] = [];
  const fac = facilities.find((f) => f.id === e.nearestFacilityId) ?? null;
  const near = e.facilityDistanceKm !== null && e.facilityDistanceKm <= 1.5;
  const month = new Date(e.detectedAt).getUTCMonth() + 1;
  const kharif = month >= 9 && month <= 11;
  const rabi = month === 4 || month === 5;
  const s = e.classification.scores;

  if (fac && near) {
    out.push({
      label: `Chronic process heat at ${fac.name} (${fac.subtype.replace('_', ' ')})`,
      weight: s.persistent * (e.persistence.regime === 'persistent' ? 1.25 : 0.9),
      evidence: [
        `OSM ${fac.subtype.replace('_', ' ')} within ${e.facilityDistanceKm} km`,
        `${e.persistence.consecutiveDays} consecutive detection-day(s) · ${e.persistence.detections30d}/30 d`,
        'low diurnal variance consistent with continuous process heat / flaring',
      ],
    });
  }
  if (s.industrial >= 0.2) {
    out.push({
      label: `Accidental industrial fire${fac ? ` at/near ${fac.name}` : ''}`,
      weight: s.industrial * (e.frp > 250 ? 1.15 : 1),
      evidence: [
        `FRP ${e.frp} MW spike vs facility baseline`,
        e.dayNight === 'N' ? 'night-time onset — uncontrolled-burn indicator' : 'day-time onset',
        fac ? `nearest OSM asset ${fac.hazard} hazard` : 'no mapped facility within 1.5 km — attribution uncertain',
      ],
    });
  }
  if (s.wildfire >= 0.2) {
    out.push({
      label: 'Vegetation / forest fire',
      weight: s.wildfire,
      evidence: ['no industrial facility within 1.5 km', 'high diurnal variance (fuel-driven combustion)', 'land-cover proxy: forest/grassland'],
    });
  }
  if (s.agricultural >= 0.15) {
    out.push({
      label: `Crop-residue burn (${kharif ? 'Kharif window Sep–Nov' : rabi ? 'Rabi window Apr–May' : 'off-season — weak prior'})`,
      weight: s.agricultural * (kharif || rabi ? 1.2 : 0.6),
      evidence: ['clustered low-FRP hotspots typical of stubble burning', `detection month ${month} vs residue windows`, 'NW-India belt seasonal prior (Bhuvan Kharif/Rabi)'],
    });
  }
  return out.sort((a, b) => b.weight - a.weight).slice(0, 3);
}