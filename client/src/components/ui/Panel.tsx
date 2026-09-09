import type { ReactNode } from 'react';
import { cn } from '@/lib/utils/cn';

interface PanelProps {
  title: string;
  icon?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}

export function Panel({ title, icon, actions, children, className, bodyClassName }: PanelProps) {
  return (
    <section className={cn('rounded-md border border-edge bg-panel/90', className)}>
      <header className="flex items-center gap-2 border-b border-edge px-3 py-2">
        {icon && <span className="text-ember [&>svg]:h-3.5 [&>svg]:w-3.5">{icon}</span>}
        <h2 className="text-[10px] font-semibold uppercase tracking-[0.16em] text-mute">{title}</h2>
        {actions && <div className="ml-auto flex items-center gap-1">{actions}</div>}
      </header>
      <div className={cn('p-3', bodyClassName)}>{children}</div>
    </section>
  );
}
