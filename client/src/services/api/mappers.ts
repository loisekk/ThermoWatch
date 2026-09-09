import type { FireEvent, FireClass, FireRegime, RiskLevel } from '@/types/domain';

const CLASSES: FireClass[] = ['industrial', 'persistent', 'wildfire', 'agricultural'];
const REGIMES: FireRegime[] = ['transient', 'persistent', 'seasonal'];
const RISKS: RiskLevel[] = ['low', 'moderate', 'high', 'critical'];

const pick = <T extends string>(v: unknown, allowed: T[], fallback: T): T =>
  allowed.includes(v as T) ? (v as T) : fallback;
const num = (v: unknown, fallback = 0): number => (typeof v === 'number' && Number.isFinite(v) ? v : fallback);

/**
 * FastAPI events are snake_case with slightly different field names than the
 * client's FireEvent model. Normalise defensively so a partial/malformed
 * server frame can never crash the console.
 */
export function mapServerEvent(raw: Record<string, unknown>): FireEvent | null {
  const lat = num(raw.lat, NaN);
  const lon = num(raw.lon, NaN);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;

  const cls = (raw.classification ?? {}) as Record<string, unknown>;
  const pers = (raw.persistence ?? {}) as Record<string, unknown>;
  const risk = (raw.risk ?? {}) as Record<string, unknown>;
  const scoresIn = (cls.scores ?? {}) as Record<string, unknown>;

  const primary = pick(cls.primary, CLASSES, 'wildfire');
  const scores = CLASSES.reduce(
    (acc, c) => { acc[c] = num(scoresIn[c]); return acc; },
    {} as Record<FireClass, number>,
  );
  const conf = Math.round(num(cls.confidence, 55));

  return {
    id: typeof raw.id === 'string' ? raw.id : `SRV-${String(raw.cell ?? '??')}-${Math.round(num(raw.detected_at))}`,
    lat,
    lon,
    frp: num(raw.frp),
    brightnessK: num(raw.brightness_k),
    confidence: Math.round(num(raw.confidence, conf)),
    detectedAt: num(raw.detected_at),
    satellite: typeof raw.satellite === 'string' ? (raw.satellite as FireEvent['satellite']) : 'VIIRS-SNPP',
    dayNight: raw.day_night === 'N' ? 'N' : 'D',
    classification: {
      primary,
      subtype: typeof cls.subtype === 'string' ? (cls.subtype as FireEvent['classification']['subtype']) : null,
      scores,
      confidence: conf,
    },
    persistence: {
      consecutiveDays: Math.round(num(pers.consecutive_days)),
      detections30d: Math.round(num(pers.detections_30d)),
      regime: pick(pers.regime, REGIMES, 'transient'),
    },
    risk: {
      score: Math.round(num(risk.score)),
      level: pick(risk.level, RISKS, 'low'),
      drivers: Array.isArray(risk.drivers) ? (risk.drivers as string[]) : [],
    },
    nearestFacilityId: typeof raw.nearest_facility_id === 'string' ? raw.nearest_facility_id : null,
    facilityDistanceKm: raw.facility_distance_km == null ? null : num(raw.facility_distance_km),
  };
}

export function mapServerEvents(raws: unknown[]): FireEvent[] {
  return raws
    .filter((r): r is Record<string, unknown> => typeof r === 'object' && r !== null)
    .map(mapServerEvent)
    .filter((e): e is FireEvent => e !== null);
}
