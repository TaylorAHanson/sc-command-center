import { useCallback, useEffect, useRef } from 'react';
import type React from 'react';

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Focus handling for a modal: focus moves in on open (`[data-autofocus]` first),
 * Tab stays inside, Escape closes, and focus goes back where it was on close.
 *
 * Escape is handled on the dialog rather than the document so a child that
 * consumes it (an open typeahead list) can stop it with `stopPropagation`.
 */
export function useDialog<T extends HTMLElement>(onClose: () => void, closeDisabled = false) {
    const ref = useRef<T>(null);

    useEffect(() => {
        const previous = document.activeElement as HTMLElement | null;
        const root = ref.current;
        const target = root?.querySelector<HTMLElement>('[data-autofocus]')
            || root?.querySelector<HTMLElement>(FOCUSABLE)
            || root;
        target?.focus();
        return () => { previous?.focus?.(); };
    }, []);

    const onKeyDown = useCallback((e: React.KeyboardEvent) => {
        if (e.key === 'Escape') {
            e.stopPropagation();
            if (!closeDisabled) onClose();
            return;
        }
        if (e.key !== 'Tab' || !ref.current) return;
        const items = Array.from(ref.current.querySelectorAll<HTMLElement>(FOCUSABLE))
            .filter(el => el.offsetParent !== null);
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }, [onClose, closeDisabled]);

    return { ref, onKeyDown };
}
