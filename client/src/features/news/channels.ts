/** Broadcast live-stream strip for the LIVE WIRE panel.
 *  Channel ids resolved/verified by `node scripts/check_news_channels.mjs`
 *  (run 2026-09-14, exit 0). Re-run the script to re-verify after any change. */
export interface NewsChannel {
  key: string;
  label: string;
  region: 'GLOBAL' | 'IN';
  ytChannelId: string;
}

export const NEWS_CHANNELS: NewsChannel[] = [
  { key: 'aje', label: 'AL JAZEERA', region: 'GLOBAL', ytChannelId: 'UCNye-wNBqNL5ZzHSJj3l8Bg' },
  { key: 'dw', label: 'DW', region: 'GLOBAL', ytChannelId: 'UCknLrEdhRCp1aegoMqRaCZg' },
  { key: 'cnbc', label: 'CNBC', region: 'GLOBAL', ytChannelId: 'UCvJJ_dzjViJCoLf5uKUTwoA' },
  { key: 'sky', label: 'SKY NEWS', region: 'GLOBAL', ytChannelId: 'UCoMdktPbSTixAyNGwb-UYkQ' },
  { key: 'wion', label: 'WION', region: 'IN', ytChannelId: 'UC_gUM8rL-Lrg6O3adPW9K1g' },
  { key: 'f24', label: 'FRANCE 24', region: 'GLOBAL', ytChannelId: 'UCCCPCZNChQdGa9EkATeye4g' },
];

export function embedUrl(ch: NewsChannel): string | null {
  if (!ch.ytChannelId) return null;
  return `https://www.youtube.com/embed/live_stream?channel=${ch.ytChannelId}&rel=0`;
}
