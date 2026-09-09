import { create } from 'zustand';
import { CLASS_META, MAX_EVENTS } from '@/config/constants';
import { simulateInitial, simulateLive } from '@/services/simulation/simulator';
import { FACILITIES } from '@/services/osm/facilitySeed';
import type { AlertItem, AlertStatus, Facility, FireEvent, Filters, LogLine } from '@/types/domain';

interface FireState {
  hydrated: boolean;
  paused: boolean;
  /** 'server' when the FastAPI feed is live; 'sim' for the local demo feed. */
  source: 'sim' | 'server';
  events: FireEvent[];
  facilities: Facility[];
  alerts: AlertItem[];
  logs: LogLine[];
  filters: Filters;
  selectedEventId: string | null;
  hydrate: () => void;
  tick: () => void;
  togglePause: () => void;
  select: (id: string | null) => void;
  setFilters: (patch: Partial<Filters>) => void;
  setAlertStatus: (id: string, status: AlertStatus) => void;
  raiseAlert: (eventId: string) => void;
  setSource: (s: 'sim' | 'server') => void;
  adoptServerEvents: (events: FireEvent[]) => void;
  /** Full handoff: replaces the local sim history with server truth. */
  setServerEvents: (events: FireEvent[]) => void;
}


const pushLogs = (logs: LogLine[], add: LogLine[]): LogLine[] => [...logs, ...add].slice(-80);
let alertSeq = 0;

export const useFireStore = create<FireState>()((set, get) => ({
  hydrated: false,
  paused: false,
  source: 'sim',
  events: [],
  facilities: FACILITIES,
  alerts: [],
  logs: [],
  filters: { classes: ['industrial', 'persistent', 'wildfire', 'agricultural'], minConfidence: 0, persistentOnly: false },
  selectedEventId: null,

  hydrate: () => {
    if (get().hydrated) return;
    const { events, logs } = simulateInitial();
    const alerts: AlertItem[] = events
      .filter((e) => e.risk.level === 'critical' && Date.now() - e.detectedAt < 86_400_000)
      .slice(-4)
      .map((e) => makeAlert(e));
    set({ hydrated: true, events, logs: pushLogs([], logs), alerts });
  },

  tick: () => {
    const s = get();
    // Server owns ingestion while connected — the sim must not pollute the feed.
    if (s.paused || !s.hydrated || s.source === 'server') return;
    const { events: fresh, logs } = simulateLive();
    if (fresh.length === 0 && logs.length === 0) return;

    const newAlerts = fresh.filter((e) => e.risk.level === 'high' || e.risk.level === 'critical').map(makeAlert);
    const alertLogs: LogLine[] = newAlerts.map((a) => ({ ts: a.createdAt, kind: 'alert', text: `ALERT ${a.level.toUpperCase()} · ${a.message}` }));
    const merged = [...s.events, ...fresh].sort((a, b) => a.detectedAt - b.detectedAt).slice(-MAX_EVENTS);
    set({ events: merged, logs: pushLogs(s.logs, [...logs, ...alertLogs]), alerts: [...s.alerts, ...newAlerts].slice(-60) });
  },

  togglePause: () => set((s) => ({ paused: !s.paused })),
  select: (id) => set({ selectedEventId: id }),
  setSource: (source) => set((s) => ({ source, paused: source === 'server' ? false : s.paused })),
  adoptServerEvents: (incoming) =>
    set((s) => {
      const ids = new Set(s.events.map((e) => e.id));
      const fresh = incoming.filter((e) => !ids.has(e.id));
      if (fresh.length === 0) return {};
      return { events: [...s.events, ...fresh].sort((a, b) => a.detectedAt - b.detectedAt).slice(-MAX_EVENTS) };
    }),
  setServerEvents: (incoming) =>
    set((s) => ({
      events: [...incoming].sort((a, b) => a.detectedAt - b.detectedAt).slice(-MAX_EVENTS),
      logs: pushLogs(s.logs, [{ ts: Date.now(), kind: 'system', text: `Server feed connected · ${incoming.length} events adopted (sim history replaced)` }]),
    })),
  setFilters: (patch) => set((s) => ({ filters: { ...s.filters, ...patch } })),
  setAlertStatus: (id, status) =>
    set((s) => ({
      alerts: s.alerts.map((a) => (a.id === id ? { ...a, status } : a)),
      logs: pushLogs(s.logs, [{ ts: Date.now(), kind: 'system', text: `Alert ${id} → ${status}` }]),
    })),
  raiseAlert: (eventId) => {
    const e = get().events.find((ev) => ev.id === eventId);
    if (!e) return;
    const alert = makeAlert(e);
    set((s) => ({
      alerts: [...s.alerts, alert],
      logs: pushLogs(s.logs, [{ ts: alert.createdAt, kind: 'alert', text: `ALERT raised manually · ${alert.message}` }]),
    }));
  },
}));

function makeAlert(e: FireEvent): AlertItem {
  const meta = CLASS_META[e.classification.primary];
  return {
    id: `AL-${String(++alertSeq).padStart(3, '0')}`,
    eventId: e.id,
    level: e.risk.level,
    message: `${meta.label}${e.classification.subtype ? ` · ${e.classification.subtype}` : ''} · risk ${e.risk.score}`,
    createdAt: Date.now(),
    status: 'new',
  };
}
