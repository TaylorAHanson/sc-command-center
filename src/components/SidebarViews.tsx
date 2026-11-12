import React, { useRef, useState } from 'react';
import { Clock, GripVertical, Layers, Pencil, Plus, Sparkles, Star, Telescope, X } from 'lucide-react';
import clsx from 'clsx';
import { useDashboardStore } from '../store/dashboardStore';
import { discoverHref } from '../discover';
import { hrefOf, type SidebarRow } from '../workingSet';
import { STATE_LABELS } from '../sharing';
import { AccessIcon } from './sharing';
import { SidebarSearch } from './SidebarSearch';

/** How widely a sidebar view is shared, and whether its draft has changes nobody else sees yet. */
const ViewMarks: React.FC<{ row: SidebarRow; selected: boolean }> = ({ row, selected }) => (
  <span className="flex items-center gap-1.5 shrink-0">
    {row.access === 'MANAGE' && row.state && row.state !== 'published' && (
      <span
        className={clsx('h-1.5 w-1.5 rounded-full', row.state === 'draft_only' ? 'bg-slate-400' : 'bg-amber-400')}
        title={STATE_LABELS[row.state]}
        aria-label={STATE_LABELS[row.state]}
      />
    )}
    <AccessIcon summary={row.sharing ?? 'private'} size={12} className={selected ? 'text-white/70' : 'text-gray-500'} />
  </span>
);

const Heading: React.FC<{ id: string; icon: React.ElementType; children: React.ReactNode }> = ({ id, icon: Icon, children }) => (
  <h2 id={id} className="text-xs font-semibold text-gray-400 uppercase mb-2 px-1 flex items-center gap-2">
    <Icon className="w-3 h-3" aria-hidden />
    {children}
  </h2>
);

const Hint: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <p className="text-xs text-gray-500 px-1">{children}</p>
);

const RowAction: React.FC<{
  label: string;
  onClick: () => void;
  selected: boolean;
  danger?: boolean;
  children: React.ReactNode;
}> = ({ label, onClick, selected, danger, children }) => (
  <button
    type="button"
    onClick={e => { e.preventDefault(); e.stopPropagation(); onClick(); }}
    aria-label={label}
    title={label}
    className={clsx(
      'p-1 rounded transition-colors',
      selected ? 'text-white/80' : 'text-gray-400',
      danger ? 'hover:bg-red-500/20 hover:text-red-300' : 'hover:bg-white/10 hover:text-white',
    )}
  >
    {children}
  </button>
);

const StarAction: React.FC<{ row: SidebarRow; selected: boolean; onToggle: (row: SidebarRow) => void }> = ({ row, selected, onToggle }) => (
  // A view never published isn't in the catalog favorites are listed from.
  row.state === 'draft_only' ? null : (
    <RowAction
      label={row.favorite ? `Remove ‘${row.name}’ from favorites` : `Add ‘${row.name}’ to favorites`}
      onClick={() => onToggle(row)}
      selected={selected}
    >
      <Star className={clsx('w-3.5 h-3.5', row.favorite && 'fill-current text-amber-400')} />
    </RowAction>
  )
);

/**
 * One view: a link to it, so it opens like any link (and in a new tab with a
 * modifier), its marks, and actions that show on hover or keyboard focus.
 */
const ViewLink: React.FC<{
  row: SidebarRow;
  selected: boolean;
  onOpen: () => void;
  lead?: React.ReactNode;
  actions: React.ReactNode;
  onKeyDown?: (e: React.KeyboardEvent<HTMLAnchorElement>) => void;
  title?: string;
}> = ({ row, selected, onOpen, lead, actions, onKeyDown, title }) => (
  <>
    <a
      href={hrefOf(row)}
      onClick={onOpen}
      onKeyDown={onKeyDown}
      aria-current={selected ? 'page' : undefined}
      title={title ?? (row.owner ? `${row.name} · ${row.owner}` : row.name)}
      className={clsx(
        'w-full px-3 py-2 rounded-md text-sm transition-colors flex items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue',
        selected ? 'bg-brand-blue text-white' : 'text-gray-300 hover:bg-gray-800 hover:text-white',
      )}
    >
      {lead}
      <span className="truncate flex-1">{row.name}</span>
      <span className="group-hover:invisible group-focus-within:invisible">
        <ViewMarks row={row} selected={selected} />
      </span>
    </a>
    <div className="absolute right-2 top-1/2 -translate-y-1/2 hidden group-hover:flex group-focus-within:flex items-center gap-0.5">
      {actions}
    </div>
  </>
);

const footLink = 'w-full px-3 py-2 rounded-md text-sm text-gray-400 hover:bg-gray-800 hover:text-white transition-colors flex items-center gap-2';

/**
 * The sidebar's views: search, Favorites, Recent and My views, each a short
 * list from the working set (`GET /api/apps/`), with the rest one link away on
 * the Discover page. Nothing here holds a view's spec.
 */
export const SidebarViews: React.FC<{
  /** The view on screen, when a view is what's on screen. */
  selectedId: string | null;
  /** A row or link was chosen: whatever covers the canvas should give way. */
  onOpen: () => void;
  onNewView: () => void;
  /** Delete or archive one of the caller's views, once they confirm. */
  onRemove: (row: SidebarRow) => void;
  onNotice: (message: string) => void;
  searchRef?: React.Ref<HTMLInputElement>;
  /** Classes that light up Browse views for the Welcome panel. */
  browseSpot?: string | false;
}> = ({ selectedId, onOpen, onNewView, onRemove, onNotice, searchRef, browseSpot }) => {
  const { sidebar, sidebarStatus, refreshSidebar, toggleFavorite, moveFavorite, removeFromRecent, renameApp } = useDashboardStore();
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null);
  // Enter and Escape end the rename, and the blur that can follow must not end it
  // again from its stale closure: Escape would rename after all.
  const editingRef = useRef<{ id: string; name: string } | null>(null);
  const [dragged, setDragged] = useState<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  const ready = sidebarStatus === 'ready';

  const toggle = async (row: SidebarRow) => {
    const refusal = await toggleFavorite(row.id);
    if (refusal) onNotice(refusal);
  };
  const leaveRecent = async (row: SidebarRow) => {
    const refusal = await removeFromRecent(row.id);
    if (refusal) onNotice(refusal);
  };
  const edit = (next: { id: string; name: string } | null) => {
    editingRef.current = next;
    setEditing(next);
  };
  const finishRename = (save: boolean) => {
    const done = editingRef.current;
    edit(null);
    if (save && done?.name.trim()) renameApp(done.id, done.name);
  };
  const endDrag = () => {
    setDragged(null);
    setOver(null);
  };

  return (
    <div className="p-3 border-b border-gray-700 space-y-4">
      <SidebarSearch ref={searchRef} onOpen={onOpen} />

      {sidebarStatus === 'failed' && (
        <p className="text-xs text-gray-400 px-1" role="alert">
          Your views couldn’t be loaded.{' '}
          <button type="button" onClick={() => refreshSidebar()} className="text-brand-blue hover:underline">Try again</button>
        </p>
      )}

      <section aria-labelledby="sidebar-favorites">
        <Heading id="sidebar-favorites" icon={Star}>Favorites</Heading>
        <ul className="space-y-1">
          {sidebar.favorites.map((row, index) => {
            const selected = selectedId === row.id;
            return (
              <li
                key={row.id}
                className={clsx(
                  'group relative',
                  dragged === index && 'opacity-50',
                  over === index && dragged !== null && dragged !== index && 'border-t-2 border-brand-blue',
                )}
                draggable
                onDragStart={e => {
                  setDragged(index);
                  e.dataTransfer.effectAllowed = 'move';
                  e.dataTransfer.setData('text/plain', row.id);
                }}
                onDragEnd={endDrag}
                onDragOver={e => {
                  if (dragged === null) return;
                  e.preventDefault();
                  e.dataTransfer.dropEffect = 'move';
                  if (dragged !== index) setOver(index);
                }}
                onDragLeave={() => { if (over === index) setOver(null); }}
                onDrop={e => {
                  e.preventDefault();
                  if (dragged !== null && dragged !== index) moveFavorite(dragged, index);
                  endDrag();
                }}
              >
                <ViewLink
                  row={row}
                  selected={selected}
                  onOpen={onOpen}
                  onKeyDown={e => {
                    if (!e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
                    e.preventDefault();
                    moveFavorite(index, index + (e.key === 'ArrowUp' ? -1 : 1));
                  }}
                  lead={(
                    <GripVertical
                      aria-hidden
                      className={clsx(
                        'w-4 h-4 flex-shrink-0 cursor-move -ml-1',
                        selected ? 'text-white/60' : 'text-gray-500 opacity-0 group-hover:opacity-100 transition-opacity',
                      )}
                    />
                  )}
                  title={`${row.name}. Drag, or Alt+↑ and Alt+↓, to reorder.`}
                  actions={<StarAction row={row} selected={selected} onToggle={toggle} />}
                />
              </li>
            );
          })}
        </ul>
        {sidebar.moreFavorites && (
          <a href={discoverHref({ scope: 'favorites', sort: 'favorites' })} onClick={onOpen} className={footLink}>
            All favorites
          </a>
        )}
        {ready && sidebar.favorites.length === 0 && <Hint>Star a view to keep it here.</Hint>}
      </section>

      <section aria-labelledby="sidebar-recent">
        <Heading id="sidebar-recent" icon={Clock}>Recent</Heading>
        <ul className="space-y-1">
          {sidebar.recent.map(row => {
            const selected = selectedId === row.id;
            return (
              <li key={row.id} className="group relative">
                <ViewLink
                  row={row}
                  selected={selected}
                  onOpen={onOpen}
                  actions={(
                    <>
                      <StarAction row={row} selected={selected} onToggle={toggle} />
                      <RowAction label={`Remove ‘${row.name}’ from Recent`} onClick={() => leaveRecent(row)} selected={selected}>
                        <X className="w-3.5 h-3.5" />
                      </RowAction>
                    </>
                  )}
                />
              </li>
            );
          })}
        </ul>
        {ready && sidebar.recent.length === 0 && <Hint>Views you open appear here.</Hint>}
      </section>

      <section aria-labelledby="sidebar-mine">
        <Heading id="sidebar-mine" icon={Layers}>My views</Heading>
        <ul className="space-y-1">
          {sidebar.mine.map(row => {
            const selected = selectedId === row.id;
            if (editing?.id === row.id) {
              return (
                <li key={row.id} className="px-3 py-2 rounded-md text-sm bg-gray-800">
                  <input
                    type="text"
                    value={editing.name}
                    onChange={e => edit({ id: row.id, name: e.target.value })}
                    onKeyDown={e => {
                      if (e.key === 'Enter') finishRename(true);
                      else if (e.key === 'Escape') finishRename(false);
                    }}
                    onBlur={() => finishRename(true)}
                    autoFocus
                    aria-label={`New name for ‘${row.name}’`}
                    className="w-full bg-gray-700 text-white px-2 py-1 rounded border border-gray-600 focus:outline-none focus:ring-2 focus:ring-brand-blue"
                  />
                </li>
              );
            }
            const manages = row.access === 'MANAGE';
            const archives = (row.sharing ?? 'private') !== 'private';
            return (
              <li key={row.id} className="group relative">
                <ViewLink
                  row={row}
                  selected={selected}
                  onOpen={onOpen}
                  actions={(
                    <>
                      <StarAction row={row} selected={selected} onToggle={toggle} />
                      {manages && (
                        <RowAction label={`Rename ‘${row.name}’`} onClick={() => edit({ id: row.id, name: row.name })} selected={selected}>
                          <Pencil className="w-3.5 h-3.5" />
                        </RowAction>
                      )}
                      {manages && (
                        <RowAction
                          label={archives ? `Archive ‘${row.name}’` : `Delete ‘${row.name}’`}
                          onClick={() => onRemove(row)}
                          selected={selected}
                          danger
                        >
                          <X className="w-3.5 h-3.5" />
                        </RowAction>
                      )}
                    </>
                  )}
                />
              </li>
            );
          })}
        </ul>
        {sidebar.mineTotal > sidebar.mine.length && (
          <a href={discoverHref({ scope: 'mine', sort: 'updated' })} onClick={onOpen} className={footLink}>
            All my views ({sidebar.mineTotal})
          </a>
        )}
        {ready && sidebar.mine.length === 0 && <Hint>Views you make appear here.</Hint>}
      </section>

      <div className="space-y-1">
        {sidebar.newForYou > 0 && (
          <a href={discoverHref({ rail: 'new_for_you' })} onClick={onOpen} className={footLink}>
            <Sparkles className="w-4 h-4" aria-hidden />
            <span className="flex-1">New for you</span>
            <span className="rounded-full bg-brand-blue px-1.5 text-xs font-semibold text-white" aria-label={`${sidebar.newForYou} new`}>
              {sidebar.newForYou}
            </span>
          </a>
        )}
        <button
          type="button"
          onClick={onNewView}
          title="A new view only you can see until you share and publish it"
          className={footLink}
        >
          <Plus className="w-4 h-4" aria-hidden />
          <span>New view</span>
        </button>
        <a href={discoverHref()} onClick={onOpen} className={clsx(footLink, browseSpot)}>
          <Telescope className="w-4 h-4" aria-hidden />
          <span>Browse views</span>
        </a>
      </div>
    </div>
  );
};
