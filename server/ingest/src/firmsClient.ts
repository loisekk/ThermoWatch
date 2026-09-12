import { cfg } from './config';

export interface FirmsRaw {
  latitude: number; longitude: number; frp: number; bright_ti4: number;
  confidence: number; satellite: string; daynight: 'D' | 'N'; acq_date: string; acq_time: string;
}

/** NASA FIRMS area CSV: {KEY}/{SOURCE}/{bbox}/{days_back 1..5}/{YYYY-MM-DD}.
 *  Rate limit: 100 req/h per key — caller throttles (POLL_MS >= 900000). */
function areaCsvUrl(source: string, dayEnd: string): string {
  return `https://firms.modaps.eosdis.nasa.gov/api/area/csv/${cfg.firmsKey}/${source}/${cfg.bbox}/5/${dayEnd}`;
}

const iso = (d: Date) => d.toISOString().slice(0, 10);

/** Resolve the newest date the FIRMS NRT archive actually serves (it can lag the
 *  wall clock). Probe ladder: yesterday → -8 d → -15 d; ≤3 requests per boot. */
export async function findDayEnd(): Promise<string> {
  for (const back of [1, 8, 15]) {
    const dayEnd = iso(new Date(Date.now() - back * 86_400_000));
    try {
      const res = await fetch(areaCsvUrl('VIIRS_SNPP_NRT', dayEnd));
      const text = await res.text();
      if (res.ok && text.split('\n').length > 1) return dayEnd;
    } catch { /* try the next step back */ }
  }
  return iso(new Date(Date.now() - 8 * 86_400_000));
}

export async function fetchFirms(source: 'VIIRS_SNPP_NRT' | 'MODIS_NRT', dayEnd: string): Promise<FirmsRaw[]> {
  const res = await fetch(areaCsvUrl(source, dayEnd));
  if (!res.ok) throw new Error(`FIRMS ${res.status}`);
  const text = (await res.text()).trim();
  const lines = text.split('\n');
  const head = lines[0];
  if (!head || lines.length < 2) return [];
  const cols = head.split(',');
  return lines.slice(1).map((r) => {
    const v = r.split(',');
    const o = Object.fromEntries(cols.map((c, i) => [c, v[i]])) as Record<string, string>;
    return {
      latitude: Number(o.latitude), longitude: Number(o.longitude), frp: Number(o.frp),
      bright_ti4: Number(o.bright_ti4), confidence: Number(o.confidence),
      satellite: o.satellite, daynight: o.daynight === 'N' ? 'N' : 'D',
      acq_date: o.acq_date, acq_time: o.acq_time,
    };
  });
}

export const toEpochMs = (r: FirmsRaw): number =>
  Date.parse(`${r.acq_date}T${r.acq_time.slice(0, 2)}:${r.acq_time.slice(2, 4)}:00Z`) || Date.now();
