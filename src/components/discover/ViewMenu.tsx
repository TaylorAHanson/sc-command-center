import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { MoreHorizontal } from 'lucide-react';
import clsx from 'clsx';
import type { HeaderMenuSection } from '../HeaderMenu';

const WIDTH = 224;
/** Room the tallest menu needs below its trigger before it opens upward instead. */
const ROOM_BELOW = 300;

type Place = { left: number; top?: number; bottom?: number };

/**
 * A view card's "⋯" menu. It looks like HeaderMenu but is drawn on `document.body`
 * at the trigger's position, because a rail scrolls sideways and its overflow
 * would clip a menu drawn inside the card. It closes on any scroll for the same
 * reason: the card moves and the menu wouldn't.
 *
 * Clicks inside stop at the menu. React carries a portal's events up its own
 * tree, so they would otherwise reach the card and open the view.
 */
export const ViewMenu: React.FC<{ sections: HeaderMenuSection[]; label: string }> = ({ sections, label }) => {
    const [place, setPlace] = useState<Place | null>(null);
    const trigger = useRef<HTMLButtonElement>(null);
    const menu = useRef<HTMLDivElement>(null);
    const shown = sections.filter(s => s.items.length > 0);
    const open = place !== null;

    useEffect(() => {
        if (!open) return;
        const close = () => setPlace(null);
        const outside = (e: MouseEvent) => {
            const target = e.target as Node;
            if (!menu.current?.contains(target) && !trigger.current?.contains(target)) close();
        };
        const escape = (e: KeyboardEvent) => {
            if (e.key === 'Escape') { close(); trigger.current?.focus(); }
        };
        document.addEventListener('mousedown', outside);
        document.addEventListener('keydown', escape);
        window.addEventListener('scroll', close, true);
        window.addEventListener('resize', close);
        return () => {
            document.removeEventListener('mousedown', outside);
            document.removeEventListener('keydown', escape);
            window.removeEventListener('scroll', close, true);
            window.removeEventListener('resize', close);
        };
    }, [open]);

    if (shown.length === 0) return null;

    const toggle = (e: React.MouseEvent<HTMLButtonElement>) => {
        e.stopPropagation();
        if (open) { setPlace(null); return; }
        const r = e.currentTarget.getBoundingClientRect();
        const left = Math.max(8, Math.min(window.innerWidth - WIDTH - 8, r.right - WIDTH));
        setPlace(window.innerHeight - r.bottom < ROOM_BELOW && r.top > ROOM_BELOW
            ? { left, bottom: window.innerHeight - r.top + 4 }
            : { left, top: r.bottom + 4 });
    };

    return (
        <>
            <button
                ref={trigger}
                type="button"
                aria-haspopup="menu"
                aria-expanded={open}
                aria-label={label}
                title={label}
                onClick={toggle}
                className={clsx(
                    'flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-colors',
                    open ? 'bg-gray-100 text-gray-900' : 'text-gray-400 hover:bg-gray-100 hover:text-brand-blue',
                )}
            >
                <MoreHorizontal className="h-4 w-4" />
            </button>
            {place && createPortal(
                <div
                    ref={menu}
                    role="menu"
                    aria-label={label}
                    style={{ position: 'fixed', width: WIDTH, ...place }}
                    onClick={e => e.stopPropagation()}
                    className="z-50 rounded-md border border-gray-200 bg-white py-1 shadow-lg"
                >
                    {shown.map((section, i) => (
                        <div key={section.label ?? i} className={clsx(i > 0 && 'mt-1 border-t border-gray-100 pt-1')}>
                            {section.label && (
                                <div className="px-3 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-gray-400">{section.label}</div>
                            )}
                            {section.items.map(item => {
                                const Icon = item.icon;
                                return (
                                    <button
                                        key={item.key}
                                        type="button"
                                        role="menuitem"
                                        aria-disabled={item.disabled || undefined}
                                        title={item.title}
                                        onClick={() => {
                                            if (item.disabled) return;
                                            setPlace(null);
                                            if (trigger.current) item.onSelect(trigger.current);
                                        }}
                                        className={clsx(
                                            'flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-sm',
                                            item.disabled
                                                ? 'cursor-not-allowed text-gray-300'
                                                : item.danger ? 'text-red-600 hover:bg-red-50' : 'text-gray-700 hover:bg-gray-50',
                                        )}
                                    >
                                        {Icon ? <Icon className={clsx('h-4 w-4 shrink-0', item.disabled ? 'text-gray-300' : 'text-gray-400')} /> : <span className="w-4" />}
                                        <span className="flex-1 truncate">{item.label}</span>
                                    </button>
                                );
                            })}
                        </div>
                    ))}
                </div>,
                document.body,
            )}
        </>
    );
};
