import type { ReactNode } from 'react';

interface BadgeProps { color: string; children: ReactNode; mono?: boolean }

export function Badge({ color, children, mono = true }: BadgeProps) {
  return (
    <span
      className={`${mono ? 'mono' : ''} inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider`}
      style={{ color, borderColor: `${color}55`, background: `${color}14` }}
    >
      {children}
    </span>
  );
}
