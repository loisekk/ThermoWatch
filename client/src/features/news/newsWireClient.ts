/** LIVE WIRE API surface — reuses the shared api helper (12 s timeout built in). */
import { api } from '@/services/api/client';
import type { NewsFeed, NewsProviderStatus } from './types';

export async function fetchNewsFeed(windowHours = 24, limit = 120): Promise<NewsFeed> {
  return api.get<NewsFeed>(
    `/api/v1/news/feed?window_hours=${windowHours}&limit=${limit}`,
  );
}

export async function fetchNewsProviders(): Promise<NewsProviderStatus[]> {
  const r = await api.get<{ providers: NewsProviderStatus[] }>('/api/v1/news/providers');
  return r.providers;
}
