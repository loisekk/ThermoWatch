import type { ReactNode } from 'react';
import { cn } from '@/lib/utils/cn';

interface Option<T extends string> { value: T; label: string; icon?: ReactNode }

interface SegmentedProps<T extends string> {
  options: Option<T>[];
  value: T;
  onChange: (v: T) => void;
  ariaLabel: string;
}

export function Segmented<T extends string>({ options, value, onChange, ariaLabel }: SegmentedProps<T>) {
  return (
    <div role="tablist" aria-label={ariaLabel} className="flex rounded border border-edge bg-panel2 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            'flex items-center gap-1.5 rounded-sm px-3 py-1 text-[11px] font-medium uppercase tracking-wider transition-colors',
            value === o.value ? 'bg-ember/15 text-ember' : 'text-mute hover:text-ink',
          )}
        >
          {o.icon}
          {o.label}
        </button>
      ))}
    </div>
  );
}
