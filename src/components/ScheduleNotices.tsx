import React, { useEffect, useState } from 'react';
import { AlertCircle, AlertTriangle, CheckCircle2, X } from 'lucide-react';
import { findCapability, useCapabilities } from '../capabilities';
import {
    bannerReason, clearOAuthOutcome, expiresIn, fetchConnection, listSchedules, pendingOAuthOutcome,
    type OAuthOutcome,
} from '../schedules';

const DISMISSED_KEY = 'schedule-banner-dismissed';

type Banner = { reason: 'reconnect' | 'expiring'; expiresAt: string | null };

const readDismissed = (): string | null => {
    try {
        return window.sessionStorage.getItem(DISMISSED_KEY);
    } catch {
        return null;
    }
};

/**
 * The strip above the header when scheduled work is about to stop: someone
 * has active schedules and their connection needs reconnecting or ends within
 * a week. One look per page load, at most a list of schedules and the status,
 * and none at all where scheduling isn't set up or runs without connections.
 * Dismissing it lasts for the browser tab's session.
 */
export const ScheduleBanner: React.FC<{ hidden?: boolean }> = ({ hidden = false }) => {
    const scheduling = findCapability(useCapabilities(), 'scheduling');
    const watch = !!scheduling?.available && scheduling.mode !== 'dev';
    const [banner, setBanner] = useState<Banner | null>(null);
    const [dismissed, setDismissed] = useState(readDismissed);

    useEffect(() => {
        if (!watch) return;
        let live = true;
        void (async () => {
            const list = await listSchedules(false);
            if (!live || !list.ok) return;
            const { schedules } = list.data;
            if (bannerReason(null, schedules) === 'reconnect') {
                setBanner({ reason: 'reconnect', expiresAt: null });
                return;
            }
            if (!schedules.some(s => s.status === 'active')) return;
            const status = await fetchConnection();
            if (!live || !status.ok) return;
            const reason = bannerReason(status.data, schedules);
            if (reason) setBanner({ reason, expiresAt: status.data.expires_at });
        })();
        return () => { live = false; };
    }, [watch]);

    if (!banner || hidden || dismissed === banner.reason) return null;

    const dismiss = () => {
        try {
            window.sessionStorage.setItem(DISMISSED_KEY, banner.reason);
        } catch {
            /* private mode: it comes back on the next page load */
        }
        setDismissed(banner.reason);
    };

    const text = banner.reason === 'reconnect'
        ? 'Your schedules are waiting: reconnect your account so they can run as you.'
        : `The connection your schedules run on ${expiresIn(banner.expiresAt) || 'expires soon'}. Reconnect to keep them running.`;

    return (
        <div role="status" className="flex items-center gap-3 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900">
            <AlertTriangle size={15} className="shrink-0 text-amber-600" aria-hidden="true" />
            <span className="min-w-0 flex-1">{text}</span>
            <a href="#/schedules" className="shrink-0 font-semibold underline-offset-2 hover:underline">
                {banner.reason === 'reconnect' ? 'Reconnect' : 'My schedules'}
            </a>
            <button
                type="button"
                onClick={dismiss}
                aria-label="Dismiss for this session"
                className="shrink-0 rounded p-0.5 text-amber-700 hover:bg-amber-100 hover:text-amber-900"
            >
                <X size={15} />
            </button>
        </div>
    );
};

/**
 * What came of connecting an account, shown once wherever the sign-in returned
 * to. `takeOAuthOutcome` in `main.tsx` has already taken it out of the address.
 */
export const OAuthOutcomeToast: React.FC = () => {
    const [outcome, setOutcome] = useState<OAuthOutcome | null>(pendingOAuthOutcome);

    useEffect(() => {
        if (!outcome) return;
        const timer = window.setTimeout(() => {
            clearOAuthOutcome();
            setOutcome(null);
        }, outcome.connected ? 6000 : 15000);
        return () => window.clearTimeout(timer);
    }, [outcome]);

    if (!outcome) return null;

    const dismiss = () => {
        clearOAuthOutcome();
        setOutcome(null);
    };

    return (
        <div
            role={outcome.connected ? 'status' : 'alert'}
            className={`fixed bottom-5 left-1/2 z-[80] flex w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2 items-start gap-3 rounded-xl border bg-white px-4 py-3 text-sm shadow-xl ${outcome.connected
                ? 'border-emerald-200'
                : 'border-red-200'}`}
        >
            {outcome.connected
                ? <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-emerald-600" aria-hidden="true" />
                : <AlertCircle size={18} className="mt-0.5 shrink-0 text-red-600" aria-hidden="true" />}
            <div className="min-w-0 flex-1">
                <p className="font-semibold text-gray-900">{outcome.connected ? 'Your account is connected' : 'Your account wasn’t connected'}</p>
                <p className="text-gray-700">{outcome.connected ? 'Your schedules can now run as you.' : outcome.message}</p>
            </div>
            <button type="button" onClick={dismiss} aria-label="Dismiss" className="-mr-1 rounded p-0.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600">
                <X size={16} />
            </button>
        </div>
    );
};
