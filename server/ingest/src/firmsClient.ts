import { cfg } from './config';

export interface FirmsRaw {
  latitude: number; longitude: number; frp: number; bright_ti4: number;
  confidence: number; satellite: string; daynight: 'D' | 'N'; acq_date: string; acq_time: string;
}

/** NASA FIRMS NRT CSV (area=3 India). Rate limit: 100 req/h per key — caller throttles. */
export async function fetchFirms(source: 'VIIRS_SNPP_NRT' | 'MODIS_NRT'): Promise<FirmsRaw[]> {
  const url = `https://firms.modaps.eosdis.nasa.gov/api/area/csv/${cfg.firmsKey}/${source}/${cfg.areaCode}/1`;
  const res = await fetch(url);
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
