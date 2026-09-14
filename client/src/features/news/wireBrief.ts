/** Rule-based wire digest (NO LLM) — the same function backs the agent's
 *  tw_summarize_wire tool. Labelled as rule-based wherever it is shown. */
import type { CorrelatedNews, NewsItem } from './types';

export interface WireBrief {
  headline: string;
  bullets: string[];
  counts: Record<string, number>;
  correlated: number;
  newest_source_age_h: number | null;
  generated_at: string;
}

export function buildWireBrief(items: NewsItem[], corr: CorrelatedNews[] = [],
                               now: Date = new Date()): WireBrief {
  const counts: Record<string, number> = {};
  for (const it of items) for (const c of it.categories) counts[c] = (counts[c] ?? 0) + 1;
  const ages = items
    .filter((i) => i.published_at)
    .map((i) => (now.getTime() - Date.parse(i.published_at as string)) / 3.6e6)
    .filter((h) => Number.isFinite(h));
  const newest = ages.length ? Math.min(...ages) : null;
  const top = corr[0] ?? items[0];
  const headline = top ? top.title : 'No wire items in window';
  const corrIds = new Set(corr.map((c) => c.id));
  const bullets = [...corr, ...items.filter((i) => !corrIds.has(i.id))]
    .slice(0, 3)
    .map((i) => `[${i.provider}] ${i.title}`);
  return {
    headline,
    bullets,
    counts,
    correlated: corr.length,
    newest_source_age_h: newest == null ? null : Math.round(newest * 10) / 10,
    generated_at: now.toISOString(),
  };
}
