import { Factory } from 'lucide-react';
import { Panel } from '@/components/ui/Panel';
import { SUBTYPE_LABEL } from '@/config/constants';
import { eventsNearFacility } from '@/selectors/fireSelectors';
import { useFireStore } from '@/store/useFireStore';
import { useUIStore } from '@/store/useUIStore';

export function FacilityTable() {
  const events = useFireStore((s) => s.events);
  const facilities = useFireStore((s) => s.facilities);
  const requestFocus = useUIStore((s) => s.requestFocus);

  return (
    <Panel title="OSM Industrial Registry" icon={<Factory />} bodyClassName="p-0">
      <table className="mono w-full text-left text-[10px]">
        <thead className="border-b border-edge text-[9px] uppercase tracking-wider text-dim">
          <tr><th className="px-2.5 py-1.5">Facility</th><th className="py-1.5">Type</th><th className="py-1.5">Hz</th><th className="py-1.5 pr-2.5 text-right">24h</th></tr>
        </thead>
        <tbody className="divide-y divide-edge/60">
          {facilities.map((f) => {
            const n = eventsNearFacility(events, f).length;
            return (
              <tr key={f.id} onClick={() => requestFocus(f.lat, f.lon)} className="cursor-pointer transition-colors hover:bg-panel2/70">
                <td className="max-w-36 truncate px-2.5 py-1.5 text-ink">{f.name}</td>
                <td className="py-1.5 text-mute">{SUBTYPE_LABEL[f.subtype]}</td>
                <td className={`py-1.5 ${f.hazard === 'G-III' ? 'text-magma' : 'text-amber'}`}>{f.hazard}</td>
                <td className={`py-1.5 pr-2.5 text-right ${n > 0 ? 'text-ember' : 'text-dim'}`}>{n}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Panel>
  );
}
