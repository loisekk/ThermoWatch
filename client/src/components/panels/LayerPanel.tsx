import { Layers as LayersIcon } from 'lucide-react';
import { useAnalyticsStore } from '@/store/useAnalyticsStore';
import { useFireStore } from '@/store/useFireStore';
import { CLASS_META, CLASS_ORDER } from '@/config/constants';
import { computeBreakdown } from '@/selectors/fireSelectors';
import { cn } from '@/lib/utils/cn';

interface Row { key: string; label: string; on: boolean; toggle: () => void; color?: string; count?: number }

export function LayerPanel() {
  const layers = useAnalyticsStore((s) => s.layers);
  const setLayers = useAnalyticsStore((s) => s.setLayers);
  const advancedMode = useAnalyticsStore((s) => s.advancedMode);
  const events = useFireStore((s) => s.events);
  const filters = useFireStore((s) => s.filters);
  const setFilters = useFireStore((s) => s.setFilters);
  const bd = computeBreakdown(events);

  const rows: Row[] = [
    ...CLASS_ORDER.map((c) => ({
      key: c, label: CLASS_META[c].label, color: CLASS_META[c].color, count: bd[c],
      on: filters.classes.includes(c),
      toggle: () => setFilters({ classes: filters.classes.includes(c) ? filters.classes.filter((x) => x !== c) : [...filters.classes, c] }),
    })),
    { key: 'persistentRings', label: 'Persistent rings', on: layers.persistentRings, toggle: () => setLayers({ persistentRings: !layers.persistentRings }) },
    { key: 'facilities', label: 'OSM facilities', on: layers.facilities, toggle: () => setLayers({ facilities: !layers.facilities }) },
    { key: 'choropleth', label: 'Country density tint', on: layers.choropleth, toggle: () => setLayers({ choropleth: !layers.choropleth }) },
    { key: 'labels', label: 'Country labels', on: layers.labels, toggle: () => setLayers({ labels: !layers.labels }) },
    { key: 'graticule', label: 'Graticule 15°', on: layers.graticule, toggle: () => setLayers({ graticule: !layers.graticule }) },
    { key: 'nightTexture', label: 'Night-lights texture', on: layers.nightTexture, toggle: () => setLayers({ nightTexture: !layers.nightTexture }) },
    ...(advancedMode
      ? [
          { key: 'hex', label: 'Hex density (deck.gl)', on: layers.hexagonDensity, toggle: () => setLayers({ hexagonDensity: !layers.hexagonDensity }) },
          { key: 'extr', label: 'Facility extrusion', on: layers.buildingExtrusion, toggle: () => setLayers({ buildingExtrusion: !layers.buildingExtrusion }) },
          { key: 'spread', label: 'Spread forecast', on: layers.spreadRings, toggle: () => setLayers({ spreadRings: !layers.spreadRings }) },
        ]
      : []),
  ];

  return (
    <div className="pointer-events-auto w-56 rounded-sm border border-edge bg-panel/95 backdrop-blur">
      <div className="flex items-center gap-2 border-b border-edge px-2.5 py-2">
        <LayersIcon className="h-3.5 w-3.5 text-ember" />
        <span className="mono text-[10px] uppercase tracking-widest text-mute">layers</span>
      </div>
      <ul className="max-h-[46vh] overflow-y-auto p-1.5">
        {rows.map((r) => (
          <li key={r.key}>
            <button onClick={r.toggle} aria-pressed={r.on} className="flex w-full items-center gap-2 rounded-sm px-1.5 py-1 text-left hover:bg-panel2">
              <span className={cn('grid h-3.5 w-3.5 place-items-center rounded-[3px] border', r.on ? 'border-ok bg-ok/30' : 'border-edge2')}>
                {r.on && <span className="h-1.5 w-1.5 bg-ok" />}
              </span>
              {r.color && <span className="h-2 w-2 rounded-full" style={{ background: r.color }} />}
              <span className="flex-1 truncate text-[10px] text-mute">{r.label}</span>
              {r.count !== undefined && <span className="mono rounded-sm border border-edge px-1 text-[9px] text-dim">{r.count}</span>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
