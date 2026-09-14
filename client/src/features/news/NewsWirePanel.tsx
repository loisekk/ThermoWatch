import { useEffect, useMemo } from 'react';
import { Radio } from 'lucide-react';
import { Panel } from '@/components/ui/Panel';
import { Badge } from '@/components/ui/Badge';
import { useNewsStore, startNewsPolling } from '@/store/useNewsStore';
import { useFireStore } from '@/store/useFireStore';
import { buildWireBrief } from './wireBrief';
import { GRADE_GLYPH, GRADE_LABEL } from './newsCorrelate';
import { NEWS_CHANNELS, embedUrl, type NewsChannel } from './channels';
import type { NewsItem } from './types';

function ageH(iso: string | null): string {
  if (!iso) return '--';
  const h = (Date.now() - Date.parse(iso)) / 3.6e6;
  return h < 1 ? `${Math.max(1, Math.round(h * 60))}m` : `${h.toFixed(1)}h`;
}

const STATUS_COLOR: Record<string, string> = {
  ok: '#3FB950', stale: '#FFB800', err: '#FF4444',
};

/** LIVE WIRE · open-source news corroboration (Session 23).
 *  Unverified wire + optional broadcast streams + rule-based brief.
 *  Corroboration is a distance/time signal for analysts, never confirmation. */
export function NewsWirePanel() {
  const { feed, status, error, tvOn, tvChannel, setTv, sync, lastSyncAt } = useNewsStore();
  const select = useFireStore((s) => s.select);
  useEffect(() => startNewsPolling(), []);
  const brief = useMemo(() => buildWireBrief(feed?.items ?? []), [feed]);
  const ch: NewsChannel | undefined = NEWS_CHANNELS.find((c) => c.key === tvChannel);
  const url = ch ? embedUrl(ch) : null;

  const openItem = (it: NewsItem) => {
    if (it.nearby_event_ids[0]) select(it.nearby_event_ids[0]);
  };

  return (
    <Panel
      title="live wire · open-source corroboration"
      icon={<Radio />}
      actions={(
        <button
          onClick={() => void sync()}
          className="mono rounded-sm border border-edge px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-mute hover:border-ember hover:text-ember"
        >
          {status === 'loading' ? 'sync…' : 'sync'}
        </button>
      )}
    >
      {/* provider health row — visible outage, never hidden */}
      <div className="mb-2 flex flex-wrap gap-1">
        {(feed?.providers ?? []).map((p) => (
          <Badge key={p.provider} color={p.ok ? (p.stale ? STATUS_COLOR.stale : STATUS_COLOR.ok) : STATUS_COLOR.err}>
            {p.provider} {p.ok ? (p.stale ? 'stale' : 'ok') : 'down'} {ageH(p.last_sync_at)}
          </Badge>
        ))}
        {status === 'error' && <Badge color={STATUS_COLOR.err}>wire unreachable · {error}</Badge>}
        {status !== 'error' && !feed && <Badge color="#8CA0B3">syncing…</Badge>}
      </div>

      {/* broadcast strip — lazy iframe, default OFF; wire list is the offline-safe surface */}
      <div className="mb-2 rounded-sm border border-edge p-2">
        <div className="mono mb-1.5 text-[9px] uppercase tracking-widest text-dim">broadcast strip (default off)</div>
        <div className="flex flex-wrap gap-1">
          <button onClick={() => setTv(null)}
            className={`mono rounded-sm border px-1.5 py-0.5 text-[9px] uppercase tracking-wider ${!tvOn ? 'border-ember text-ember' : 'border-edge text-dim hover:text-ink'}`}>
            off
          </button>
          {NEWS_CHANNELS.map((c) => (
            <button key={c.key} disabled={!c.ytChannelId}
              title={c.ytChannelId ? c.label : 'channel id pending verification — run scripts/check_news_channels.mjs'}
              onClick={() => setTv(c.key)}
              className={`mono rounded-sm border px-1.5 py-0.5 text-[9px] uppercase tracking-wider disabled:opacity-40 ${tvOn && tvChannel === c.key ? 'border-ember text-ember' : 'border-edge text-dim hover:text-ink'}`}>
              {c.label}
            </button>
          ))}
        </div>
        {tvOn && url && (
          <div className="mt-1.5 aspect-video overflow-hidden rounded-sm bg-void">
            <iframe src={url} title={`Live stream: ${ch?.label}`} allow="autoplay; encrypted-media"
              referrerPolicy="strict-origin-when-cross-origin" className="h-full w-full" />
          </div>
        )}
        {tvOn && !url && <div className="mono mt-1 text-[9px] text-amber">channel id pending · run scripts/check_news_channels.mjs</div>}
        <div className="mono mt-1 text-[8px] leading-relaxed text-dim">
          streams © respective broadcasters via YouTube · availability = broadcaster + network · the wire list below is the offline-safe surface
        </div>
      </div>

      {/* rule-based brief (no LLM) */}
      <div className="mb-2 rounded-sm border border-edge p-2">
        <div className="mono mb-1 text-[9px] uppercase tracking-widest text-dim">wire brief · rule-based (no llm)</div>
        <div className="text-[11px] font-medium text-ink">{brief.headline}</div>
        {brief.bullets.map((b, i) => <div key={i} className="mt-0.5 text-[10px] leading-snug text-mute">▸ {b}</div>)}
        <div className="mono mt-1 text-[9px] text-dim">
          {Object.entries(brief.counts).map(([k, v]) => `${k}: ${v}`).join(' · ') || 'no categories'}
        </div>
        <div className="mono text-[9px] text-dim">
          {brief.correlated} corroborated · newest source {brief.newest_source_age_h ?? '--'} h old
          {lastSyncAt ? ` · synced ${ageH(feed?.generated_at ?? null)} ago` : ''}
        </div>
      </div>

      {/* item list */}
      <div className="max-h-[38vh] space-y-0.5 overflow-y-auto">
        {(feed?.items ?? []).map((it) => (
          <button key={it.id} onClick={() => openItem(it)}
            className="block w-full rounded-sm px-1.5 py-1 text-left hover:bg-panel2">
            <div className="truncate text-[11px] text-ink">
              <span className="text-amber">{GRADE_GLYPH[it.grade]}</span> {it.title}
            </div>
            <div className="mono text-[9px] text-dim">
              {ageH(it.published_at)} · {it.provider} · {it.source_domain ?? it.country ?? '--'} · {GRADE_LABEL[it.grade]}
              {it.nearby_event_ids[0] ? ` · ↔ ${it.nearby_event_ids[0]} ${it.correlation_km} km` : ''}
            </div>
          </button>
        ))}
        {(feed?.items.length ?? 0) === 0 && status !== 'loading' && (
          <div className="mono px-1.5 py-2 text-[10px] text-dim">no wire items in 24 h window</div>
        )}
      </div>
      <div className="mono mt-2 border-t border-edge pt-1.5 text-[8px] leading-relaxed text-dim">
        unverified open-source reporting · near-real-time wire (provider latency 15 min–6 h) · corroboration for analysts, not confirmation
      </div>
    </Panel>
  );
}

