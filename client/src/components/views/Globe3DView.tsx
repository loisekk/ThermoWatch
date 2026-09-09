import { useEffect, useRef, useState } from 'react';
import Globe, { type GlobeMethods } from 'react-globe.gl';
import { CLASS_META } from '@/config/constants';
import { filterEvents } from '@/selectors/fireSelectors';
import { useFireStore } from '@/store/useFireStore';
import { useUIStore } from '@/store/useUIStore';
import type { FireEvent } from '@/types/domain';

const pointLabel = (d: object): string => {
  const e = d as FireEvent;
  const m = CLASS_META[e.classification.primary];
  return `<div class="map-pop"><b>${m.label}</b> · ${e.classification.confidence}%<br/>FRP ${e.frp} MW · ${e.persistence.regime}<br/>risk ${e.risk.score}</div>`;
};

export function Globe3DView() {
  const wrap = useRef<HTMLDivElement>(null);
  const globe = useRef<GlobeMethods | undefined>(undefined);
  const [dims, setDims] = useState({ w: 800, h: 600 });
  const [ready, setReady] = useState(false);

  const events = useFireStore((s) => s.events);
  const filters = useFireStore((s) => s.filters);
  const select = useFireStore((s) => s.select);
  const autoRotate = useUIStore((s) => s.autoRotate);
  const focus = useUIStore((s) => s.focus);

  const filtered = filterEvents(events, filters);
  const persistent = filtered.filter((e) => e.persistence.regime === 'persistent');

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setDims({ w: entry.contentRect.width, h: entry.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!ready) return;
    const c = globe.current?.controls();
    if (c) { c.autoRotate = autoRotate; c.autoRotateSpeed = 0.5; }
  }, [ready, autoRotate]);

  useEffect(() => {
    if (focus && ready) globe.current?.pointOfView({ lat: focus.lat, lng: focus.lon, altitude: 1.4 }, 1000);
  }, [focus, ready]);

  return (
    <div ref={wrap} className="absolute inset-0" style={{ background: 'radial-gradient(circle at 50% 42%, #0d1420 0%, #07090d 72%)' }} aria-label="3D globe view">
      <Globe
        ref={globe}
        width={dims.w}
        height={dims.h}
        backgroundColor="rgba(0,0,0,0)"
        globeImageUrl="//unpkg.com/three-globe/example/img/earth-night.jpg"
        atmosphereColor="#ff6b35"
        atmosphereAltitude={0.16}
        pointsData={filtered}
        pointLat={(d: object) => (d as FireEvent).lat}
        pointLng={(d: object) => (d as FireEvent).lon}
        pointColor={(d: object) => CLASS_META[(d as FireEvent).classification.primary].color}
        pointRadius={(d: object) => 0.2 + (Math.min((d as FireEvent).frp, 800) / 800) * 1.0}
        pointAltitude={0.02}
        pointLabel={pointLabel}
        onPointClick={(d: object) => select((d as FireEvent).id)}
        ringsData={persistent}
        ringLat={(d: object) => (d as FireEvent).lat}
        ringLng={(d: object) => (d as FireEvent).lon}
        ringColor={() => (t: number) => `rgba(255,184,0,${(1 - t) * 0.8})`}
        ringMaxRadius={5}
        ringPropagationSpeed={0.7}
        ringRepeatPeriod={1100}
        onGlobeReady={() => setReady(true)}
      />
    </div>
  );
}
