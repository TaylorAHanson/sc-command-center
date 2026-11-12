import React from 'react';
import {
    AppWindow, Eye, EyeOff, PencilLine, Share2, ShieldCheck, ShieldOff, Sparkles, Star, Users, type LucideIcon,
} from 'lucide-react';
import clsx from 'clsx';
import type { ViewRow } from '../../discover';
import { LEVEL_LABELS, STATE_LABELS } from '../../sharing';
import { formatWhen, relativeTime } from '../../schedules';
import type { HeaderMenuSection } from '../HeaderMenu';
import { ViewMenu } from './ViewMenu';

/** What a card can do. The page owns the state; a card only asks. */
export interface ViewActions {
    isAdmin: boolean;
    onFavorite: (row: ViewRow) => void;
    onHide: (row: ViewRow) => void;
    onFeature: (row: ViewRow) => void;
    onCertify: (row: ViewRow) => void;
    onShare: (row: ViewRow) => void;
}

/** Opens a view the way its link would, or in a new tab with a modifier held. */
const openView = (row: ViewRow, e: React.MouseEvent) => {
    if (window.getSelection()?.toString()) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey) {
        window.open(`${window.location.pathname}${window.location.search}${row.link}`, '_blank', 'noopener');
        return;
    }
    window.location.hash = row.link;
};

const menuSections = (row: ViewRow, a: ViewActions): HeaderMenuSection[] => {
    const general: HeaderMenuSection = {
        items: [
            row.hidden
                ? { key: 'unhide', label: 'Unhide', icon: Eye, title: 'Show it in the rails again', onSelect: () => a.onHide(row) }
                : { key: 'hide', label: 'Hide from rails', icon: EyeOff, title: 'Only for you. Search still finds it.', onSelect: () => a.onHide(row) },
        ],
    };
    if (a.isAdmin || row.access === 'MANAGE') {
        general.items.push({ key: 'share', label: 'Share…', icon: Share2, onSelect: () => a.onShare(row) });
    }
    if (!a.isAdmin) return [general];
    return [general, {
        label: 'Administrator',
        items: [
            row.featured
                ? { key: 'unfeature', label: 'Unfeature', icon: Sparkles, onSelect: () => a.onFeature(row) }
                : { key: 'feature', label: 'Feature', icon: Sparkles, title: 'Add it to the Featured rail, for everyone who can open it', onSelect: () => a.onFeature(row) },
            row.certified
                ? { key: 'uncertify', label: 'Uncertify', icon: ShieldOff, onSelect: () => a.onCertify(row) }
                : { key: 'certify', label: 'Certify', icon: ShieldCheck, title: 'Mark it as checked and trustworthy', onSelect: () => a.onCertify(row) },
        ],
    }];
};

const StarButton: React.FC<{ row: ViewRow; onToggle: (row: ViewRow) => void }> = ({ row, onToggle }) => (
    <button
        type="button"
        aria-pressed={row.favorite}
        aria-label={row.favorite ? `Remove ${row.name} from favorites` : `Add ${row.name} to favorites`}
        title={row.favorite ? 'Remove from favorites' : 'Add to favorites'}
        onClick={e => { e.stopPropagation(); onToggle(row); }}
        className={clsx(
            'flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-colors hover:bg-gray-100',
            row.favorite ? 'text-amber-500' : 'text-gray-300 hover:text-amber-500',
        )}
    >
        <Star className="h-4 w-4" fill={row.favorite ? 'currentColor' : 'none'} />
    </button>
);

const TONES = {
    featured: 'bg-amber-50 text-amber-800 border-amber-200',
    certified: 'bg-green-100 text-green-700 border-green-200',
    hidden: 'bg-gray-100 text-gray-600 border-gray-200',
} as const;

const Badge: React.FC<{ tone: keyof typeof TONES; icon: LucideIcon; title: string; children: React.ReactNode }> = ({ tone, icon: Icon, title, children }) => (
    <span title={title} className={clsx('inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide', TONES[tone])}>
        <Icon className="h-3 w-3" aria-hidden="true" />
        {children}
    </span>
);

const BADGES = [
    { key: 'featured', icon: Sparkles, title: 'Featured', color: 'text-amber-600' },
    { key: 'certified', icon: ShieldCheck, title: 'Certified', color: 'text-green-600' },
    { key: 'hidden', icon: EyeOff, title: 'Hidden from your rails', color: 'text-gray-400' },
] as const;

const Badges: React.FC<{ row: ViewRow; className?: string; compact?: boolean }> = ({ row, className, compact }) => {
    if (!row.featured && !row.certified && !row.hidden) return null;
    if (compact) {
        return (
            <span className={clsx('inline-flex shrink-0 items-center gap-1', className)}>
                {BADGES.filter(b => row[b.key]).map(({ key, icon: Icon, title, color }) => (
                    <span key={key} role="img" aria-label={title} title={title} className="inline-flex">
                        <Icon className={clsx('h-3.5 w-3.5', color)} aria-hidden="true" />
                    </span>
                ))}
            </span>
        );
    }
    return (
        <div className={clsx('flex flex-wrap items-center gap-1.5', className)}>
            {row.featured && <Badge tone="featured" icon={Sparkles} title="Picked by your administrators">Featured</Badge>}
            {row.certified && <Badge tone="certified" icon={ShieldCheck} title="Checked and vouched for by your administrators">Certified</Badge>}
            {row.hidden && <Badge tone="hidden" icon={EyeOff} title="You hid this from the rails. Unhide it from its ⋯ menu.">Hidden</Badge>}
        </div>
    );
};

/** The marks the sidebar puts on a view (a dot for unpublished work), plus how it opens and what the caller may do. */
const Marks: React.FC<{ row: ViewRow }> = ({ row }) => {
    const Level = row.access === 'MANAGE' ? PencilLine : Eye;
    return (
        <span className="inline-flex shrink-0 items-center gap-1.5 text-gray-400">
            {row.access === 'MANAGE' && row.state && row.state !== 'published' && (
                <span
                    className={clsx('h-1.5 w-1.5 rounded-full', row.state === 'draft_only' ? 'bg-slate-400' : 'bg-amber-400')}
                    title={STATE_LABELS[row.state]}
                    aria-label={STATE_LABELS[row.state]}
                />
            )}
            {row.presentation === 'standalone' && (
                <span role="img" aria-label="Opens on its own page" title="Opens on its own page" className="inline-flex">
                    <AppWindow className="h-3.5 w-3.5" aria-hidden="true" />
                </span>
            )}
            <span role="img" aria-label={LEVEL_LABELS[row.access]} title={LEVEL_LABELS[row.access]} className="inline-flex">
                <Level className="h-3.5 w-3.5" aria-hidden="true" />
            </span>
        </span>
    );
};

const viewersTitle = (n: number) => `${n.toLocaleString()} ${n === 1 ? 'person' : 'people'} opened it in the last 30 days`;
const favoritesTitle = (n: number) => `Starred by ${n.toLocaleString()} ${n === 1 ? 'person' : 'people'}`;

const Byline: React.FC<{ row: ViewRow }> = ({ row }) => {
    const parts = [row.owner, row.domain].filter(Boolean);
    if (parts.length === 0) return null;
    return <div className="mt-0.5 truncate text-xs text-gray-500">{parts.join(' · ')}</div>;
};

const Name: React.FC<{ row: ViewRow; className?: string }> = ({ row, className }) => (
    <a
        href={row.link}
        title={row.name}
        onClick={e => e.stopPropagation()}
        className={clsx('font-semibold text-gray-900 hover:text-brand-blue focus:outline-none focus-visible:underline', className)}
    >
        {row.name}
    </a>
);

export const ViewCard: React.FC<{ row: ViewRow; actions: ViewActions }> = ({ row, actions }) => {
    const updated = relativeTime(row.updated_at);
    return (
        <article
            onClick={e => openView(row, e)}
            className={clsx(
                'group flex h-full cursor-pointer flex-col rounded-xl border bg-white p-4 shadow-sm transition hover:shadow-md',
                row.hidden ? 'border-dashed border-gray-300' : 'border-gray-200 hover:border-brand-blue/50',
            )}
        >
            <div className="flex items-start gap-1">
                <div className="min-w-0 flex-1">
                    <Name row={row} className="line-clamp-2 text-[15px] leading-snug" />
                    <Byline row={row} />
                </div>
                <StarButton row={row} onToggle={actions.onFavorite} />
                <ViewMenu sections={menuSections(row, actions)} label={`More for ${row.name}`} />
            </div>
            <Badges row={row} className="mt-2" />
            {row.description && <p className="mt-2 line-clamp-2 text-sm text-gray-600">{row.description}</p>}
            <div className="mt-auto flex items-center gap-3 pt-3 text-xs text-gray-500">
                <span className="inline-flex items-center gap-1" title={viewersTitle(row.viewers_30d)}>
                    <Users className="h-3.5 w-3.5" aria-hidden="true" />{row.viewers_30d.toLocaleString()}
                </span>
                <span className="inline-flex items-center gap-1" title={favoritesTitle(row.favorites)}>
                    <Star className="h-3.5 w-3.5" aria-hidden="true" />{row.favorites.toLocaleString()}
                </span>
                {updated && <span className="truncate" title={`Updated ${formatWhen(row.updated_at)}`}>{updated}</span>}
                <span className="ml-auto"><Marks row={row} /></span>
            </div>
        </article>
    );
};

// Columns that matter least drop out first as the page narrows, so the name,
// the counts and the menu always fit without scrolling sideways.
const COL = {
    star: 'w-7 shrink-0',
    name: 'min-w-0 flex-1 overflow-hidden',
    owner: 'hidden w-40 shrink-0 truncate 2xl:block',
    domain: 'hidden w-32 shrink-0 truncate 2xl:block',
    updated: 'hidden w-24 shrink-0 truncate xl:block',
    count: 'w-12 shrink-0 text-right tabular-nums',
    end: 'flex w-20 shrink-0 items-center justify-end gap-1',
};

export const ViewListHeader: React.FC = () => (
    <div aria-hidden="true" className="flex items-center gap-3 border-b border-gray-200 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-gray-500">
        <span className={COL.star} />
        <span className={COL.name}>Name</span>
        <span className={COL.owner}>Owner</span>
        <span className={COL.domain}>Domain</span>
        <span className={COL.updated}>Updated</span>
        <span className={COL.count} title="People who opened it in the last 30 days">Viewers</span>
        <span className={COL.count} title="People who starred it">Stars</span>
        <span className={COL.end} />
    </div>
);

export const ViewListRow: React.FC<{ row: ViewRow; actions: ViewActions }> = ({ row, actions }) => (
    <div
        onClick={e => openView(row, e)}
        className={clsx('flex cursor-pointer items-center gap-3 border-b border-gray-100 px-3 py-2 text-sm last:border-b-0 hover:bg-gray-50', row.hidden && 'bg-gray-50/60')}
    >
        <span className={COL.star}><StarButton row={row} onToggle={actions.onFavorite} /></span>
        <div className={COL.name}>
            <div className="flex min-w-0 items-center gap-1.5">
                <Name row={row} className="truncate" />
                <Badges row={row} compact />
            </div>
            <div className="truncate text-xs text-gray-500">
                <span className="2xl:hidden">{[row.owner, row.domain].filter(Boolean).join(' · ')}{row.description && (row.owner || row.domain) && ' · '}</span>
                {row.description}
            </div>
        </div>
        <span className={clsx(COL.owner, 'text-gray-600')} title={row.owner ?? undefined}>{row.owner}</span>
        <span className={clsx(COL.domain, 'text-gray-600')} title={row.domain ?? undefined}>{row.domain}</span>
        <span className={clsx(COL.updated, 'text-gray-500')} title={row.updated_at ? `Updated ${formatWhen(row.updated_at)}` : undefined}>{relativeTime(row.updated_at)}</span>
        <span className={clsx(COL.count, 'text-gray-600')} title={viewersTitle(row.viewers_30d)}>{row.viewers_30d.toLocaleString()}</span>
        <span className={clsx(COL.count, 'text-gray-600')} title={favoritesTitle(row.favorites)}>{row.favorites.toLocaleString()}</span>
        <span className={COL.end}>
            <Marks row={row} />
            <ViewMenu sections={menuSections(row, actions)} label={`More for ${row.name}`} />
        </span>
    </div>
);
