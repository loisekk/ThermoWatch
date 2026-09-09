import { useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Checkbox from '@mui/material/Checkbox';
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

interface PredOut {
  model: string;
  classification: { primary: keyof typeof CLASS_META; subtype: IndustrialSubtype | null; scores: Record<string, number>; confidence: number };
  risk: { score: number; level: keyof typeof RISK_META; drivers: string[] };
  spread: { hours: number; radius_km: number }[];
  affected_facilities: string[];
}

/** Manual ML entry-point: user parameters → FastAPI /predict (PyG slot or heuristic ensemble). */
export function ManualPredictionPanel() {
  const [frp, setFrp] = useState(150);
  const [persist, setPersist] = useState(6);
  const [subtype, setSubtype] = useState<IndustrialSubtype | ''>('refinery');
  const [spread, setSpread] = useState(true);
  const [out, setOut] = useState<PredOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      setOut(await api.post<PredOut>('/api/v1/predict', {
        frp, persist_days: persist, facility_subtype: subtype || null,
        include_spread: spread, lat: 22.47, lon: 70.06,
      }));
    } catch (e) {
      setOut(null);
      setErr((e as Error).message);
    }
    setBusy(false);
  };

  return (
    <Paper sx={{ p: 2, display: 'grid', gap: 2 }}>
      <Typography variant="overline" color="text.secondary">Manual Model Run</Typography>
      <Box>
        <Typography className="mono" sx={{ fontSize: 10 }}>FRP (MW): {frp}</Typography>
        <Slider value={frp} min={5} max={900} onChange={(_, v) => setFrp(v as number)} aria-label="FRP" />
      </Box>
      <Box>
        <Typography className="mono" sx={{ fontSize: 10 }}>Persistence (days): {persist}</Typography>
        <Slider value={persist} min={0} max={45} onChange={(_, v) => setPersist(v as number)} aria-label="Persistence days" />
      </Box>
      <TextField select label="Facility context" value={subtype} onChange={(e) => setSubtype(e.target.value as IndustrialSubtype | '')}>
        <MenuItem value="">none / unknown</MenuItem>
        {(Object.keys(SUBTYPE_LABEL) as IndustrialSubtype[]).map((s) => <MenuItem key={s} value={s}>{SUBTYPE_LABEL[s]}</MenuItem>)}
      </TextField>
      <FormControlLabel control={<Checkbox checked={spread} onChange={(e) => setSpread(e.target.checked)} />} label="Include spread forecast (6/12/24h)" />
      <Button variant="contained" onClick={run} disabled={busy}>{busy ? 'Running…' : 'Run prediction'}</Button>
      {err && <Typography sx={{ fontSize: 11 }} color="error">{err} — is the API running on :8000?</Typography>}

      {out && (
        <Box sx={{ display: 'grid', gap: 1, fontSize: 12 }}>
          <div className="mono" style={{ fontSize: 10, color: '#5B6B7D' }}>served by: {out.model}</div>
          <div><Badge color={CLASS_META[out.classification.primary].color}>{CLASS_META[out.classification.primary].label} · {out.classification.confidence}%</Badge></div>
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
