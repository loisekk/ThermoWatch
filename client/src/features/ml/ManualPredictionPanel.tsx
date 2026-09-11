import { useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Checkbox from '@mui/material/Checkbox';
import Chip from '@mui/material/Chip';
import FormControlLabel from '@mui/material/FormControlLabel';
import MenuItem from '@mui/material/MenuItem';
import Paper from '@mui/material/Paper';
import Slider from '@mui/material/Slider';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { api } from '@/services/api/client';
import { Badge } from '@/components/ui/Badge';
import { CLASS_META, RISK_META, SUBTYPE_LABEL } from '@/config/constants';
import type { IndustrialSubtype } from '@/types/domain';
import { buildPredictRequest, DEFAULT_FORM, PRESETS, type PredictFormState } from './predictPayload';

interface PredOut {
  model: string;
  classification: { primary: keyof typeof CLASS_META; subtype: IndustrialSubtype | null; scores: Record<string, number>; confidence: number };
  risk: { score: number; level: keyof typeof RISK_META; drivers: string[] };
  spread: { hours: number; radius_km: number }[];
  affected_facilities: string[];
}

function Row({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void }) {
  return (
    <Box>
      <Typography className="mono" sx={{ fontSize: 10 }}>
        {label}: <b style={{ color: '#FF6B35' }}>{step < 1 ? value.toFixed(2) : value}</b>
      </Typography>
      <Slider size="small" value={value} min={min} max={max} step={step} onChange={(_, v) => onChange(v as number)} aria-label={label} />
    </Box>
  );
}

/** Manual ML entry-point: full feature contract → FastAPI /predict (bundle or heuristic ensemble). */
export function ManualPredictionPanel() {
  const [form, setForm] = useState<PredictFormState>(DEFAULT_FORM);
  const [out, setOut] = useState<PredOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = (patch: Partial<PredictFormState>) => setForm((f) => ({ ...f, ...patch }));

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      setOut(await api.post<PredOut>('/api/v1/predict', buildPredictRequest(form)));
    } catch (e) {
      setOut(null);
      setErr((e as Error).message);
    }
    setBusy(false);
  };

  return (
    <Paper sx={{ p: 2, display: 'grid', gap: 1.5 }}>
      <Typography variant="overline" color="text.secondary">Manual Model Run · full feature contract</Typography>

      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
        {Object.keys(PRESETS).map((p) => (
          <Chip key={p} size="small" variant="outlined" label={p} onClick={() => set(PRESETS[p])} />
        ))}
      </Box>

      <Typography className="mono" sx={{ fontSize: 9, letterSpacing: '.14em', color: '#5B6B7D' }}>THERMAL</Typography>
      <Row label="frp (MW)" value={form.frp} min={5} max={900} step={5} onChange={(v) => set({ frp: v })} />
      <Row label="brightness_k (K)" value={form.brightness_k} min={280} max={420} step={1} onChange={(v) => set({ brightness_k: v })} />
      <Row label="night_ratio" value={form.night_ratio} min={0} max={1} step={0.05} onChange={(v) => set({ night_ratio: v })} />
      <Row label="diurnal_variance" value={form.diurnal_variance} min={0} max={1} step={0.05} onChange={(v) => set({ diurnal_variance: v })} />

      <Typography className="mono" sx={{ fontSize: 9, letterSpacing: '.14em', color: '#5B6B7D' }}>TEMPORAL / PERSISTENCE</Typography>
      <Row label="persist_days" value={form.persist_days} min={0} max={45} step={1} onChange={(v) => set({ persist_days: v })} />
      <Row label="detections_30d" value={form.detections_30d} min={0} max={60} step={1} onChange={(v) => set({ detections_30d: v })} />
      <Row label="frp_stability" value={form.frp_stability} min={0} max={1} step={0.05} onChange={(v) => set({ frp_stability: v })} />

      <Typography className="mono" sx={{ fontSize: 9, letterSpacing: '.14em', color: '#5B6B7D' }}>SPATIAL CONTEXT</Typography>
      <TextField select size="small" label="Facility context" value={form.facility_subtype} onChange={(e) => set({ facility_subtype: e.target.value })}>
        <MenuItem value="">none / unknown</MenuItem>
        {(Object.keys(SUBTYPE_LABEL) as IndustrialSubtype[]).map((s) => (
          <MenuItem key={s} value={s}>{SUBTYPE_LABEL[s]}</MenuItem>
        ))}
      </TextField>
      <Box sx={{ display: 'flex', gap: 1 }}>
        <TextField size="small" type="number" label="lat" value={form.lat} onChange={(e) => set({ lat: Number(e.target.value) })} fullWidth />
        <TextField size="small" type="number" label="lon" value={form.lon} onChange={(e) => set({ lon: Number(e.target.value) })} fullWidth />
      </Box>
      <Row label="forest_proxy" value={form.forest_proxy} min={0} max={1} step={0.05} onChange={(v) => set({ forest_proxy: v })} />
      <Row label="agri_window" value={form.agri_window} min={0} max={1} step={0.05} onChange={(v) => set({ agri_window: v })} />
      <Row label="cluster_density" value={form.cluster_density} min={0} max={1} step={0.05} onChange={(v) => set({ cluster_density: v })} />

      <Typography className="mono" sx={{ fontSize: 9, letterSpacing: '.14em', color: '#5B6B7D' }}>ENVIRONMENT / SPREAD</Typography>
      <Row label="wind_speed (m/s)" value={form.wind_speed_ms} min={0} max={25} step={0.5} onChange={(v) => set({ wind_speed_ms: v })} />
      <Row label="wind_dir (°)" value={form.wind_dir_deg} min={0} max={360} step={5} onChange={(v) => set({ wind_dir_deg: v })} />
      <FormControlLabel
        control={<Checkbox size="small" checked={form.include_spread} onChange={(e) => set({ include_spread: e.target.checked })} />}
        label={<Typography sx={{ fontSize: 11 }}>Include spread forecast (6/12/24 h)</Typography>}
      />

      <Box sx={{ display: 'flex', gap: 1 }}>
        <Button variant="contained" onClick={run} disabled={busy} fullWidth>{busy ? 'Running…' : 'Run prediction'}</Button>
        <Button variant="outlined" onClick={() => navigator.clipboard?.writeText(JSON.stringify(buildPredictRequest(form), null, 2))}>copy JSON</Button>
      </Box>
      {err && <Typography sx={{ fontSize: 11 }} color="error">{err} — is the API running on :8000?</Typography>}

      {out && (
        <Box sx={{ display: 'grid', gap: 1, fontSize: 12 }}>
          <div className="mono" style={{ fontSize: 10, color: '#5B6B7D' }}>served by: {out.model}</div>
          <div><Badge color={CLASS_META[out.classification.primary].color}>{CLASS_META[out.classification.primary].label} · {out.classification.confidence}%</Badge></div>
          {Object.entries(out.classification.scores).map(([c, s]) => (
            <Box key={c} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <span className="mono" style={{ width: 34, fontSize: 9, color: '#8CA0B3' }}>{c.slice(0, 3).toUpperCase()}</span>
              <Box sx={{ flex: 1, height: 5, borderRadius: 1, bgcolor: '#1D2833' }}>
                <Box sx={{ width: `${s * 100}%`, height: 5, borderRadius: 1, background: CLASS_META[c as keyof typeof CLASS_META]?.color ?? '#8CA0B3' }} />
              </Box>
              <span className="mono" style={{ fontSize: 9, color: '#8CA0B3' }}>{Math.round(s * 100)}%</span>
            </Box>
          ))}
          {out.classification.subtype && <div className="mono" style={{ fontSize: 11 }}>{SUBTYPE_LABEL[out.classification.subtype]}</div>}
          <div><Badge color={RISK_META[out.risk.level].color}>risk {out.risk.score}/100</Badge></div>
          <ul style={{ margin: 0, paddingLeft: 16, color: '#8CA0B3' }}>{out.risk.drivers.map((d) => <li key={d}>{d}</li>)}</ul>
          {out.spread.length > 0 && <div className="mono" style={{ fontSize: 10 }}>spread: {out.spread.map((r) => `${r.hours}h→${r.radius_km}km`).join(' · ')}</div>}
          {out.affected_facilities.length > 0 && <div className="mono" style={{ fontSize: 10 }}>exposed: {out.affected_facilities.join(', ')}</div>}
        </Box>
      )}
    </Paper>
  );
}
