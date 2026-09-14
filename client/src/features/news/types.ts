/** LIVE WIRE domain types (mirror of the server /api/v1/news contract). */

export type NewsProvider = 'gdelt-doc' | 'gdelt-geo' | 'eonet' | 'gdacs';
export type NewsGrade = 'event' | 'geo-mention' | 'article-country';

export interface NewsItem {
  id: string;
  provider: NewsProvider;
  grade: NewsGrade;
  title: string;
  url: string;
  published_at: string | null;
  lat: number | null;
  lon: number | null;
  country: string | null;
  source_domain: string | null;
  categories: string[];
  matched_terms: string[];
  /** Server-side corroboration: nearest FIRMS event within 75 km / 72 h. */
  nearby_event_ids: string[];
  correlation_km: number | null;
  correlation_dt_h: number | null;
}

export interface NewsProviderStatus {
  provider: NewsProvider;
  ok: boolean;
  stale: boolean;
  last_sync_at: string | null;
  items: number;
  latency_ms: number;
  error?: string | null;
}

export interface NewsFeed {
  generated_at: string;
  ttl_s: number;
  window_hours: number;
  providers: NewsProviderStatus[];
  items: NewsItem[];
}

/** Client-side correlate result vs an anchor event (panel-local re-ranking). */
export interface CorrelatedNews extends NewsItem {
  distance_km: number;
  dt_hours: number;
}
