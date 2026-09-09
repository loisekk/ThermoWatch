import type { FirmsRecord } from './firmsTypes';

/**
 * Live NASA FIRMS NRT client (area code 3 = India).
 * Unused by the demo feed — activated when VITE_FIRMS_API_KEY is present.
 * NOTE: FIRMS latency is 3-6h; the UI must always say "near-real-time".
 */
const BASE = 'https://firms.modaps.eosdis.nasa.gov/api/area/csv';
const INDIA_AREA = '3';

export async function fetchFirmsIndia(
  apiKey: string,
  source: 'VIIRS_SNPP_NRT' | 'MODIS_NRT',
  days = 1,
): Promise<FirmsRecord[]> {
  const url = `${BASE}/${apiKey}/${source}/${INDIA_AREA}/${days}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`FIRMS API ${res.status}`);
  const text = await res.text();
  return parseCsv(text);
}

function parseCsv(csv: string): FirmsRecord[] {
  const [header, ...rows] = csv.trim().split('\n');
  if (!header) return [];
  const cols = header.split(',');
  return rows.map((row) => {
    const vals = row.split(',');
    const rec = Object.fromEntries(cols.map((c, i) => [c, vals[i]])) as unknown as Record<keyof FirmsRecord, string>;
    return {
      latitude: Number(rec.latitude),
      longitude: Number(rec.longitude),
      bright_ti4: Number(rec.bright_ti4),
      scan: Number(rec.scan),
      track: Number(rec.track),
      acq_date: rec.acq_date,
      acq_time: rec.acq_time,
      satellite: rec.satellite,
      instrument: rec.instrument,
      confidence: Number(rec.confidence),
      frp: Number(rec.frp),
      daynight: rec.daynight === 'N' ? 'N' : 'D',
      type: Number(rec.type),
    };
  });
}
