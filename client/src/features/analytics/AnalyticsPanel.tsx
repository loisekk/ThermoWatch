/** Advanced-mode control surface: layer visibility + DuckDB spatial queries. */
import { useEffect, useState } from 'react';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import Switch from '@mui/material/Switch';
import FormControlLabel from '@mui/material/FormControlLabel';
import Button from '@mui/material/Button';
import TextField from '@mui/material/TextField';
import { useAnalyticsStore } from '@/store/useAnalyticsStore';
import { queryFacilityStats, queryFiresNearFacilities } from './DuckDBEngine';

interface FacilityStat { subtype: string; count: number; avgRisk: number }
interface NearbyFire { fireId: string; facilityName: string; distanceKm: number }

export function AnalyticsPanel() {
  const layers = useAnalyticsStore((s) => s.layers);
  const setLayers = useAnalyticsStore((s) => s.setLayers);
  const duckdbReady = useAnalyticsStore((s) => s.duckdbReady);
  const [radius, setRadius] = useState(5);
  const [facilityStats, setFacilityStats] = useState<FacilityStat[]>([]);
  const [nearbyFires, setNearbyFires] = useState<NearbyFire[] | null>(null);

  useEffect(() => {
    if (duckdbReady) queryFacilityStats().then(setFacilityStats).catch(() => setFacilityStats([]));
  }, [duckdbReady]);

  const handleQuery = async () => {
    if (!duckdbReady) return;
    const results = await queryFiresNearFacilities(radius, 'G-III').catch(() => []);
    setNearbyFires(results);
  };

  if (!duckdbReady) {
    return (
      <Paper sx={{ p: 2 }}>
        <Typography variant="overline" color="text.secondary">analytics engine</Typography>
        <Typography sx={{ fontSize: 12, color: '#8CA0B3', mt: 1 }}>
          DuckDB-WASM not loaded yet. Toggle <b>Advanced Mode</b> in the 2D viewport to boot the
          in-browser SQL engine (loads the live feed + facility registry for client-side spatial queries).
        </Typography>
      </Paper>
    );
  }

  return (
    <Paper sx={{ p: 2, display: 'grid', gap: 2 }}>
      <Typography variant="overline" color="text.secondary">advanced analytics</Typography>

      <div className="grid gap-1">
        <FormControlLabel
          control={<Switch checked={layers.hexagonDensity} onChange={(e) => setLayers({ hexagonDensity: e.target.checked })} size="small" />}
          label={<Typography sx={{ fontSize: 11 }}>Hex density heatmap (1 km cells)</Typography>}
        />
        <FormControlLabel
          control={<Switch checked={layers.buildingExtrusion} onChange={(e) => setLayers({ buildingExtrusion: e.target.checked })} size="small" />}
          label={<Typography sx={{ fontSize: 11 }}>Facility extrusion (3D, hazard-height)</Typography>}
        />
        <FormControlLabel
          control={<Switch checked={layers.spreadRings} onChange={(e) => setLayers({ spreadRings: e.target.checked })} size="small" />}
          label={<Typography sx={{ fontSize: 11 }}>Spread forecast rings (6/12/24 h)</Typography>}
        />
        <FormControlLabel
          control={<Switch checked={layers.timeSlider} onChange={(e) => setLayers({ timeSlider: e.target.checked })} size="small" />}
          label={<Typography sx={{ fontSize: 11 }}>Time slider (temporal scrubber)</Typography>}
        />
      </div>

      <div className="border-t border-edge pt-2">
        <Typography variant="overline" color="text.secondary">spatial query · duckdb-wasm</Typography>
        <div className="mt-2 flex gap-2">
          <TextField
            label="Radius (km)"
            type="number"
            value={radius}
            onChange={(e) => setRadius(Math.max(0, Number(e.target.value)))}
            size="small"
            sx={{ flex: 1 }}
            inputProps={{ 'aria-label': 'Query radius in kilometres' }}
          />
          <Button variant="outlined" onClick={handleQuery} size="small">Query</Button>
        </div>
        {nearbyFires !== null && (
          <div className="mono mt-2 text-[10px] text-mute">
            {nearbyFires.length} fires within {radius} km of G-III facilities (client-side SQL, no server round-trip)
          </div>
        )}
      </div>

      {facilityStats.length > 0 && (
        <div className="border-t border-edge pt-2">
          <Typography variant="overline" color="text.secondary">facility statistics</Typography>
          <div className="mt-1 grid gap-1">
            {facilityStats.slice(0, 5).map((stat) => (
              <div key={stat.subtype} className="flex justify-between text-[10px]">
                <span className="text-mute">{stat.subtype}</span>
                <span className="mono text-ink">{stat.count} events · avg risk {Math.round(stat.avgRisk)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Paper>
  );
}
