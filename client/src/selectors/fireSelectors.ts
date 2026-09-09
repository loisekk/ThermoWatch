import { HISTORY_DAYS } from '@/config/constants';
import { haversineKm } from '@/lib/geo/distance';
import type { FireClass, FireEvent, Facility, Filters } from '@/types/domain';

const DAY = 86_400_000;

export function filterEvents(events: FireEvent[], f: Filters): FireEvent[] {
  return events.filter(
    (e) =>
      f.classes.includes(e.classification.primary) &&
      e.classification.confidence >= f.minConfidence &&
      (!f.persistentOnly || e.persistence.regime === 'persistent'),
  );
}

export interface Kpis {
  active24: number;
  delta24: number;
  industrialShare: number;
  persistentCount: number;
  meanConfidence: number;
}

export function computeKpis(events: FireEvent[], now = Date.now()): Kpis {
  const last24 = events.filter((e) => now - e.detectedAt <= DAY);
  const prev24 = events.filter((e) => now - e.detectedAt > DAY && now - e.detectedAt <= 2 * DAY);
  const industrial = last24.filter((e) => e.classification.primary === 'industrial').length;
  const persistent = events.filter((e) => now - e.detectedAt <= 7 * DAY && e.persistence.regime === 'persistent').length;
  return {
    active24: last24.length,
    delta24: last24.length - prev24.length,
    industrialShare: last24.length ? (industrial / last24.length) * 100 : 0,
    persistentCount: persistent,
    meanConfidence: last24.length ? last24.reduce((a, e) => a + e.classification.confidence, 0) / last24.length : 0,
  };
}

export function computeBreakdown(events: FireEvent[]): Record<FireClass, number> {
  const out: Record<FireClass, number> = { industrial: 0, persistent: 0, wildfire: 0, agricultural: 0 };
  for (const e of events) out[e.classification.primary]++;
  return out;
}

export interface TimelineDay { ts: number; label: string; counts: Record<FireClass, number>; total: number }

export function computeTimeline(events: FireEvent[], now = Date.now()): TimelineDay[] {
  const days: TimelineDay[] = Array.from({ length: HISTORY_DAYS }, (_, i) => {
    const ts = now - (HISTORY_DAYS - 1 - i) * DAY;
    return { ts, label: new Date(ts).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: 'UTC' }), counts: { industrial: 0, persistent: 0, wildfire: 0, agricultural: 0 }, total: 0 };
  });
  const bucket = (ts: number): TimelineDay | undefined => {
    const idx = HISTORY_DAYS - 1 - Math.floor((now - ts) / DAY);
    return idx >= 0 && idx < HISTORY_DAYS ? days[idx] : undefined;
  };
  for (const e of events) {
    if (e.persistence.regime === 'persistent') {
      for (let d = 0; d < Math.min(e.persistence.consecutiveDays, HISTORY_DAYS); d++) {
        const b = bucket(e.detectedAt - d * DAY);
        if (b) { b.counts[e.classification.primary]++; b.total++; }
      }
    } else {
      const b = bucket(e.detectedAt);
      if (b) { b.counts[e.classification.primary]++; b.total++; }
    }
  }
  return days;
}

export function topPersistent(events: FireEvent[], n = 8): FireEvent[] {
  return events
    .filter((e) => e.persistence.regime === 'persistent')
    .sort((a, b) => b.persistence.consecutiveDays - a.persistence.consecutiveDays)
    .slice(0, n);
}

export function eventsNearFacility(events: FireEvent[], f: Facility, km = 3, hours = 24, now = Date.now()): FireEvent[] {
  return events.filter((e) => now - e.detectedAt <= hours * 3_600_000 && haversineKm(e.lat, e.lon, f.lat, f.lon) <= km);
}
