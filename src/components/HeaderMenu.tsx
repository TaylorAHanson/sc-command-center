import React, { useEffect, useRef, useState } from 'react';
import { Check, MoreHorizontal, type LucideIcon } from 'lucide-react';
import clsx from 'clsx';

export interface HeaderMenuItem {
  key: string;
  label: string;
  icon?: LucideIcon;
  /** Receives the menu's trigger, for an item that opens something anchored to it. */
  onSelect: (trigger: HTMLElement) => void;
  title?: string;
  disabled?: boolean;
  /** For a choice between options: shows a check against the current one. */
  checked?: boolean;
  danger?: boolean;
}

export interface HeaderMenuSection {
  label?: string;
  items: HeaderMenuItem[];
}

/**
 * The "⋯" menu at the end of a header: actions people reach for now and then,
 * kept out of the bar so the ones used every day stay readable.
 */
export const HeaderMenu: React.FC<{
  sections: HeaderMenuSection[];
  dark?: boolean;
  label?: string;
}> = ({ sections, dark, label = 'More options' }) => {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const shown = sections.filter(s => s.items.length > 0);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const escape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setOpen(false); trigger.current?.focus(); }
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', escape); };
  }, [open]);

  if (shown.length === 0) return null;

  return (
    <div ref={box} className="relative shrink-0">
      <button
        ref={trigger}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        title={label}
        onClick={() => setOpen(o => !o)}
        className={clsx(
          'flex items-center justify-center w-8 h-8 rounded-md transition-colors',
          open
            ? (dark ? 'bg-white/15 text-white' : 'bg-gray-100 text-gray-900')
            : (dark ? 'text-white/80 hover:text-white hover:bg-white/10' : 'text-gray-600 hover:text-brand-blue hover:bg-gray-100'),
        )}
      >
        <MoreHorizontal className="w-4 h-4" />
      </button>
      {open && (
        <div role="menu" aria-label={label} className="absolute right-0 top-full mt-1 z-50 w-60 bg-white border border-gray-200 rounded-md shadow-lg py-1">
          {shown.map((section, i) => (
            <div key={section.label ?? i} className={clsx(i > 0 && 'border-t border-gray-100 mt-1 pt-1')}>
              {section.label && (
                <div className="px-3 pt-1.5 pb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400">{section.label}</div>
              )}
              {section.items.map(item => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.key}
                    type="button"
                    role={item.checked === undefined ? 'menuitem' : 'menuitemradio'}
                    aria-checked={item.checked}
                    aria-disabled={item.disabled || undefined}
                    title={item.title}
                    onClick={() => {
                      if (item.disabled) return;
                      setOpen(false);
                      if (trigger.current) item.onSelect(trigger.current);
                    }}
                    className={clsx(
                      'w-full flex items-center gap-2.5 px-3 py-1.5 text-left text-sm',
                      item.disabled
                        ? 'text-gray-300 cursor-not-allowed'
                        : item.danger ? 'text-red-600 hover:bg-red-50' : 'text-gray-700 hover:bg-gray-50',
                    )}
                  >
                    {Icon ? <Icon className={clsx('w-4 h-4 shrink-0', item.disabled ? 'text-gray-300' : item.danger ? 'text-red-500' : 'text-gray-400')} /> : <span className="w-4" />}
                    <span className="flex-1 truncate">{item.label}</span>
                    {item.checked && <Check className="w-4 h-4 text-brand-blue shrink-0" aria-hidden="true" />}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
