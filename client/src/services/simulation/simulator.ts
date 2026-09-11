import { mulberry32 } from '@/lib/random/mulberry';
import { FACILITIES } from '@/services/osm/facilitySeed';
import { classify } from '@/services/classification/classifier';
import { assessPersistence } from '@/services/persistence/tracker';
import { scoreRisk } from '@/services/risk/scorer';
import { haversineKm } from '@/lib/geo/distance';
import type { ClassFeatures, Facility, FireEvent, LogLine } from '@/types/domain';

/**
 * Deterministic demo feed — the client-side twin of the FastAPI sim seed
 * (same contract as the Bun worker's live feed). Mirrors server simseed:
 * chronic flare/steel/cement sources repeat daily in the same ~400 m cell;
 * incidents scatter near facilities; wildfire/agri scatter in belts.
 */

const DAY = 86_400_000;
const CELL = 0.004; // ~400 m grid — matches the server's cell_id semantics
const FLARE_SUBTYPES = new Set(['gas_flare', 'refinery', 'cement', 'steel', 'smelter']);
const FLARE = FACILITIES.filter((f) => FLARE_SUBTYPES.has(f.subtype));
const WLD: [number, number, number][] = [[30.1, 79.5, 1.1], [22.3, 79.8, 1.4], [25.6, 93.2, 0.9]];
const AGR: [number, number, number][] = [[30.9, 75.8, 0.8], [29.0, 76.8, 0.7]];

interface RawSim {
  latitude: number; longitude: number; frp: number; bright_ti4: number;
  confidence: number; satellite: 'VIIRS-SNPP' | 'VIIRS-NOAA20' | 'MODIS';
  daynight: 'D' | 'N'; acq_epoch_ms: number; persist_days: number; det30: number;
  forest_proxy: number; agri_window: number; cluster_density: number; diurnal_variance: number;
}

const u = (r: () => number, lo: number, hi: number) => lo + r() * (hi - lo);

function rawFor(kind: 'flare' | 'incident' | 'wildfire' | 'agri', lat: number, lon: number, ts: number, persist: number, det30: number, r: () => number): RawSim {
  const frp = { flare: 60 + r() * 190, incident: 150 + r() * 750, wildfire: 20 + r() * 160, agri: 8 + r() * 52 }[kind];
  return {
    latitude: lat, longitude: lon, frp: Math.round(frp), bright_ti4: Math.round(315 + r() * 120),
    confidence: 55 + Math.round(r() * 44),
    satellite: r() < 0.5 ? 'VIIRS-SNPP' : r() < 0.8 ? 'VIIRS-NOAA20' : 'MODIS',
    daynight: r() < 0.5 ? 'N' : 'D', acq_epoch_ms: ts, persist_days: persist, det30: det30,
    forest_proxy: { flare: 0.05, incident: 0.08, wildfire: 0.82, agri: 0.18 }[kind],
    agri_window: { flare: 0.08, incident: 0.08, wildfire: 0.1, agri: 0.9 }[kind],
    cluster_density: { flare: 0.3, incident: 0.2, wildfire: 0.45, agri: 0.8 }[kind],
    diurnal_variance: { flare: 0.12, incident: 0.45, wildfire: 0.7, agri: 0.5 }[kind],
  };
}

/** Per-cell persistence state across the generated feed (STA-aligned streaks). */
const cells = new Map<string, { lastDay: number; streak: number; total: number }>();

function noteCell(lat: number, lon: number, ts: number): { persist: number; det30: number } {
  const key = `${Math.round(lat / CELL)}:${Math.round(lon / CELL)}`;
  const day = Math.floor(ts / DAY);
  const c = cells.get(key) ?? { lastDay: -1, streak: 0, total: 0 };
  if (c.lastDay === day - 1) c.streak += 1;
  else if (c.lastDay !== day) c.streak = 1;
  c.lastDay = day;
  c.total += 1;
  cells.set(key, c);
  return { persist: c.streak, det30: Math.min(c.total, 30) };
}

function toEvent(raw: RawSim, seq: number): FireEvent {
  const { latitude: lat, longitude: lon } = raw;
  let best: Facility | null = null;
  let bestKm = Infinity;
  for (const f of FACILITIES) {
    const km = haversineKm(lat, lon, f.lat, f.lon);
    if (km < bestKm) { bestKm = km; best = f; }
  }
  const facility = bestKm <= 3.0 ? best : null;
  const feats: ClassFeatures = {
    frp: raw.frp, brightnessK: raw.bright_ti4,
    nightRatio: raw.daynight === 'N' ? 0.5 : 0.15,
    diurnalVariance: raw.diurnal_variance, persistDays: raw.persist_days,
    facilityDistanceKm: facility ? bestKm : null,
    facilityHazard: facility?.hazard ?? null,
    forestProxy: raw.forest_proxy, agriWindow: raw.agri_window,
    clusterDensity: raw.cluster_density,
  };
  const classification = classify(feats);
  if (facility && (classification.primary === 'industrial' || classification.primary === 'persistent')) {
    classification.subtype = facility.subtype;
  }
  return {
    id: `SIM-${String(seq).padStart(5, '0')}`,
    lat, lon, frp: raw.frp, brightnessK: raw.bright_ti4,
    confidence: raw.confidence, detectedAt: raw.acq_epoch_ms,
    satellite: raw.satellite, dayNight: raw.daynight,
    classification,
    persistence: assessPersistence(raw.persist_days, raw.det30),
    risk: scoreRisk(feats, classification.confidence),
    nearestFacilityId: facility?.id ?? null,
    facilityDistanceKm: facility ? Math.round(bestKm * 100) / 100 : null,
  };
}

/** 14-day deterministic history (chronic sources repeat daily in the same cell). */
export function simulateInitial(): { events: FireEvent[]; logs: LogLine[] } {
  const r = mulberry32(20260908);
  const now = Date.now();
  const events: FireEvent[] = [];
  let seq = 0;

  for (let day = 13; day >= 0; day--) {
    const ts = now - day * DAY;
    for (const f of FLARE) {
      const lat = f.lat + u(r, -0.002, 0.002);
      const lon = f.lon + u(r, -0.002, 0.002);
      const cell = noteCell(lat, lon, ts);
      events.push(toEvent(rawFor('flare', lat, lon, ts - Math.round(u(r, 0, 10_000_000)), cell.persist, cell.det30, r), ++seq));
    }
    const n = 6 + Math.round(r() * 6);
    for (let i = 0; i < n; i++) {
      const roll = r();
      if (roll < 0.15) {
        const f = FACILITIES[Math.floor(r() * FACILITIES.length)];
        const lat = f.lat + u(r, -0.05, 0.05);
        const lon = f.lon + u(r, -0.05, 0.05);
        const cell = noteCell(lat, lon, ts);
        events.push(toEvent(rawFor('incident', lat, lon, ts - Math.round(u(r, 0, 80_000_000)), cell.persist, cell.det30, r), ++seq));
      } else if (roll < 0.6) {
        const [la, lo, sp] = WLD[Math.floor(r() * WLD.length)];
        const lat = la + u(r, -sp, sp);
        const lon = lo + u(r, -sp, sp);
        const cell = noteCell(lat, lon, ts);
        events.push(toEvent(rawFor('wildfire', lat, lon, ts - Math.round(u(r, 0, 80_000_000)), cell.persist, cell.det30, r), ++seq));
      } else {
        const [la, lo, sp] = AGR[Math.floor(r() * AGR.length)];
        const lat = la + u(r, -sp, sp);
        const lon = lo + u(r, -sp, sp);
        const cell = noteCell(lat, lon, ts);
        events.push(toEvent(rawFor('agri', lat, lon, ts - Math.round(u(r, 0, 80_000_000)), cell.persist, cell.det30, r), ++seq));
      }
    }
  }
  events.sort((a, b) => a.detectedAt - b.detectedAt);
  const logs: LogLine[] = events.slice(-4).map((e) => ({
    ts: Date.now(), kind: 'ingest' as const,
    text: `seeded ${e.id} · ${e.classification.primary} · FRP ${e.frp} MW`,
  }));
  return { events, logs };
}

/** Live trickle: 1–3 fresh detections per tick (chronic cells continue their streaks). */
export function simulateLive(): { events: FireEvent[]; logs: LogLine[] } {
  const r = mulberry32(((Date.now() / 1000) | 0) ^ 0x5f37);
  const n = 1 + Math.floor(r() * 3);
  const events: FireEvent[] = [];
  for (let i = 0; i < n; i++) {
    const roll = r();
    let lat: number, lon: number, kind: 'flare' | 'incident' | 'wildfire' | 'agri';
    if (roll < 0.35) {
      const f = FLARE[Math.floor(r() * FLARE.length)];
      lat = f.lat + u(r, -0.002, 0.002); lon = f.lon + u(r, -0.002, 0.002); kind = 'flare';
    } else if (roll < 0.5) {
      const f = FACILITIES[Math.floor(r() * FACILITIES.length)];
      lat = f.lat + u(r, -0.05, 0.05); lon = f.lon + u(r, -0.05, 0.05); kind = 'incident';
    } else if (roll < 0.75) {
      const [la, lo, sp] = WLD[Math.floor(r() * WLD.length)];
      lat = la + u(r, -sp, sp); lon = lo + u(r, -sp, sp); kind = 'wildfire';
    } else {
      const [la, lo, sp] = AGR[Math.floor(r() * AGR.length)];
      lat = la + u(r, -sp, sp); lon = lo + u(r, -sp, sp); kind = 'agri';
    }
    const ts = Date.now();
    const cell = noteCell(lat, lon, ts);
    events.push(toEvent(rawFor(kind, lat, lon, ts, cell.persist, cell.det30, r), 90000 + (Date.now() % 9000) + i));
  }
  const logs: LogLine[] = events.slice(0, 1).map((e) => ({
    ts: Date.now(), kind: 'ingest' as const,
    text: `SIM · ${e.id} · ${e.classification.primary} · FRP ${e.frp} MW`,
  }));
  return { events, logs };
}