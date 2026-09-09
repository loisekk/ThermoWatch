import { api } from '@/services/api/client';

/** Tools the LLM agent may call — all execute against OUR FastAPI, key never leaves browser. */
export const TOOL_DEFS = [
  { type: 'function', function: { name: 'tw_query_events', description: 'Query classified fire events', parameters: { type: 'object', properties: { window_hours: { type: 'number' }, classes: { type: 'string', description: 'csv: industrial,persistent,wildfire,agricultural' }, min_risk: { type: 'number' } }, required: [] } } },
  { type: 'function', function: { name: 'tw_kpis', description: 'Pan-India KPI snapshot (24h)', parameters: { type: 'object', properties: {} } } },
  { type: 'function', function: { name: 'tw_run_model', description: 'Run the fire classification ML model on explicit parameters', parameters: { type: 'object', properties: { frp: { type: 'number' }, persist_days: { type: 'number' }, facility_subtype: { type: 'string' }, include_spread: { type: 'boolean' } }, required: ['frp'] } } },
  { type: 'function', function: { name: 'tw_event_dossier', description: 'Full dossier for one event id', parameters: { type: 'object', properties: { event_id: { type: 'string' } }, required: ['event_id'] } } },
] as const;

export async function executeTool(name: string, args: Record<string, unknown>): Promise<string> {
  try {
    switch (name) {
      case 'tw_query_events': {
        const q = new URLSearchParams({ window_hours: String(args.window_hours ?? 24) });
        if (args.classes) q.set('classes', String(args.classes));
        if (args.min_risk) q.set('min_risk', String(args.min_risk));
        const ev = await api.get<unknown[]>(`/api/v1/events?${q}`);
        return JSON.stringify(ev.slice(0, 25));
      }
      case 'tw_kpis': return JSON.stringify(await api.get('/api/v1/stats/kpis'));
      case 'tw_run_model': return JSON.stringify(await api.post('/api/v1/predict', { frp: 120, ...args }));
      case 'tw_event_dossier': return JSON.stringify(await api.get(`/api/v1/events/${String(args.event_id)}`));
      default: return JSON.stringify({ error: `unknown tool ${name}` });
    }
  } catch (e) {
    return JSON.stringify({ error: (e as Error).message });
  }
}
