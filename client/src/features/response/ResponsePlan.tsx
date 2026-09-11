import { useEffect, useState } from 'react';
import { MapPin, ShieldAlert, Truck } from 'lucide-react';
import { api } from '@/services/api/client';
import { useFireStore } from '@/store/useFireStore';
import { fmtKm } from '@/lib/utils/format';
import type { FireEvent } from '@/types/domain';

interface Station { id: string; name: string; distance_km: number; eta_min: number }
interface ResponseData {
  nearest_stations: Station[];
  resources: { vehicles: number; personnel: number; water_liters: number };
  evacuation_radius_m: number;
  staging_point: { lat: number; lon: number };
  wind_bearing_deg: number;
}

/** Response recommendation for an incident: nearest stations + ETA, resource
 *  table, NBC evacuation radius, downwind staging point. Model, not orders. */
export function ResponsePlan({ event }: { event: FireEvent }) {
  const facilities = useFireStore((s) => s.facilities);
  const [data, setData] = useState<ResponseData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let on = true;
    const fac = facilities.find((f) => f.id === event.nearestFacilityId) ?? null;
    const hazard = fac
      ? fac.hazard
      : event.risk.level === 'critical' ? 'G-III'
      : event.risk.level === 'high' ? 'G-II'
      : null;
    api
      .post<ResponseData>('/api/v1/response/recommend', {
        lat: event.lat,
        lon: event.lon,
        fire_class: event.classification.primary,
        hazard,
        wind_dir_deg: 270,
      })
      .then((d) => { if (on) setData(d); })
      .catch((e: unknown) => { if (on) setError(e instanceof Error ? e.message : String(e)); });
    return () => { on = false; };
  }, [event, facilities]);

  if (error) return <div className="text-[10px] text-magma">response engine unavailable — {error}</div>;
  if (!data) return <div className="text-[10px] text-dim">computing response plan…</div>;

  return (
    <div className="grid gap-1.5 text-[10px]">
      <div className="mono flex items-center gap-1.5 text-[9px] uppercase tracking-widest text-dim"><Truck className="h-3 w-3" /> nearest stations · ETA</div>
      {data.nearest_stations.map((s, i) => (
        <div key={s.id} className="flex items-center justify-between gap-2">
          <span className="truncate text-mute">{i + 1}. {s.name}</span>
          <span className="mono shrink-0 text-ink">{fmtKm(s.distance_km)} · {Math.max(1, Math.round(s.eta_min))} min</span>
        </div>
      ))}
      <div className="grid grid-cols-3 gap-2 border-t border-edge pt-1.5">
        <div>
          <div className="mono text-[9px] uppercase tracking-widest text-dim">resources</div>
          <div className="mt-0.5 text-mute">{data.resources.vehicles} veh · {data.resources.personnel} ppl</div>
          <div className="text-mute">{data.resources.water_liters.toLocaleString()} L water</div>
        </div>
        <div>
          <div className="mono flex items-center gap-1 text-[9px] uppercase tracking-widest text-dim"><ShieldAlert className="h-3 w-3" /> evacuation</div>
          <div className="mt-0.5 text-mute">radius {Math.round(data.evacuation_radius_m)} m</div>
          <div className="text-mute">{data.wind_bearing_deg}° wind</div>
        </div>
        <div>
          <div className="mono flex items-center gap-1 text-[9px] uppercase tracking-widest text-dim"><MapPin className="h-3 w-3" /> staging</div>
          <div className="mt-0.5 mono text-mute">{data.staging_point.lat.toFixed(3)}°, {data.staging_point.lon.toFixed(3)}°</div>
          <div className="text-mute">downwind</div>
        </div>
      </div>
    </div>
  );
}