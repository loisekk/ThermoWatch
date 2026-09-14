/** Client-side news↔event correlation (panel-local re-ranking).
 *  The server already annotates items with the nearest FIRMS event; this module
 *  re-ranks/verifies against a chosen anchor event and is unit-tested pure. */
import { haversineKm } from '@/lib/geo/distance';
import type { CorrelatedNews, NewsItem } from './types';

export interface NewsAnchor {
  lat: number;
  lon: number;
  atMs: number | null;
}

/** Grade + distance + dt vs an anchor event. Inclusive bounds: <= 75 km, <= 72 h. */
export function correlateNews(items: NewsItem[], anchor: NewsAnchor,
                              maxKm = 75, maxHours = 72): CorrelatedNews[] {
  const out: CorrelatedNews[] = [];
  for (const it of items) {
    if (it.lat == null || it.lon == null) continue;
    const km = haversineKm(anchor.lat, anchor.lon, it.lat, it.lon);
    if (km > maxKm) continue;
    let dt = 0;
    if (anchor.atMs != null && it.published_at) {
      dt = Math.abs(Date.parse(it.published_at) - anchor.atMs) / 3.6e6;
      if (dt > maxHours) continue;
    }
    out.push({ ...it, distance_km: Math.round(km * 10) / 10, dt_hours: Math.round(dt * 10) / 10 });
  }
  return out.sort((a, b) => a.distance_km - b.distance_km);
}

export const GRADE_LABEL: Record<NewsItem['grade'], string> = {
  event: 'event (EONET/GDACS)',
  'geo-mention': 'location mention (GDELT)',
  'article-country': 'country-level article',
};

export const GRADE_GLYPH: Record<NewsItem['grade'], string> = {
  event: '◆',
  'geo-mention': '◇',
  'article-country': '·',
};
