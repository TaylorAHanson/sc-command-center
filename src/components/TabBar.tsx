import React, { useRef, useState } from 'react';
import { Plus, X } from 'lucide-react';
import clsx from 'clsx';
import { useDashboardStore } from '../store/dashboardStore';
import { MAX_NAME_LENGTH, MAX_TABS, navStyle, tabLabel } from '../store/appSpec';

const NEW_TAB = '\u0000new';

/**
 * The tabs of the app on screen. An app with one tab — every view — has no bar:
 * its editors add a second tab from the header. Whoever may move the app's
 * widgets may also add, rename, reorder and delete its tabs.
 *
 * Each shell places one bar above the canvas and one beside it; only the one the
 * app's nav style asks for draws anything.
 */
export const TabBar: React.FC<{ placement: 'top' | 'side' }> = ({ placement }) => {
  const { activeApp, activeAppTab, selectTab, addTab, renameTab, moveTab, removeTab, canEditLayout } = useDashboardStore();
  const [editing, setEditing] = useState<{ id: string; was: string } | null>(null);
  const [draft, setDraft] = useState('');
  const cancelled = useRef(false);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);

  if (!activeApp || activeApp.spec.tabs.length < 2) return null;
  const side = navStyle(activeApp) === 'sidebar';
  if (side !== (placement === 'side')) return null;
  const app = activeApp;
  const tabs = app.spec.tabs;
  const editable = canEditLayout(app);

  const startEditing = (id: string, was: string) => {
    cancelled.current = false;
    setEditing({ id, was });
    setDraft(was);
  };

  // Every way out of the name box ends in its blur, so a name is saved once.
  const finishEditing = () => {
    const name = draft.trim();
    if (editing && !cancelled.current && name) {
      if (editing.id === NEW_TAB) addTab(app.id, name);
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
      {tabs.map((tab, index) => {
        const label = tabLabel(app, tab, index);
        const active = tab.id === activeAppTab?.id;
        if (editing?.id === tab.id) return nameBox(tab.id);

        return (
          <div
            key={tab.id}
            role="tab"
            aria-selected={active}
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
            title={editable ? `${label} — double-click to rename, drag to reorder` : label}
            className={clsx(
              'group flex items-center gap-1 px-3 py-2 text-sm cursor-pointer select-none whitespace-nowrap transition-colors',
              side ? 'border-l-2 justify-between' : 'border-b-2',
              active ? 'border-brand-blue text-brand-navy font-medium' : 'border-transparent text-gray-500 hover:text-gray-800',
              side && active && 'bg-brand-blue/5',
              dragIndex === index && 'opacity-50',
              overIndex === index && dragIndex !== null && dragIndex !== index && 'bg-brand-blue/5',
            )}
          >
            <span className={clsx('truncate', !side && 'max-w-[14rem]')}>{label}</span>
            {editable && (
              <button
                type="button"
                onClick={e => {
                  e.stopPropagation();
                  const count = tab.widgets.length;
                  if (count && !window.confirm(`Delete the tab “${label}” and the ${count} widget${count === 1 ? '' : 's'} on it?`)) return;
                  removeTab(app.id, tab.id);
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
      {editing?.id === NEW_TAB && nameBox(NEW_TAB)}
      {editable && !editing && tabs.length < MAX_TABS && (
        <button
          type="button"
          onClick={() => startEditing(NEW_TAB, `Tab ${tabs.length + 1}`)}
          className={clsx(
            'p-1.5 rounded-md text-gray-400 hover:text-brand-blue hover:bg-gray-100',
            side ? 'mx-2 self-start' : 'mb-1 ml-1',
          )}
          title="Add a tab"
        >
          <Plus className="w-4 h-4" />
        </button>
      )}
    </nav>
  );
};
