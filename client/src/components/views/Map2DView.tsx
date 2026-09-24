import { useEffect, useMemo, useRef, useState } from 'react';
import maplibregl, { type GeoJSONSource, type Map as MLMap, type MapSourceDataEvent } from 'maplibre-gl';
import { CLASS_META, INDIA_CENTER } from '@/config/constants';
import { HEAT_RAMP, LAND, makeWorldVectorStyle } from '@/config/worldStyle';
import { probeNightTexture, WORLD_BOUNDS, WORLD_IMAGE_COORDS } from '@/config/basemap';
import { COUNTRY_LABELS, countryCounts } from '@/lib/geo/countryIndex';
import { facilitiesToFeatureCollection, firesToFeatureCollection } from '@/lib/geo/featureCollection';
import { useFireStore } from '@/store/useFireStore';
import { useUIStore } from '@/store/useUIStore';
import { useAnalyticsStore } from '@/store/useAnalyticsStore';
import { useMapDiagStore } from '@/store/useMapDiagStore';
import { filterEvents } from '@/selectors/fireSelectors';
import { syncDuckDB } from '@/features/analytics/DuckDBEngine';
import { minZoomForCover } from '@/lib/geo/viewClamp';
import { gibsDate, GIBS_ATTRIBUTION } from '@/config/imagery';
import { DeckGLLayers } from '@/features/analytics/DeckGLLayers';

const classColor = ['match', ['get', 'cls'], 'industrial', CLASS_META.industrial.color, 'persistent', CLASS_META.persistent.color, 'wildfire', CLASS_META.wildfire.color, CLASS_META.agricultural.color];

const PULSE_PERIOD_MS = 1600;

export function Map2DView() {
  const container = useRef<HTMLDivElement>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const clickPopupRef = useRef<maplibregl.Popup | null>(null);
  const hoverPopupRef = useRef<maplibregl.Popup | null>(null);
  const labelMarkersRef = useRef<maplibregl.Marker[]>([]);
  const [mapInstance, setMapInstance] = useState<MLMap | null>(null);

  const events = useFireStore((s) => s.events);
  const filters = useFireStore((s) => s.filters);
  const facilities = useFireStore((s) => s.facilities);
  const selectedId = useFireStore((s) => s.selectedEventId);
  const select = useFireStore((s) => s.select);
  const focus = useUIStore((s) => s.focus);
  const advancedMode = useAnalyticsStore((s) => s.advancedMode);
  const layers = useAnalyticsStore((s) => s.layers);
  const timeRange = useAnalyticsStore((s) => s.timeRange);
  const setDuckDBReady = useAnalyticsStore((s) => s.setDuckDBReady);
  const webgl = useMapDiagStore((s) => s.webgl);

  const filtered = useMemo(
    () => filterEvents(events, filters).filter((e) => e.detectedAt >= timeRange.start && e.detectedAt <= timeRange.end),
    [events, filters, timeRange],
  );
  const counts = useMemo(() => countryCounts(filtered), [filtered]);

  // Advanced Mode only: DuckDB sync (Session 7 behaviour preserved)
  useEffect(() => {
    if (!advancedMode || events.length === 0 || facilities.length === 0) return;
    let cancelled = false;
    syncDuckDB(events, facilities)
      .then(() => { if (!cancelled) setDuckDBReady(true); })
      .catch((err) => console.error('[DuckDB] sync failed:', err));
    return () => { cancelled = true; };
  }, [advancedMode, events, facilities, setDuckDBReady]);

  useEffect(() => {
    if (!container.current) return;
    
    // If WebGL rasterization is broken, ViewStage will render FallbackWorldMap instead
    if (webgl && !webgl.rasterizes) return;

    let disposed = false;
    let pulseTimer: number | undefined;

    const map = new maplibregl.Map({
      container: container.current,
      style: makeWorldVectorStyle(),
      center: INDIA_CENTER,
      zoom: Math.max(1.4, minZoomForCover(container.current.clientWidth, container.current.clientHeight)),
      minZoom: minZoomForCover(container.current.clientWidth, container.current.clientHeight),
      maxZoom: 12,
      // NOTE: no maxBounds. The minZoom-cover guarantee + renderWorldCopies:false
      // already lock the world to the screen; maxBounds at exactly ±180 fights the
      // cover zoom in constrainInternal and crashes the constraint solver
      // (TypeError reading '0' of null in _calcMatrices during resize).
      renderWorldCopies: false,
      attributionControl: false,
    });
    if (import.meta.env.DEV) (window as unknown as { __twmap?: MLMap }).__twmap = map;

    useMapDiagStore.getState().reset();

    // Never trust initial layout: force resize on any container change.
    // Guard: setMinZoom only for a real laid-out container, clamped below maxZoom,
    // and error-isolated — a resize exception must never take the map down.
    const ro = new ResizeObserver(() => {
      try {
        map.resize();
        const el = container.current;
        if (el && el.clientWidth > 0 && el.clientHeight > 0) {
          map.setMinZoom(Math.min(11.9, minZoomForCover(el.clientWidth, el.clientHeight)));
        }
      } catch (err) {
        console.error('[map2d] resize guard:', err);
      }
    });
    ro.observe(container.current);

    map.on('error', (e) => useMapDiagStore.getState().pushError(String(e.error?.message ?? 'map error')));
    useMapDiagStore.getState().setMapApi({
      zoomIn: () => map.zoomIn(),
      zoomOut: () => map.zoomOut(),
      reset: () => map.fitBounds(WORLD_BOUNDS, { duration: 600 }),
    });

    // style.load fires IMMEDIATELY (vector style is fully bundled) — nothing critical waits on assets.
    map.once('style.load', () => {
      if (disposed) return;

      map.addSource('fires', { type: 'geojson', data: firesToFeatureCollection([]) });
      map.addSource('facilities', { type: 'geojson', data: facilitiesToFeatureCollection(facilities) });

      map.addLayer({ id: 'fires-halo', type: 'circle', source: 'fires', paint: {
        'circle-radius': ['interpolate', ['linear'], ['get', 'risk'], 0, 6, 100, 20],
        'circle-color': classColor as never, 'circle-opacity': 0.16, 'circle-blur': 0.5 } });
      
      // Animated pulse ring for persistent sources (2D parity with globe ringsData)
      map.addLayer({ id: 'fires-pulse', type: 'circle', source: 'fires', filter: ['==', ['get', 'pers'], 1], paint: {
        'circle-radius': 6, 'circle-opacity': 0, 'circle-stroke-color': CLASS_META.persistent.color,
        'circle-stroke-width': 1.5, 'circle-stroke-opacity': 0.6 } });
      map.addLayer({ id: 'fires-ring', type: 'circle', source: 'fires', filter: ['==', ['get', 'pers'], 1], paint: {
        'circle-radius': 10, 'circle-opacity': 0, 'circle-stroke-color': CLASS_META.persistent.color, 'circle-stroke-width': 1.2, 'circle-stroke-opacity': 0.75 } });
      map.addLayer({ id: 'fires-core', type: 'circle', source: 'fires', paint: {
        'circle-radius': ['interpolate', ['linear'], ['get', 'frp'], 0, 3, 900, 8],
        'circle-color': classColor as never, 'circle-stroke-color': '#0b0f14', 'circle-stroke-width': 1 } });
      map.addLayer({ id: 'facilities', type: 'circle', source: 'facilities', paint: {
        'circle-radius': 2.5, 'circle-color': '#10161d', 'circle-stroke-color': '#7d8da1', 'circle-stroke-width': 1 } });
      // NASA GIBS imagery raster (no key; daily composite) — under the vector fills.
      if (!map.getSource('gibs')) {
        map.addSource('gibs', {
          type: 'raster',
          tiles: [`https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_SNPP_CorrectedReflectance_TrueColor/default/${gibsDate()}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg`],
          tileSize: 256,
          attribution: GIBS_ATTRIBUTION,
          maxzoom: 9,
        });
        map.addLayer({ id: 'imagery', type: 'raster', source: 'gibs', paint: { 'raster-opacity': 0.9, 'raster-fade-duration': 300 } }, 'countries-fill');
        map.setLayoutProperty('imagery', 'visibility', useAnalyticsStore.getState().layers.imagery ? 'visible' : 'none');
      }

      const t0 = performance.now();
      pulseTimer = window.setInterval(() => {
        const t = ((performance.now() - t0) % PULSE_PERIOD_MS) / PULSE_PERIOD_MS;
        map.setPaintProperty('fires-pulse', 'circle-radius', 6 + t * 12);
        map.setPaintProperty('fires-pulse', 'circle-stroke-opacity', 0.6 * (1 - t));
      }, 60);

      // Country labels as HTML markers (no glyph fetch required)
      labelMarkersRef.current = COUNTRY_LABELS.map((l) => {
        const el = document.createElement('div');
        el.className = 'mono pointer-events-none text-[10px] uppercase tracking-[0.18em] text-dim/80';
        el.textContent = l.name;
        return new maplibregl.Marker({ element: el }).setLngLat(l.centroid).addTo(map);
      });

      map.fitBounds(WORLD_BOUNDS, { duration: 0 });
      useMapDiagStore.getState().setMode('vector-110m');
      useMapDiagStore.getState().setReady(true);
      setMapInstance(map);

      // Night-lights texture: OPTIONAL layer (default off), still probe-guarded.
      probeNightTexture().then((url) => {
        if (disposed || !url || map.getSource('night')) return;
        map.addSource('night', { type: 'image', url, coordinates: WORLD_IMAGE_COORDS });
        map.addLayer({ id: 'night', type: 'raster', source: 'night', paint: { 'raster-opacity': 0.4, 'raster-saturation': -0.3 } }, 'countries-fill');
        map.setLayoutProperty('night', 'visibility', useAnalyticsStore.getState().layers.nightTexture ? 'visible' : 'none');
      });
    });

    map.on('sourcedata', (e: MapSourceDataEvent) => {
      if (e.sourceId === 'night') useMapDiagStore.getState().pushError('night texture unavailable — vector basemap active');
    });

    // Hover tooltip — parity with globe pointLabel
    map.on('mousemove', 'fires-core', (e) => {
      const f = e.features?.[0];
      if (!f?.properties) return;
      map.getCanvas().style.cursor = 'pointer';
      const p = f.properties as Record<string, string | number>;
      hoverPopupRef.current ??= new maplibregl.Popup({ closeButton: false, offset: 10 });
      // Built as DOM nodes, never setHTML(): feature properties originate in the
      // API payload, and setHTML() routes them through MapLibre's HTML sanitizer
      // (see GHSA-jrc7-96c5-q579 for the sanitizer-bypass class). textContent is
      // never parsed as markup, so this popup is inert by construction.
      const pop = document.createElement('div');
      pop.className = 'map-pop';
      const popClass = document.createElement('b');
      popClass.textContent = String(
        CLASS_META[p.cls as keyof typeof CLASS_META]?.label ?? p.cls,
      );
      pop.append(
        popClass,
        ` · risk ${p.risk}`,
        document.createElement('br'),
        `FRP ${p.frp} MW · ${p.pers === 1 ? 'persistent' : 'transient'}`,
      );
      hoverPopupRef.current
        .setLngLat(e.lngLat)
        .setDOMContent(pop)
        .addTo(map);
    });
    map.on('mouseleave', 'fires-core', () => {
      map.getCanvas().style.cursor = '';
      hoverPopupRef.current?.remove();
    });

    map.on('click', 'fires-core', (e) => {
      const f = e.features?.[0];
      if (f?.properties?.eid) select(String(f.properties.eid));
    });
    map.on('click', 'facilities', (e) => {
      const p = e.features?.[0]?.properties;
      if (p?.fid) useFireStore.getState().selectFacility(String(p.fid));
    });

    return () => {
      disposed = true;
      ro.disconnect();
      if (pulseTimer !== undefined) window.clearInterval(pulseTimer);
      labelMarkersRef.current.forEach((m) => m.remove());
      labelMarkersRef.current = [];
      markerRef.current?.remove();
      hoverPopupRef.current?.remove();
      clickPopupRef.current?.remove();
      useMapDiagStore.getState().setMapApi(null);
      map.remove();
      setMapInstance(null);
      useMapDiagStore.getState().setReady(false);
    };
    // Mount-once effect: the map instance is created a single time; data updates
    // flow through the dedicated source/marker/focus effects below.
  }, [webgl]);

  useEffect(() => {
    const src = mapInstance?.getSource('fires') as GeoJSONSource | undefined;
    src?.setData(firesToFeatureCollection(filtered) as never);
  }, [filtered, mapInstance]);

  // Choropleth via feature-state (cheap: ~180 writes, debounced)
  useEffect(() => {
    if (!mapInstance) return;
    const t = window.setTimeout(() => {
      counts.forEach((n, id) => mapInstance.setFeatureState({ source: 'countries', id }, { count: n }));
    }, 400);
    return () => window.clearTimeout(t);
  }, [counts, mapInstance]);

  // Layer visibility toggles
  useEffect(() => {
    if (!mapInstance) return;
    const vis = (id: string, on: boolean) => { if (mapInstance.getLayer(id)) mapInstance.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none'); };
    vis('graticule', layers.graticule);
    vis('facilities', layers.facilities);
    vis('fires-ring', layers.persistentRings);
    vis('fires-pulse', layers.persistentRings);
    vis('night', layers.nightTexture);
    vis('imagery', layers.imagery);
    if (mapInstance.getLayer('countries-fill')) {
      mapInstance.setPaintProperty('countries-fill', 'fill-opacity', layers.imagery ? 0.25 : 0.9);
    }
    mapInstance.setPaintProperty('countries-fill', 'fill-color', (layers.choropleth ? HEAT_RAMP : LAND) as never);
    labelMarkersRef.current.forEach((m) => { (m.getElement() as HTMLElement).style.display = layers.labels ? '' : 'none'; });
  }, [layers, mapInstance]);

  useEffect(() => {
    const map = mapInstance;
    markerRef.current?.remove();
    markerRef.current = null;
    const ev = events.find((e) => e.id === selectedId);
    if (!map || !ev) return;
    const el = document.createElement('div');
    el.className = 'pulse-marker';
    el.style.color = CLASS_META[ev.classification.primary].color;
    markerRef.current = new maplibregl.Marker({ element: el }).setLngLat([ev.lon, ev.lat]).addTo(map);
  }, [selectedId, events, mapInstance]);

  useEffect(() => {
    if (focus && mapInstance) mapInstance.flyTo({ center: [focus.lon, focus.lat], zoom: 7, duration: 1200 });
  }, [focus, mapInstance]);

  return (
    <>
      <div ref={container} className="absolute inset-0" aria-label="2D world fire map" />
      {advancedMode && mapInstance && <DeckGLLayers map={mapInstance} events={filtered} facilities={facilities} />}
    </>
  );
}