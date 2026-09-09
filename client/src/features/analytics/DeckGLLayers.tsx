/** deck.gl overlay mounted inside MapLibre GL via MapboxOverlay (v9 supports MapLibre).
 *  The overlay is created once per map and layers are swapped with setProps —
 *  no add/remove-control churn on every data tick. */
import { useEffect, useMemo, useRef } from 'react';
import { MapboxOverlay } from '@deck.gl/mapbox';
import { PolygonLayer } from '@deck.gl/layers';
import { HexagonLayer } from '@deck.gl/aggregation-layers';
import type { Layer } from '@deck.gl/core';
import type { Map as MLMap } from 'maplibre-gl';
import type { FireEvent, Facility } from '@/types/domain';
import { useAnalyticsStore } from '@/store/useAnalyticsStore';
import { SUBTYPE_COLORS, HAZARD_HEIGHTS, buildFacilityFootprints, buildSpreadRings, filterByTimeRange } from './deckData';

interface DeckGLLayersProps {
  map: MLMap | null;
  events: FireEvent[];
  facilities: Facility[];
}

/** HEX color ramp for the density heatmap (ember → crimson). */
const HEX_COLOR_RANGE: [number, number, number][] = [
  [42, 54, 68],
  [255, 184, 0],
  [255, 107, 53],
  [255, 68, 68],
];

export function DeckGLLayers({ map, events, facilities }: DeckGLLayersProps) {
  const layers = useAnalyticsStore((s) => s.layers);
  const timeRange = useAnalyticsStore((s) => s.timeRange);
  const overlayRef = useRef<MapboxOverlay | null>(null);

  const filteredEvents = useMemo(
    () => filterByTimeRange(events, timeRange.start, timeRange.end),
    [events, timeRange.start, timeRange.end],
  );

  const deckLayers = useMemo(() => {
    const out: Layer[] = [];

    if (layers.hexagonDensity) {
      out.push(
        new HexagonLayer<FireEvent>({
          id: 'hexagon-density',
          data: filteredEvents,
          pickable: true,
          extruded: true,
          radius: 1000, // 1 km cells
          elevationScale: 20,
          coverage: 0.9,
          getPosition: (d) => [d.lon, d.lat],
          getElevationWeight: (d) => d.frp,
          getColorWeight: (d) => Math.max(1, d.frp),
          colorRange: HEX_COLOR_RANGE,
          opacity: 0.65,
          elevationRange: [0, 2000],
          autoHighlight: true,
          transitions: { getElevationWeight: 500 },
        }),
      );
    }

    if (layers.buildingExtrusion) {
      out.push(
        new PolygonLayer<ReturnType<typeof buildFacilityFootprints>[number]>({
          id: 'facility-extrusion',
          data: buildFacilityFootprints(facilities),
          pickable: true,
          extruded: true,
          wireframe: true,
          getPolygon: (d) => d.polygon,
          getElevation: (d) => HAZARD_HEIGHTS[d.hazard] ?? 1000,
          getFillColor: (d) => SUBTYPE_COLORS[d.subtype] ?? [128, 128, 128],
          getLineColor: [232, 238, 245, 60],
          opacity: 0.7,
          autoHighlight: true,
          transitions: { getElevation: 500 },
        }),
      );
    }

    if (layers.spreadRings) {
      out.push(
        new PolygonLayer<ReturnType<typeof buildSpreadRings>[number]>({
          id: 'spread-forecast',
          data: buildSpreadRings(filteredEvents),
          pickable: true,
          filled: false,
          stroked: true,
          getPolygon: (d) => d.polygon,
          getLineColor: (d) => (d.risk === 'critical' ? [255, 68, 68, 180] : [255, 107, 53, 180]),
          getLineWidth: 2,
          lineWidthUnits: 'pixels',
          transitions: { getPolygon: 1000 },
        }),
      );
    }

    return out;
  }, [filteredEvents, facilities, layers]);

  // Mount the overlay once per map instance.
  useEffect(() => {
    if (!map) return;
    const overlay = new MapboxOverlay({ layers: [] });
    map.addControl(overlay);
    overlayRef.current = overlay;
    return () => {
      map.removeControl(overlay);
      overlayRef.current = null;
    };
  }, [map]);

  // Swap layers in place as data/visibility changes.
  useEffect(() => {
    overlayRef.current?.setProps({ layers: deckLayers });
  }, [deckLayers]);

  return null; // rendering happens inside the MapLibre canvas
}
