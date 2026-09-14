import { useMemo } from 'react';
import { Crosshair, Gauge, X } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Sparkline } from '@/components/ui/charts/Sparkline';
import { CLASS_META, CLASS_ORDER, RISK_META, SUBTYPE_LABEL } from '@/config/constants';
import { haversineKm } from '@/lib/geo/distance';
import { hashString, mulberry32 } from '@/lib/random/mulberry';
import { coordLabel, fmtKm, fmtMW, relTime, utcStamp } from '@/lib/utils/format';
import { useFireStore } from '@/store/useFireStore';
import { panelWidth, useUIStore } from '@/store/useUIStore';
import { ResizeHandle } from '@/components/ui/ResizeHandle';
import { useSceneContextStore } from '@/store/useSceneContextStore';
import { suggestFireType } from '@/features/context/suggestFireType';
import { ResponsePlan } from '@/features/response/ResponsePlan';

/** Slide-over incident dossier for the selected detection (resizable since S23). */
export function EventDrawer() {
  const selectedId = useFireStore((s) => s.selectedEventId);
  const events = useFireStore((s) => s.events);
  const facilities = useFireStore((s) => s.facilities);
  const select = useFireStore((s) => s.select);
  const raiseAlert = useFireStore((s) => s.raiseAlert);
  const setSceneEventId = useUIStore((s) => s.setSceneEventId);
  const width = useUIStore((s) => panelWidth(s.panelSizes, 'eventDrawer'));
  const setPanelSize = useUIStore((s) => s.setPanelSize);
  const resetPanelSize = useUIStore((s) => s.resetPanelSize);
  const sceneCtx = useSceneContextStore((s) => s.eventId === selectedId ? s.context : null);
  const sceneNearest = useSceneContextStore((s) => s.eventId === selectedId ? s.nearest : null);
  const e = events.find((x) => x.id === selectedId);

  const nearest = useMemo(() => {
    if (!e) return null;
    let best = null as null | { name: string; subtype: keyof typeof SUBTYPE_LABEL; hazard: string; km: number };
    for (const f of facilities) {
      const km = haversineKm(e.lat, e.lon, f.lat, f.lon);
      if (!best || km < best.km) best = { name: f.name, subtype: f.subtype, hazard: f.hazard, km };
    }
    return best;
  }, [e, facilities]);

  const series = useMemo(() => {
    if (!e) return [];
    const r = mulberry32(hashString(e.id));
    const base = e.frp;
    return Array.from({ length: 12 }, (_, i) => base * (0.6 + 0.5 * r()) * (e.persistence.regime === 'persistent' ? 1 : 1 - i * 0.04));
  }, [e]);

  if (!e) return null;
  const meta = CLASS_META[e.classification.primary];

  return (
    <div role="dialog" aria-label={`Incident dossier ${e.id}`} className="drawer-in fixed bottom-7 right-0 top-12 z-30 flex flex-col gap-2.5 overflow-y-auto border-l border-edge bg-panel/95 p-3 backdrop-blur" style={{ width }}>
      <ResizeHandle edge="left" width={width} min={360} max={720}
        onChange={(w) => setPanelSize('eventDrawer', w)}
        onReset={() => resetPanelSize('eventDrawer')}
        label="Resize dossier (drag, arrow keys, double-click to reset)" />
      <header className="flex items-start justify-between gap-2">
        <div>
          <div className="mono text-[10px] text-dim">{e.id} · {utcStamp(e.detectedAt)} · {relTime(e.detectedAt)}</div>
          <h2 className="mt-1 text-base font-bold" style={{ color: meta.color }}>{meta.label}</h2>
          <div className="mt-1 flex flex-wrap gap-1">
            {e.classification.subtype && <Badge color={meta.color}>{SUBTYPE_LABEL[e.classification.subtype]}</Badge>}
            <Badge color={RISK_META[e.risk.level].color}>risk {e.risk.level}</Badge>
            <Badge color="#8CA0B3">{e.persistence.regime}</Badge>
          </div>
        </div>
        <button onClick={() => select(null)} aria-label="Close dossier" className="rounded p-1 text-mute hover:text-ink"><X className="h-4 w-4" /></button>
      </header>

      <section className="rounded-md border border-edge bg-panel2/60 p-2.5">
        <div className="mono mb-2 text-[9px] uppercase tracking-widest text-dim">ensemble scores</div>
        <ul className="space-y-1.5">
          {CLASS_ORDER.map((c) => (
            <li key={c} className="flex items-center gap-2">
              <span className="mono w-9 text-[9px] text-mute">{CLASS_META[c].short}</span>
              <div className="h-1.5 flex-1 rounded-full bg-edge">
                <div className="h-1.5 rounded-full" style={{ width: `${e.classification.scores[c] * 100}%`, background: CLASS_META[c].color }} />
              </div>
              <span className="mono w-9 text-right text-[9px] text-ink">{Math.round(e.classification.scores[c] * 100)}%</span>
            </li>
          ))}
        </ul>
        <div className="mono mt-2 text-[9px] text-dim">detection confidence {e.classification.confidence}% · {e.satellite} · {e.dayNight === 'N' ? 'night' : 'day'} pass</div>
      </section>

      <section className="rounded-md border border-edge bg-panel2/60 p-2.5">
        <div className="mono mb-1 flex justify-between text-[9px] uppercase tracking-widest text-dim">
          <span>frp trend</span><span>{fmtMW(e.frp)} · {e.brightnessK} K</span>
        </div>
        <Sparkline values={series} color={meta.color} width={352} height={44} />
        <div className="mono mt-1 flex justify-between text-[9px] text-dim">
          <span>persistence {e.persistence.consecutiveDays} d · {e.persistence.detections30d} det/30d</span>
          <span>{coordLabel(e.lat, e.lon)}</span>
        </div>
      </section>

      <section className="rounded-md border border-edge bg-panel2/60 p-2.5">
        <div className="mono mb-2 flex items-center gap-1.5 text-[9px] uppercase tracking-widest text-dim"><Gauge className="h-3 w-3" /> risk drivers · {e.risk.score}/100</div>
        <div className="mb-2 h-1.5 rounded-full bg-edge">
          <div className="h-1.5 rounded-full" style={{ width: `${e.risk.score}%`, background: RISK_META[e.risk.level].color }} />
        </div>
        <ul className="space-y-1 text-[10px] text-mute">{e.risk.drivers.map((d) => <li key={d}>· {d}</li>)}</ul>
      </section>

      {nearest && (
        <section className="rounded-md border border-edge bg-panel2/60 p-2.5">
          <div className="mono mb-1.5 flex items-center gap-1.5 text-[9px] uppercase tracking-widest text-dim"><Crosshair className="h-3 w-3" /> nearest OSM asset</div>
          <div className="text-[11px] font-medium text-ink">{nearest.name}</div>
          <div className="mono mt-0.5 text-[9px] text-mute">{SUBTYPE_LABEL[nearest.subtype]} · hazard {nearest.hazard} · {fmtKm(nearest.km)}</div>
        </section>
      )}

      <section className="rounded-md border border-edge bg-panel2/60 p-2.5">
        <div className="mono mb-1.5 text-[9px] uppercase tracking-widest text-dim">response recommendation · model, not orders</div>
        <ResponsePlan event={e} />
      </section>

      {sceneCtx && (
        <section className="rounded-md border border-edge bg-panel2/60 p-2.5">
          <div className="mono mb-1.5 text-[9px] uppercase tracking-widest text-dim">scene context provenance</div>
          {sceneCtx.source === 'osm-overpass' ? (
            <>
              <div className="text-[10px] text-mute">source: OSM Overpass · radius {sceneCtx.radius_m} m · snapshot {sceneCtx.snapshot_at.slice(0, 16).replace('T', ' ')}Z · {sceneCtx.attribution}</div>
              <div className="mono mt-1 text-[9px] text-dim">
                buildings {sceneCtx.buildings.length} · trees {sceneCtx.trees.length} · roads {sceneCtx.roads.length} · water {sceneCtx.water.length} · wood {sceneCtx.wood.length}
              </div>
              {(sceneCtx.buildings.length > 0) && (
                <div className="mono mt-0.5 text-[9px] text-dim">
                  height provenance: {Math.round(100 * (sceneCtx.buildings.filter((b) => b.height_source !== 'estimated').length) / sceneCtx.buildings.length)}% tagged / {100 - Math.round(100 * sceneCtx.buildings.filter((b) => b.height_source !== 'estimated').length / sceneCtx.buildings.length)}% estimated
                </div>
              )}
              {sceneNearest && (
                <div className="mono mt-0.5 text-[9px] text-amber">
                  top-FRP hotspot ≈{sceneNearest.m.toFixed(0)} m from OSM way {sceneNearest.id}… ({sceneNearest.kind})
                </div>
              )}
              <div className="mono mt-1 text-[8px] leading-relaxed text-dim">OSM is community-mapped; coverage varies by region.</div>
            </>
          ) : (
            <div className="text-[10px] text-mute">OSM unreachable — the 3D scene renders labelled SCHEMATIC context (never invented).</div>
          )}
        </section>
      )}

      <section className="rounded-md border border-edge bg-panel2/60 p-2.5">
        <div className="mono mb-1.5 text-[9px] uppercase tracking-widest text-dim">multi-source validation</div>
        <div className="flex gap-3">
          <a className="mono text-[10px] text-ember underline-offset-2 hover:underline" target="_blank" rel="noreferrer"
            href={`https://apps.sentinel-hub.com/eo-browser/?zoom=12&lat=${e.lat.toFixed(4)}&lng=${e.lon.toFixed(4)}`}>
            Sentinel-2 imagery (10 m)
          </a>
          <a className="mono text-[10px] text-ember underline-offset-2 hover:underline" target="_blank" rel="noreferrer"
            href="https://firms.modaps.eosdis.nasa.gov/map/">NASA FIRMS map</a>
        </div>
        <div className="mono mt-1 text-[9px] text-dim">labels are OSM-tag proxies — cross-check imagery before field action</div>
      </section>

      <section className="rounded-md border border-edge bg-panel2/60 p-2.5">
        <div className="mono mb-1.5 text-[9px] uppercase tracking-widest text-dim">context hypotheses (ranked, evidence-backed)</div>
        <ul className="space-y-2">
          {suggestFireType(e, facilities).map((h, i) => (
            <li key={h.label}>
              <div className="flex items-center justify-between gap-2">
                <span className={`text-[11px] font-medium ${i === 0 ? 'text-ink' : 'text-mute'}`}>{i + 1}. {h.label}</span>
                <span className="mono text-[9px] text-dim">w={h.weight.toFixed(2)}</span>
              </div>
              <ul className="mt-0.5 space-y-0.5 pl-3 text-[9px] text-dim">
                {h.evidence.map((evd) => <li key={evd}>· {evd}</li>)}
              </ul>
            </li>
          ))}
        </ul>
        <div className="mono mt-1.5 text-[8px] text-dim">hypotheses ≠ certainty — validate with Sentinel-2 / field report before action</div>
      </section>

      <div className="flex gap-2">
        <button onClick={() => setSceneEventId(e.id)} className="mono flex-1 rounded-md border border-edge px-3 py-2 text-[11px] font-semibold uppercase tracking-widest text-mute transition-colors hover:border-ember/50 hover:text-ember">
          view 3D scene
        </button>
        <button onClick={() => raiseAlert(e.id)} className="mono flex-1 rounded-md border border-ember/50 bg-ember/10 px-3 py-2 text-[11px] font-semibold uppercase tracking-widest text-ember transition-colors hover:bg-ember/20">
          raise verification alert
        </button>
      </div>
    </div>
  );
}
