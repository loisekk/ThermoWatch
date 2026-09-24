/**
 * Animated activity-state glyph — state changes catch the eye without
 * reading; always paired with the text state beside it (never color or
 * motion alone). Styles live in styles/globals.css (.tw-glyph-*) and honor
 * prefers-reduced-motion there.
 */
import type { ActivityState } from '@/services/api/v2Types';

const GLYPHS: Record<string, { cls: string; icon: string }> = {
  acute: { cls: 'tw-glyph-acute', icon: '⚡' },
  persistent: { cls: 'tw-glyph-persistent', icon: '●' },
  recurring: { cls: 'tw-glyph-recurring', icon: '↻' },
  changing: { cls: 'tw-glyph-changing', icon: '▲' },
  insufficient_history: { cls: 'tw-glyph-insufficient', icon: '?' },
  unknown: { cls: 'tw-glyph-insufficient', icon: '—' },
};

export function ActivityGlyph({ state }: { state: ActivityState }) {
  const g = GLYPHS[state] ?? GLYPHS.unknown;
  return (
    <span className={`tw-glyph ${g.cls}`} role="img" aria-label={`activity: ${state}`}>
      {g.icon}
    </span>
  );
}
