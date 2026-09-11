import { useEffect, useMemo, useState } from 'react';
import { X, Factory, ExternalLink } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Sparkline } from '@/components/ui/charts/Sparkline';
import { CLASS_META, SUBTYPE_LABEL } from '@/config/constants';
import { NBC_HAZARD, OSM_TAGS, overpassTurboUrl } from '@/config/regulatory';
import { useFireStore } from '@/store/useFireStore';
import { api } from '@/services/api/client';
import { haversineKm } from '@/lib/geo/distance';
import { FacilityIso } from './FacilityIso';

const DAY = 86_400_000;

interface Resp { nearest_stations: { name: string; distance_km: number; eta_min: number }[]; evacuation_radius_m: number }

export function FacilityDrawer() {
  const id = useFireStore((s) => s.selectedFacilityId);
  const selectFacility = useFireStore((s) => s.selectFacility);
  const facilities = useFireStore((s) => s.facilities);
  const events = useFireStore((s) => s.events);
  const f = facilities.find((x) => x.id === id) ?? null;
  const [resp, setResp] = useState<Resp | null>(null);

  const stats = useMemo(() => {
    if (!f) return null;
    const near = events.filter((e) => haversineKm(e.lat, e.lon, f.lat, f.lon) <= 3);
    const now = Date.now();
    const in24 = near.filter((e) => now - e.detectedAt <= DAY).length;
    const in7 = near.filter((e) => now - e.detectedAt <= 7 * DAY).length;
    const persist = near.reduce((a, e) => Math.max(a, e.persistence.consecutiveDays), 0);
    const series = Array.from({ length: 14 }, (_, i) =>
      near.filter((e) => { const d = Math.floor((now - e.detectedAt) / DAY); return d === 13 - i; }).length);
    return { total: near.length, in24, in7, persist, series };
  }, [f, events]);

  useEffect(() => {
    if (!f) { setResp(null); return; }
    api.post<Resp>('/api/v1/response/recommend', { lat: f.lat, lon: f.lon, fire_class: 'industrial', hazard: f.hazard })
      .then(setResp).catch(() => setResp(null));
  }, [f]);

  if (!f) return null;
  const nbc = NBC_HAZARD[f.hazard];

  return (
    <div role="dialog" aria-label={`Facility dossier ${f.name}`} className="drawer-in fixed bottom-7 right-0 top-12 z-30 flex w-[400px] flex-col gap-2.5 overflow-y-auto border-l border-edge bg-panel/95 p-3 backdrop-blur">
      <header className="flex items-start justify-between gap-2">
        <div>
          <div className="mono text-[10px] text-dim">{f.id} · {f.lat.toFixed(3)}°, {f.lon.toFixed(3)}°</div>
          <h2 className="mt-1 flex items-center gap-2 text-base font-bold text-ink"><Factory className="h-4 w-4 text-ember" />{f.name}</h2>
          <div className="mt-1 flex flex-wrap gap-1">
            <Badge color="#FF6B35">{SUBTYPE_LABEL[f.subtype]}</Badge>
            <Badge color={f.hazard === 'G-III' ? '#FF4444' : '#FFB800'}>{f.hazard} · {nbc.label}</Badge>
          </div>
        </div>
        <button onClick={() => selectFacility(null)} aria-label="Close facility dossier" className="rounded p-1 text-mute hover:text-ink"><X className="h-4 w-4" /></button>
      </header>

      <section className="rounded-md border border-edge bg-panel2/60 p-2.5">
        <div className="mono mb-1 text-[9px] uppercase tracking-widest text-dim">isometric massing · 1 unit = 100 m</div>
        <FacilityIso hazard={f.hazard} subtype={f.subtype} />
      </section>

      {stats && (
        <section className="rounded-md border border-edge bg-panel2/60 p-2.5">
          <div className="mono mb-1 text-[9px] uppercase tracking-widest text-dim">fire history (3 km buffer)</div>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div><div className="mono text-lg text-ink">{stats.in24}</div><div className="mono text-[8px] text-dim">24 H</div></div>
            <div><div className="mono text-lg text-ink">{stats.in7}</div><div className="mono text-[8px] text-dim">7 D</div></div>
            <div><div className="mono text-lg text-amber">{stats.persist}d</div><div className="mono text-[8px] text-dim">MAX PERSIST</div></div>
          </div>
          <div className="mt-2 flex justify-center"><Sparkline values={stats.series} color={CLASS_META.industrial.color} width={320} height={40} /></div>
        </section>
      )}

      {resp && (
        <section className="rounded-md border border-edge bg-panel2/60 p-2.5">
          <div className="mono mb-1 text-[9px] uppercase tracking-widest text-dim">response readiness</div>
          {resp.nearest_stations.slice(0, 2).map((s) => (
            <div key={s.name} className="flex justify-between text-[10px] text-mute"><span>{s.name}</span><span className="mono text-ink">{s.distance_km} km · {s.eta_min} min</span></div>
          ))}
          <div className="mono mt-1 text-[9px] text-dim">evacuation radius {resp.evacuation_radius_m} m ({f.hazard})</div>
        </section>
      )}

      <section className="rounded-md border border-edge bg-panel2/60 p-2.5">
        <div className="mono mb-1 text-[9px] uppercase tracking-widest text-dim">regulatory & OSM context</div>
        <p className="text-[10px] leading-relaxed text-mute">{nbc.desc} NBC 2016 Part F class {f.hazard}. CPCB OCEMS high-priority emitter sector (15-min telemetry where mandated).</p>
        <div className="mono mt-1 text-[9px] text-ember">osm tag: {OSM_TAGS[f.subtype]}</div>
        <a className="mono mt-2 inline-flex items-center gap-1 text-[10px] text-ember underline-offset-2 hover:underline" target="_blank" rel="noreferrer" href={overpassTurboUrl(f.lat, f.lon)}>
          <ExternalLink className="h-3 w-3" /> query live OSM data here (Overpass Turbo)
        </a>
      </section>
    </div>
  );
}