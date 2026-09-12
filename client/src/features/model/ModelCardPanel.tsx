import { useEffect, useState } from 'react';
import Alert from '@mui/material/Alert';
import Chip from '@mui/material/Chip';
import Paper from '@mui/material/Paper';
import Skeleton from '@mui/material/Skeleton';
import Typography from '@mui/material/Typography';
import { api, API_BASE } from '@/services/api/client';

interface PerClass { precision: number; recall: number; f1: number; support: number }
interface EvalReport {
  model: string; trained_at: string;
  dataset: { source: string; n_samples: number; label_provenance: Record<string, unknown>; class_counts: Record<string, number> };
  split: { train: number; val: number; test: number };
  metrics: { macro_f1: number; weighted_f1: number; per_class: Record<string, PerClass> };
  confusion_matrix: { labels: string[]; matrix: number[][] };
  inference_ms_p50: number; limitations: string[];
}
interface Card { served_by: string; provenance: { stgnn_available: boolean; bundle_present: boolean }; eval: EvalReport | null; features: string[]; classes: string[]; ui_projection: string; claim_safety: string[] }

export function ModelCardPanel() {
  const [card, setCard] = useState<Card | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    api.get<Card>('/api/v1/model/card').then(setCard).catch(() => setErr(true));
  }, []);

  if (err) return (
    <Alert severity="warning">
      Backend unreachable at {API_BASE}.{' '}
      {API_BASE.includes('localhost')
        ? 'Start FastAPI (port 8000) or set VITE_API_URL.'
        : 'Render instance may be waking — retrying; if this persists check TW_CORS_ORIGINS includes this site.'}
    </Alert>
  );
  if (!card) return <Skeleton variant="rectangular" height={320} />;
  const ev = card.eval;

  return (
    <Paper sx={{ p: 2, display: 'grid', gap: 1.5 }}>
      <div className="flex items-center gap-2">
        <Chip size="small" color="primary" variant="outlined" label={`served by: ${card.served_by}`} />
        <Chip size="small" variant="outlined" label={`PyG ST-GNN: ${card.provenance.stgnn_available ? 'available' : 'not installed'}`} />
      </div>

      {!ev && <Alert severity="info">No trained bundle yet. Run: <code>python -m app.ml.train --source synthetic</code> then restart the API. Heuristic ensemble is serving.</Alert>}

      {ev && (
        <>
          <div className="flex items-baseline gap-3">
            <span className="mono text-2xl font-semibold text-ink">{ev.metrics.macro_f1.toFixed(3)}</span>
            <span className="mono text-[10px] uppercase tracking-widest text-dim">macro-F1 · test n={ev.split.test} · p50 {ev.inference_ms_p50} ms</span>
          </div>

          <div className="grid gap-1">
            {Object.entries(ev.metrics.per_class).map(([cls, m]) => (
              <div key={cls} className="flex items-center gap-2">
                <span className="mono w-40 shrink-0 truncate text-[10px] text-mute">{cls}</span>
                <div className="h-1.5 flex-1 rounded-full bg-edge">
                  <div className="h-1.5 rounded-full bg-ember" style={{ width: `${m.f1 * 100}%` }} />
                </div>
                <span className="mono w-24 shrink-0 text-right text-[9px] text-dim">F1 {m.f1.toFixed(2)} · n={m.support}</span>
              </div>
            ))}
          </div>

          <div>
            <Typography variant="overline" color="text.secondary">confusion (row = true)</Typography>
            <div className="grid gap-px" style={{ gridTemplateColumns: `repeat(${ev.confusion_matrix.labels.length}, 1fr)` }}>
              {ev.confusion_matrix.matrix.map((row, i) => {
                const rowMax = Math.max(...row, 1);
                return row.map((v, j) => (
                  <div key={`${i}-${j}`} title={`${ev.confusion_matrix.labels[i]} → ${ev.confusion_matrix.labels[j]}: ${v}`}
                    className="h-3.5 w-full" style={{ background: i === j ? `rgba(63,185,80,${0.15 + 0.75 * (v / rowMax)})` : `rgba(255,68,68,${0.1 + 0.7 * (v / rowMax)})` }} />
                ));
              })}
            </div>
          </div>

          <div className="mono text-[9px] text-dim">
            data: {ev.dataset.source} · n={ev.dataset.n_samples} · train/val/test {ev.split.train}/{ev.split.val}/{ev.split.test} (stratified) · trained {ev.trained_at.slice(0, 10)}
          </div>
          <ul className="grid gap-0.5 text-[10px] text-mute">
            {ev.limitations.map((l) => <li key={l}>· {l}</li>)}
          </ul>
        </>
      )}

      <div className="grid gap-1">
        <Typography variant="overline" color="text.secondary">claim safety</Typography>
        <div className="flex flex-wrap gap-1">{card.claim_safety.map((c) => <Chip key={c} size="small" variant="outlined" color="success" label={c} />)}</div>
        <div className="mono text-[9px] leading-relaxed text-dim">{card.ui_projection}</div>
        <div className="mono text-[9px] text-dim">features: {card.features.join(', ')}</div>
      </div>
    </Paper>
  );
}
