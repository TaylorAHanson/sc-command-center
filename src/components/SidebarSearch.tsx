import React, { useEffect, useId, useState } from 'react';
import { Loader2, Search, X } from 'lucide-react';
import clsx from 'clsx';
import { discoverHref, suggestViews, type ViewRow } from '../discover';
import { hrefOf } from '../workingSet';

// Long enough that a word typed at speed asks once, short enough to feel live.
const SUGGEST_DELAY_MS = 150;

/**
 * The sidebar's search box: view names as you type, from the view catalog, and
 * Enter for every match on the Discover page. A suggestion is a link, like a
 * sidebar row, so it opens the way the row would and can open in a new tab.
 */
export const SidebarSearch = React.forwardRef<HTMLInputElement, { onOpen?: () => void }>(({ onOpen }, ref) => {
  const [q, setQ] = useState('');
  const [found, setFound] = useState<{ query: string; rows: ViewRow[] }>({ query: '', rows: [] });
  const [failed, setFailed] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const listId = useId();
  const text = q.trim();

  useEffect(() => {
    if (!text) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      suggestViews(text, { signal: controller.signal })
        .then(r => {
          setFound({ query: text, rows: r.results });
          setActive(-1);
        })
        .catch(() => {
          if (!controller.signal.aborted) setFailed(text);
        });
    }, SUGGEST_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [text]);

  const rows = text && found.query === text ? found.rows : [];
  const waiting = !!text && found.query !== text && failed !== text;
  const shown = open && !!text;
  const searchAll = discoverHref({ q: text });

  const go = (href: string) => {
    setOpen(false);
    setQ('');
    onOpen?.();
    window.location.hash = href;
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' && text) {
      e.preventDefault();
      setOpen(true);
      setActive(i => Math.min(i + 1, rows.length));
    } else if (e.key === 'ArrowUp' && text) {
      e.preventDefault();
      setActive(i => Math.max(i - 1, -1));
    } else if (e.key === 'Enter' && text) {
      e.preventDefault();
      const row = active >= 0 ? rows[active] : undefined;
      go(row ? hrefOf(row) : searchAll);
    } else if (e.key === 'Escape') {
      if (shown) setOpen(false);
      else setQ('');
    }
  };

  const optionId = (i: number) => `${listId}-${i}`;
  const option = 'flex items-center gap-2 px-3 py-1.5 text-sm rounded-md truncate';

  return (
    <div className="relative">
      <label className="flex items-center gap-2 px-2.5 py-1.5 rounded-md bg-gray-800/70 border border-gray-700 focus-within:border-brand-blue text-gray-400">
        <Search className="w-4 h-4 shrink-0" aria-hidden />
        <input
          ref={ref}
          type="search"
          value={q}
          onChange={e => { setQ(e.target.value); setOpen(true); setActive(-1); }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
          placeholder="Search views"
          aria-label="Search views"
          role="combobox"
          aria-expanded={shown}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={shown && active >= 0 ? optionId(active) : undefined}
          className="flex-1 min-w-0 bg-transparent text-sm text-white placeholder-gray-500 focus:outline-none [&::-webkit-search-cancel-button]:hidden"
        />
        {waiting && <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" aria-label="Searching" />}
        {q && !waiting && (
          <button
            type="button"
            onMouseDown={e => e.preventDefault()}
            onClick={() => setQ('')}
            className="shrink-0 rounded p-0.5 hover:text-white"
            aria-label="Clear search"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </label>
      {shown && (
        <ul
          id={listId}
          role="listbox"
          aria-label="Views matching your search"
          // Choosing with the mouse mustn't blur the box first, which would close the list.
          onMouseDown={e => e.preventDefault()}
          className="absolute left-0 right-0 top-full mt-1 z-40 rounded-md border border-gray-700 bg-brand-navy p-1 shadow-xl"
        >
          {rows.map((row, i) => (
            <li key={row.id} id={optionId(i)} role="option" aria-selected={active === i}>
              <a
                href={hrefOf(row)}
                tabIndex={-1}
                onClick={() => { setOpen(false); setQ(''); onOpen?.(); }}
                className={clsx(option, active === i ? 'bg-brand-blue text-white' : 'text-gray-300 hover:bg-gray-800 hover:text-white')}
                title={row.owner ? `${row.name} · ${row.owner}` : row.name}
              >
                <span className="truncate">{row.name}</span>
              </a>
            </li>
          ))}
          {!waiting && rows.length === 0 && (
            <li role="presentation" className="px-3 py-1.5 text-xs text-gray-500">
              {failed === text ? 'Couldn’t search just now.' : 'No view names match.'}
            </li>
          )}
          <li id={optionId(rows.length)} role="option" aria-selected={active === rows.length}>
            <a
              href={searchAll}
              tabIndex={-1}
              onClick={() => { setOpen(false); setQ(''); onOpen?.(); }}
              className={clsx(option, 'text-xs', active === rows.length ? 'bg-brand-blue text-white' : 'text-gray-400 hover:bg-gray-800 hover:text-white')}
            >
              <Search className="w-3.5 h-3.5 shrink-0" aria-hidden />
              <span className="truncate">Search all views for “{text}”</span>
            </a>
          </li>
        </ul>
      )}
    </div>
  );
});
SidebarSearch.displayName = 'SidebarSearch';
