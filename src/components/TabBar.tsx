import React, { useEffect, useRef, useState } from 'react';
import { FileText, LayoutGrid, Plus, X } from 'lucide-react';
import clsx from 'clsx';
import { ConfirmModal } from './ConfirmModal';
import { useDashboardStore } from '../store/dashboardStore';
import { layoutSwitch, MAX_NAME_LENGTH, MAX_TABS, navStyle, tabLabel, type TabLayout } from '../store/appSpec';

const NEW_TAB = '\u0000new';

const LAYOUT_CHOICES: { layout: TabLayout; label: string; hint: string; icon: typeof LayoutGrid }[] = [
  { layout: 'canvas', label: 'Cards on a grid', hint: 'Several widgets, each in a card you can move and resize', icon: LayoutGrid },
  { layout: 'page', label: 'Full page', hint: 'One widget that fills the whole tab', icon: FileText },
];

/** The names a view's tabs get when it first has two: what the view was, and what was added. */
export interface NewTabNames { name: string; first?: string }

/**
 * A button that asks which kind of tab to add. With `naming`, it then asks for
 * the new tab's name in the same menu, and for the existing tab's too when it has
 * none yet: a view's first two tabs appear at once, so both are named at once.
 */
export const AddTabMenu: React.FC<{
  onChoose: (layout: TabLayout, names?: NewTabNames) => void;
  button: (open: (e: React.MouseEvent<HTMLElement>) => void) => React.ReactNode;
  align?: 'left' | 'right';
  extra?: React.ReactNode;
  naming?: { suggested: string; first?: string };
}> = ({ onChoose, button, align = 'left', extra, naming }) => {
  const [open, setOpen] = useState(false);
  const [at, setAt] = useState<React.CSSProperties>({});
  const [chosen, setChosen] = useState<TabLayout | null>(null);
  const [name, setName] = useState('');
  const [first, setFirst] = useState('');
  const box = useRef<HTMLDivElement>(null);
  // Fixed, because the top tab bar scrolls sideways and would clip the menu.
  const toggle = (e: React.MouseEvent<HTMLElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    setAt(align === 'right' ? { top: r.bottom + 4, right: window.innerWidth - r.right } : { top: r.bottom + 4, left: r.left });
    setChosen(null);
    setOpen(o => !o);
  };
  const choose = (layout: TabLayout) => {
    if (!naming) { setOpen(false); onChoose(layout); return; }
    setChosen(layout);
    setName(naming.suggested);
    setFirst(naming.first ?? '');
  };
  const finish = () => {
    if (!chosen || !name.trim()) return;
    setOpen(false);
    onChoose(chosen, { name: name.trim(), first: naming?.first !== undefined ? first.trim() || naming.first : undefined });
  };
  const field = 'w-full px-2 py-1 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-brand-blue/30';
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const escape = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', escape); };
  }, [open]);
  return (
    <div ref={box} className="relative shrink-0">
      {button(toggle)}
      {open && chosen && (
        <form
          style={at}
          className="fixed z-50 w-72 bg-white border border-gray-200 rounded-md shadow-lg p-3 space-y-2"
          onSubmit={e => { e.preventDefault(); finish(); }}
          aria-label="Name the tabs"
        >
          {naming?.first !== undefined && (
            <label className="block">
              <span className="block text-xs text-gray-500 mb-0.5">This tab, the one you’re on</span>
              <input value={first} maxLength={MAX_NAME_LENGTH} onChange={e => setFirst(e.target.value)} placeholder={naming.first} className={field} />
            </label>
          )}
          <label className="block">
            <span className="block text-xs text-gray-500 mb-0.5">The new tab</span>
            <input autoFocus value={name} maxLength={MAX_NAME_LENGTH} onChange={e => setName(e.target.value)} onFocus={e => e.currentTarget.select()} className={field} />
          </label>
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={() => setChosen(null)} className="px-2 py-1 text-xs text-gray-600 hover:bg-gray-100 rounded">Back</button>
            <button type="submit" disabled={!name.trim()} className="px-3 py-1 text-xs text-white bg-brand-blue rounded hover:bg-brand-navy disabled:opacity-50">Add tab</button>
          </div>
        </form>
      )}
      {open && !chosen && (
        <div role="menu" style={at} className="fixed z-50 w-64 bg-white border border-gray-200 rounded-md shadow-lg py-1">
          {LAYOUT_CHOICES.map(({ layout, label, hint, icon: Icon }) => (
            <button
              key={layout}
              type="button"
              role="menuitem"
              onClick={() => choose(layout)}
              className="w-full flex items-start gap-2.5 px-3 py-2 text-left hover:bg-gray-50"
            >
              <Icon className="w-4 h-4 mt-0.5 text-gray-400 shrink-0" />
              <span>
                <span className="block text-sm text-brand-navy">{label}</span>
                <span className="block text-xs text-gray-500">{hint}</span>
              </span>
            </button>
          ))}
          {extra && <div className="border-t border-gray-100 mt-1 pt-1" onClick={() => setOpen(false)}>{extra}</div>}
        </div>
      )}
    </div>
  );
};

/**
 * The tabs of the app on screen. An app with one tab — every view — has no bar:
 * its editors add a second tab from the header. Whoever may move the app's
 * widgets may also add, rename, reorder and delete its tabs.
 *
 * Each shell places one bar above the canvas and one beside it; only the one the
 * app's nav style asks for draws anything.
 */
export const TabBar: React.FC<{ placement: 'top' | 'side' }> = ({ placement }) => {
  const { activeApp, activeAppTab, selectTab, addTab, setTabLayout, renameTab, moveTab, removeTab, canEditLayout } = useDashboardStore();
  const [editing, setEditing] = useState<{ id: string; was: string; layout?: TabLayout } | null>(null);
  const [draft, setDraft] = useState('');
  const cancelled = useRef(false);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<{ id: string; label: string; count: number } | null>(null);
  const tabRefs = useRef<(HTMLDivElement | null)[]>([]);
  const [focusIndex, setFocusIndex] = useState<number | null>(null);
  const refocus = useRef<string | null>(null);

  useEffect(() => {
    if (!refocus.current || editing) return;
    const index = activeApp?.spec.tabs.findIndex(t => t.id === refocus.current) ?? -1;
    refocus.current = null;
    tabRefs.current[index]?.focus();
  });

  if (!activeApp || activeApp.spec.tabs.length < 2) return null;
  const side = navStyle(activeApp) === 'sidebar';
  if (side !== (placement === 'side')) return null;
  const app = activeApp;
  const tabs = app.spec.tabs;
  const editable = canEditLayout(app);
  // Roving focus: one tab is in the Tab order, the arrow keys move between them.
  const activeIndex = tabs.findIndex(t => t.id === activeAppTab?.id);
  const rovingIndex = focusIndex !== null && focusIndex < tabs.length ? focusIndex : Math.max(0, activeIndex);

  const onTabKey = (e: React.KeyboardEvent<HTMLDivElement>, index: number, id: string, label: string) => {
    if (e.target !== e.currentTarget) return;
    const last = tabs.length - 1;
    const to = {
      ArrowRight: index === last ? 0 : index + 1, ArrowDown: index === last ? 0 : index + 1,
      ArrowLeft: index === 0 ? last : index - 1, ArrowUp: index === 0 ? last : index - 1,
      Home: 0, End: last,
    }[e.key];
    if (to !== undefined) {
      e.preventDefault();
      tabRefs.current[to]?.focus();
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      selectTab(id);
    } else if (e.key === 'F2' && editable) {
      e.preventDefault();
      refocus.current = id;
      startEditing(id, label);
    }
  };

  const startEditing = (id: string, was: string, layout?: TabLayout) => {
    cancelled.current = false;
    setEditing({ id, was, layout });
    setDraft(was);
  };

  // Every way out of the name box ends in its blur, so a name is saved once.
  const finishEditing = () => {
    const name = draft.trim();
    if (editing && !cancelled.current && name) {
      if (editing.id === NEW_TAB) addTab(app.id, name, editing.layout);
      else if (name !== editing.was) renameTab(app.id, editing.id, name);
    }
    setEditing(null);
    setDraft('');
  };

  const nameBox = (key: string) => (
    <input
      key={key}
      autoFocus
      value={draft}
      maxLength={MAX_NAME_LENGTH}
      onChange={e => setDraft(e.target.value)}
      onFocus={e => e.currentTarget.select()}
      onKeyDown={e => {
        if (e.key === 'Escape') cancelled.current = true;
        if (e.key === 'Enter' || e.key === 'Escape') e.currentTarget.blur();
      }}
      onBlur={finishEditing}
      aria-label="Tab name"
      className={clsx(
        'px-2 py-1 text-sm border border-brand-blue rounded focus:outline-none focus:ring-2 focus:ring-brand-blue/30',
        side ? 'mx-2 my-0.5' : 'my-1 w-40',
      )}
    />
  );

  return (
    <nav
      className={clsx(
        'bg-white border-gray-200 shrink-0',
        side ? 'w-52 border-r py-2 flex flex-col gap-0.5 overflow-y-auto' : 'border-b px-4 flex items-end gap-1 overflow-x-auto',
      )}
      aria-label="Tabs"
    >
      <div
        role="tablist"
        aria-label="Tabs"
        aria-orientation={side ? 'vertical' : 'horizontal'}
        className="contents"
        onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocusIndex(null); }}
      >
      {tabs.map((tab, index) => {
        const label = tabLabel(app, tab, index);
        const active = tab.id === activeAppTab?.id;
        if (editing?.id === tab.id) return nameBox(tab.id);

        return (
          <div
            key={tab.id}
            ref={el => { tabRefs.current[index] = el; }}
            role="tab"
            aria-selected={active}
            tabIndex={index === rovingIndex ? 0 : -1}
            onFocus={e => { if (e.target === e.currentTarget) setFocusIndex(index); }}
            onKeyDown={e => onTabKey(e, index, tab.id, label)}
            draggable={editable}
            onDragStart={e => {
              setDragIndex(index);
              e.dataTransfer.effectAllowed = 'move';
              e.dataTransfer.setData('text/plain', String(index));
            }}
            onDragOver={e => {
              if (dragIndex === null) return;
              e.preventDefault();
              e.dataTransfer.dropEffect = 'move';
              if (overIndex !== index) setOverIndex(index);
            }}
            onDrop={e => {
              e.preventDefault();
              if (dragIndex !== null) moveTab(app.id, dragIndex, index);
              setDragIndex(null);
              setOverIndex(null);
            }}
            onDragEnd={() => { setDragIndex(null); setOverIndex(null); }}
            onClick={() => selectTab(tab.id)}
            onDoubleClick={() => editable && startEditing(tab.id, label)}
            title={editable ? `${label} — double-click or press F2 to rename, drag to reorder` : label}
            className={clsx(
              'group flex items-center gap-1 px-3 py-2 text-sm cursor-pointer select-none whitespace-nowrap transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue/40 focus-visible:ring-inset',
              side ? 'border-l-2 justify-between' : 'border-b-2',
              active ? 'border-brand-blue text-brand-navy font-medium' : 'border-transparent text-gray-500 hover:text-gray-800',
              side && active && 'bg-brand-blue/5',
              dragIndex === index && 'opacity-50',
              overIndex === index && dragIndex !== null && dragIndex !== index && 'bg-brand-blue/5',
            )}
          >
            <span className={clsx('truncate', !side && 'max-w-[14rem]')}>{label}</span>
            {/* Only the tab on screen switches layout, but every tab keeps the
                room for it: selecting a tab mustn't shift the others under the
                second click of a double-click. */}
            {editable && (() => {
              const swap = layoutSwitch(tab);
              const Icon = swap.to === 'page' ? FileText : LayoutGrid;
              return (
                <button
                  type="button"
                  aria-disabled={swap.blocked}
                  aria-hidden={!active}
                  tabIndex={active ? undefined : -1}
                  onClick={e => {
                    e.stopPropagation();
                    if (active && !swap.blocked) setTabLayout(app.id, tab.id, swap.to);
                  }}
                  className={clsx(
                    'p-0.5 rounded opacity-0 group-hover:opacity-100 focus:opacity-100',
                    !active && 'invisible',
                    swap.blocked ? 'text-gray-300 cursor-not-allowed' : 'text-gray-400 hover:text-brand-blue hover:bg-gray-100',
                  )}
                  title={swap.title}
                >
                  <Icon className="w-3 h-3" />
                </button>
              );
            })()}
            {editable && (
              <button
                type="button"
                onClick={e => {
                  e.stopPropagation();
                  const count = tab.widgets.length;
                  if (count) setDeleting({ id: tab.id, label, count });
                  else removeTab(app.id, tab.id);
                }}
                className="p-0.5 rounded text-gray-400 hover:text-red-600 hover:bg-gray-100 opacity-0 group-hover:opacity-100 focus:opacity-100"
                title={`Delete the tab “${label}”`}
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </div>
        );
      })}
      </div>
      {editing?.id === NEW_TAB && nameBox(NEW_TAB)}
      {editable && !editing && tabs.length < MAX_TABS && (
        <div className={side ? 'mx-2 self-start' : 'mb-1 ml-1'}>
          <AddTabMenu
            onChoose={layout => startEditing(NEW_TAB, `Tab ${tabs.length + 1}`, layout)}
            button={open => (
              <button
                type="button"
                onClick={open}
                className="p-1.5 rounded-md text-gray-400 hover:text-brand-blue hover:bg-gray-100"
                title="Add a tab"
              >
                <Plus className="w-4 h-4" />
              </button>
            )}
          />
        </div>
      )}
      {deleting && (
        <ConfirmModal
          title="Delete this tab?"
          message={`“${deleting.label}” and the ${deleting.count === 1 ? 'widget' : `${deleting.count} widgets`} on it will be removed from this view.`}
          detail="The widgets stay in the Widget Library, so you can place them again."
          confirmLabel="Delete tab"
          variant="danger"
          onConfirm={() => { removeTab(app.id, deleting.id); setDeleting(null); }}
          onCancel={() => setDeleting(null)}
        />
      )}
    </nav>
  );
};
