import React, { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertCircle, AlertTriangle, Check, Globe, Link2, Loader2, Lock, Users, X } from 'lucide-react';
import clsx from 'clsx';
import {
    EVERYONE, LEVEL_LABELS, fetchAcl, fetchMe, initials, isServicePrincipal, samePrincipal, saveAcl,
    type Acl, type AclEntry, type Level, type Me, type ObjectType,
} from '../../sharing';
import { PrincipalPicker, type PickedPrincipal, type PrincipalPickerHandle } from './PrincipalPicker';
import { useDialog } from './useDialog';

export interface ShareDialogProps {
    objectType: ObjectType;
    objectId: string;
    name: string;
    /** Whether a published version exists; USE holders see nothing until there is one. */
    published: boolean;
    /** Absolute link to the object; omit to hide Copy link. */
    link?: string;
    onClose: () => void;
    /** Called with the server's list after every successful save. */
    onChanged?: (acl: Acl) => void;
}

type Status =
    | { kind: 'idle' } | { kind: 'saving' } | { kind: 'saved' }
    | { kind: 'error'; message: string } | { kind: 'note'; message: string };
type General = 'restricted' | 'USE' | 'MANAGE';

const LEVELS: Level[] = ['USE', 'MANAGE'];

// Literal class names so Tailwind keeps them.
const AVATAR_COLOURS = [
    'bg-blue-100 text-blue-700',
    'bg-emerald-100 text-emerald-700',
    'bg-violet-100 text-violet-700',
    'bg-amber-100 text-amber-800',
    'bg-rose-100 text-rose-700',
    'bg-cyan-100 text-cyan-800',
];

const colourOf = (principal: string) => {
    let h = 0;
    for (const ch of principal.toLowerCase()) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return AVATAR_COLOURS[h % AVATAR_COLOURS.length];
};

const Avatar: React.FC<{ entry: AclEntry }> = ({ entry }) => (
    entry.principal_type === 'group' ? (
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-600" aria-hidden="true">
            <Users size={15} />
        </span>
    ) : (
        <span
            className={clsx('flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold', colourOf(entry.principal))}
            aria-hidden="true"
        >
            {initials(entry.principal)}
        </span>
    )
);

const selectCls = 'rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-800 focus:outline-none focus:border-brand-blue focus:ring-2 focus:ring-brand-blue/20 disabled:border-transparent disabled:bg-transparent disabled:text-gray-500 disabled:appearance-none';

/**
 * Who can use or manage one view, widget or agent, in the shape of the Databricks
 * dashboard share dialog. Every change saves at once (`PUT /api/sharing/...`
 * replaces the whole list), optimistically, and rolls back if the server refuses.
 */
export const ShareDialog: React.FC<ShareDialogProps> = ({
    objectType, objectId, name, published, link, onClose, onChanged,
}) => {
    const [acl, setAcl] = useState<Acl | null>(null);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [loadNonce, setLoadNonce] = useState(0);
    const [me, setMe] = useState<Me | null>(null);
    const [text, setText] = useState('');
    const [addLevel, setAddLevel] = useState<Level>('USE');
    const [status, setStatus] = useState<Status>({ kind: 'idle' });
    const [copied, setCopied] = useState<'idle' | 'copied' | 'failed'>('idle');
    const pickerRef = useRef<PrincipalPickerHandle>(null);
    // Saves are queued so the server applies them in click order; each sends the
    // whole list as it stood after that click. `confirmed` is the last list the
    // server accepted, which is what a failed save rolls back to.
    const queueRef = useRef<Promise<unknown>>(Promise.resolve());
    const seqRef = useRef(0);
    const confirmedRef = useRef<Acl | null>(null);
    const savedTimer = useRef<number | undefined>(undefined);
    const copyTimer = useRef<number | undefined>(undefined);
    const titleId = useId();
    const { ref: dialogRef, onKeyDown } = useDialog<HTMLDivElement>(onClose);

    useEffect(() => {
        let cancelled = false;
        fetchAcl(objectType, objectId)
            .then(next => {
                if (cancelled) return;
                confirmedRef.current = next;
                setAcl(next);
                setLoadError(null);
            })
            .catch(e => { if (!cancelled) setLoadError(e?.message || String(e)); });
        return () => { cancelled = true; };
    }, [objectType, objectId, loadNonce]);

    useEffect(() => {
        fetchMe().then(setMe).catch(() => { /* "(you)" is cosmetic */ });
    }, []);

    useEffect(() => () => {
        window.clearTimeout(savedTimer.current);
        window.clearTimeout(copyTimer.current);
    }, []);

    const canManage = acl?.my_level === 'MANAGE';
    const entries = acl?.entries || [];
    const people = entries
        .filter(e => e.principal !== EVERYONE)
        .sort((a, b) => Number(samePrincipal(b.principal, acl?.owner)) - Number(samePrincipal(a.principal, acl?.owner)));
    const everyone = entries.find(e => e.principal === EVERYONE);
    const general: General = everyone ? everyone.level : 'restricted';
    const managers = entries.filter(e => e.level === 'MANAGE').length;

    const apply = (next: AclEntry[]) => {
        if (!acl) return;
        const seq = ++seqRef.current;
        setAcl({ ...acl, entries: next });
        setStatus({ kind: 'saving' });
        window.clearTimeout(savedTimer.current);
        queueRef.current = queueRef.current
            .catch(() => undefined)
            .then(() => saveAcl(objectType, objectId, next))
            .then(saved => {
                confirmedRef.current = saved;
                onChanged?.(saved);
                if (seq !== seqRef.current) return;
                setAcl(saved);
                setStatus({ kind: 'saved' });
                savedTimer.current = window.setTimeout(() => setStatus({ kind: 'idle' }), 2500);
            })
            .catch(e => {
                const message = e?.message || String(e);
                if (seq === seqRef.current && confirmedRef.current) setAcl(confirmedRef.current);
                setStatus({ kind: 'error', message });
            });
    };

    const setLevel = (entry: AclEntry, level: Level) =>
        apply(entries.map(e => (e.principal === entry.principal ? { ...e, level } : e)));

    const remove = (entry: AclEntry) => apply(entries.filter(e => e.principal !== entry.principal));

    const setGeneral = (next: General) => {
        const rest = entries.filter(e => e.principal !== EVERYONE);
        apply(next === 'restricted' ? rest : [...rest, { principal: EVERYONE, principal_type: 'all', level: next }]);
    };

    const grant = ({ principal, principal_type }: PickedPrincipal) => {
        const p = principal.trim();
        if (!p) return;
        setText('');
        if (p === EVERYONE) { setGeneral('USE'); return; }
        const existing = entries.find(e => samePrincipal(e.principal, p));
        if (existing) {
            if (existing.level !== addLevel) setLevel(existing, addLevel);
            else setStatus({ kind: 'note', message: `${existing.principal} already has access.` });
            return;
        }
        apply([...entries, { principal: p, principal_type, level: addLevel }]);
    };

    const copyLink = async () => {
        if (!link) return;
        window.clearTimeout(copyTimer.current);
        try {
            await navigator.clipboard.writeText(link);
            setCopied('copied');
        } catch {
            setCopied('failed');
        }
        copyTimer.current = window.setTimeout(() => setCopied('idle'), 2000);
    };

    // The server refuses a list with no manager unless an app admin saves it;
    // saying so here beats an optimistic change that snaps back.
    const soleManager = (entry: AclEntry) => entry.level === 'MANAGE' && managers <= 1 && !me?.is_admin;

    const statusLine = (
        <span className="flex items-center gap-1 text-xs" aria-live="polite">
            {status.kind === 'saving' && <><Loader2 size={12} className="animate-spin text-gray-400" /><span className="text-gray-500">Saving…</span></>}
            {status.kind === 'saved' && <><Check size={12} className="text-emerald-600" /><span className="text-emerald-700">Saved</span></>}
        </span>
    );

    return createPortal(
        <div
            className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
            onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}
        >
            <div
                ref={dialogRef}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                tabIndex={-1}
                onKeyDown={onKeyDown}
                className="w-full max-w-lg rounded-xl bg-white shadow-2xl animate-in fade-in zoom-in-95 duration-150 focus:outline-none"
            >
                <div className="flex items-start gap-3 px-6 pt-5 pb-3">
                    <h2 id={titleId} className="min-w-0 flex-1 truncate text-lg font-semibold text-gray-900" title={name}>
                        Share ‘{name}’
                    </h2>
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Close"
                        className="-mr-2 rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                    >
                        <X size={18} />
                    </button>
                </div>

                <div className="px-6 pb-5">
                    {!acl && !loadError && (
                        <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-500">
                            <Loader2 size={16} className="animate-spin" /> Loading who has access…
                        </div>
                    )}
                    {!acl && loadError && (
                        <div role="alert" className="my-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                            <AlertCircle size={16} className="mt-0.5 shrink-0" />
                            <span className="flex-1">Couldn’t load sharing: {loadError}</span>
                            <button type="button" onClick={() => { setLoadError(null); setLoadNonce(n => n + 1); }} className="font-medium underline">
                                Retry
                            </button>
                        </div>
                    )}

                    {acl && (
                        <>
                            {canManage ? (
                                <div className="flex items-start gap-2">
                                    <PrincipalPicker
                                        ref={pickerRef}
                                        value={text}
                                        onChange={setText}
                                        onSubmit={grant}
                                        exclude={people.map(p => p.principal)}
                                        allowEveryone
                                        autoFocus
                                        className="min-w-0 flex-1"
                                    />
                                    <select
                                        aria-label="Access to give"
                                        value={addLevel}
                                        onChange={e => setAddLevel(e.target.value as Level)}
                                        className={clsx(selectCls, 'py-2')}
                                    >
                                        {LEVELS.map(l => <option key={l} value={l}>{LEVEL_LABELS[l]}</option>)}
                                    </select>
                                    <button
                                        type="button"
                                        onClick={() => { if (!pickerRef.current?.submit()) pickerRef.current?.focus(); }}
                                        disabled={!text.trim()}
                                        className="rounded-lg bg-brand-blue px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-navy disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                        Add
                                    </button>
                                </div>
                            ) : (
                                <p className="flex items-center gap-1.5 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600">
                                    <Lock size={12} className="shrink-0 text-gray-400" />
                                    You can see who has access. Someone who can manage it can change this.
                                </p>
                            )}

                            {(status.kind === 'error' || status.kind === 'note') && (
                                <p
                                    role={status.kind === 'error' ? 'alert' : 'status'}
                                    className={clsx('mt-2 flex items-start gap-1.5 text-xs', status.kind === 'error' ? 'text-red-600' : 'text-gray-600')}
                                >
                                    {status.kind === 'error' && <AlertCircle size={13} className="mt-px shrink-0" />}
                                    <span className="flex-1">{status.message}</span>
                                    <button type="button" aria-label="Dismiss" onClick={() => setStatus({ kind: 'idle' })} className="opacity-60 hover:opacity-100">
                                        <X size={12} />
                                    </button>
                                </p>
                            )}

                            {!published && (
                                <p className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                                    <AlertTriangle size={14} className="mt-px shrink-0 text-amber-500" />
                                    Not published yet — people with Can use will see it once you publish.
                                </p>
                            )}

                            <div className="mt-4 flex items-center justify-between">
                                <h3 className="text-sm font-semibold text-gray-800">People with access</h3>
                                {statusLine}
                            </div>
                            <ul className="mt-1 max-h-64 overflow-y-auto -mx-2" aria-label="People with access">
                                {people.length === 0 && (
                                    <li className="px-2 py-3 text-sm text-gray-500">Nobody yet. App admins can still manage it.</li>
                                )}
                                {people.map(entry => {
                                    const isMe = samePrincipal(entry.principal, me?.username);
                                    const isOwner = samePrincipal(entry.principal, acl.owner);
                                    const locked = soleManager(entry);
                                    return (
                                        <li key={entry.principal} className="flex items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-gray-50">
                                            <Avatar entry={entry} />
                                            <div className="min-w-0 flex-1">
                                                <div className="flex items-center gap-1.5 text-sm text-gray-900">
                                                    <span className="truncate" title={entry.principal}>{entry.principal}</span>
                                                    {isMe && <span className="shrink-0 text-gray-500">(you)</span>}
                                                    {isOwner && (
                                                        <span className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-gray-600">
                                                            Owner
                                                        </span>
                                                    )}
                                                </div>
                                                {entry.principal_type === 'group' && <div className="text-xs text-gray-500">Group</div>}
                                                {entry.principal_type === 'user' && isServicePrincipal(entry.principal) && (
                                                    <div className="text-xs text-gray-500">Service principal</div>
                                                )}
                                            </div>
                                            <select
                                                aria-label={`Access for ${entry.principal}`}
                                                value={entry.level}
                                                disabled={!canManage || locked}
                                                title={locked ? 'Someone must be able to manage it' : undefined}
                                                onChange={e => setLevel(entry, e.target.value as Level)}
                                                className={selectCls}
                                            >
                                                {LEVELS.map(l => <option key={l} value={l}>{LEVEL_LABELS[l]}</option>)}
                                            </select>
                                            {canManage && (
                                                <button
                                                    type="button"
                                                    onClick={() => remove(entry)}
                                                    disabled={locked}
                                                    aria-label={`Remove ${entry.principal}`}
                                                    title={locked ? 'Someone must be able to manage it' : 'Remove'}
                                                    className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-gray-400"
                                                >
                                                    <X size={15} />
                                                </button>
                                            )}
                                        </li>
                                    );
                                })}
                            </ul>
                            <p className="mt-1 text-xs text-gray-400">App admins can always manage.</p>

                            <h3 className="mt-5 text-sm font-semibold text-gray-800">General access</h3>
                            <div className="mt-2 flex items-center gap-3">
                                <span
                                    className={clsx(
                                        'flex h-8 w-8 shrink-0 items-center justify-center rounded-full',
                                        general === 'restricted' ? 'bg-gray-100 text-gray-500' : 'bg-emerald-100 text-emerald-700',
                                    )}
                                    aria-hidden="true"
                                >
                                    {general === 'restricted' ? <Lock size={15} /> : <Globe size={15} />}
                                </span>
                                <div className="min-w-0 flex-1">
                                    <select
                                        aria-label="General access"
                                        value={general}
                                        disabled={!canManage}
                                        onChange={e => setGeneral(e.target.value as General)}
                                        className={clsx(selectCls, '-ml-2 border-transparent font-medium hover:bg-gray-50')}
                                    >
                                        <option value="restricted">Only people with access</option>
                                        <option value="USE">Everyone in this app can use</option>
                                        {general === 'MANAGE' && <option value="MANAGE">Everyone in this app can manage</option>}
                                    </select>
                                    <p className="text-xs text-gray-500">
                                        {general === 'restricted'
                                            ? 'Only the people and groups above can open it.'
                                            : 'Anyone who signs in to this app can open it.'}
                                    </p>
                                </div>
                            </div>
                        </>
                    )}
                </div>

                <div className="flex items-center gap-3 rounded-b-xl border-t border-gray-100 bg-gray-50 px-6 py-3">
                    {link && (
                        <div className="flex min-w-0 flex-1 items-center gap-2">
                            <button
                                type="button"
                                onClick={copyLink}
                                className="flex shrink-0 items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-brand-blue transition-colors hover:bg-blue-50"
                            >
                                {copied === 'copied' ? <Check size={14} /> : <Link2 size={14} />}
                                {copied === 'copied' ? 'Copied' : 'Copy link'}
                            </button>
                            <span className="truncate text-xs text-gray-500" aria-live="polite">
                                {copied === 'failed' ? 'Couldn’t copy — your browser blocked it.' : 'Only people with access can open it'}
                            </span>
                        </div>
                    )}
                    <button
                        type="button"
                        onClick={onClose}
                        className="ml-auto rounded-lg bg-brand-blue px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-brand-navy"
                    >
                        Done
                    </button>
                </div>
            </div>
        </div>,
        document.body,
    );
};

export default ShareDialog;
