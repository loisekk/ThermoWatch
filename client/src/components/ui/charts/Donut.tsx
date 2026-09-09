interface Segment { value: number; color: string; label: string }
interface DonutProps { segments: Segment[]; size?: number; thickness?: number; centerLabel: string; centerSub: string }

export function Donut({ segments, size = 116, thickness = 12, centerLabel, centerSub }: DonutProps) {
  const total = segments.reduce((a, s) => a + s.value, 0) || 1;
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <svg width={size} height={size} role="img" aria-label={`Classification split: ${segments.map((s) => `${s.label} ${s.value}`).join(', ')}`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-edge)" strokeWidth={thickness} />
      {segments.map((s) => {
        const len = (s.value / total) * c;
        const el = (
          <circle
            key={s.label}
            cx={size / 2} cy={size / 2} r={r} fill="none"
            stroke={s.color} strokeWidth={thickness}
            strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-offset}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
        );
        offset += len;
        return el;
      })}
      <text x="50%" y="47%" textAnchor="middle" className="mono" fill="var(--color-ink)" fontSize={18} fontWeight={600}>{centerLabel}</text>
      <text x="50%" y="62%" textAnchor="middle" className="mono" fill="var(--color-dim)" fontSize={8} letterSpacing={1}>{centerSub}</text>
    </svg>
  );
}
