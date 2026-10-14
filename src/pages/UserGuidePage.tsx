// The user guide. The words live in `guide/sections/*.tsx`, one file per page,
// written with the pieces in `guide/kit.tsx`; this file is only the frame around
// them: the sidebar, search, the address of each page and heading, the
// "On this page" rail, and previous/next.
//
// An address is `#/user-guide[/<section>[/<heading>]]`. Layout leaves the part
// after `#/user-guide/` alone (see `pageOf` there), so a copied link reopens the
// same heading and Back returns to where you were.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, Book, Search, X } from 'lucide-react';
import clsx from 'clsx';
import { SECTIONS } from './guide/registry';
import { GROUP_TITLES, type GuideGroup, type GuideSection } from './guide/types';
import { GuideSectionContext, LightboxProvider, guideHash } from './guide/kit';

const GROUP_ORDER: GuideGroup[] = ['start', 'use', 'build', 'admin', 'reference'];

const readRoute = (): { section: string; anchor: string | null } => {
  // "#/user-guide/<section>/<heading>" splits into ["#", "user-guide", section, heading].
  const [, , section, anchor] = window.location.hash.split('/');
  const known = SECTIONS.find(s => s.id === section);
  return { section: known ? known.id : SECTIONS[0].id, anchor: known && anchor ? decodeURIComponent(anchor) : null };
};

// ---------------------------------------------------------------- search index

interface Chunk { sectionId: string; heading: string; headingId: string | null; text: string }

/**
 * Every section's words, split under the heading they sit beneath. Built the
 * first time someone searches, by drawing each section off-screen to static
 * markup, so the guide never keeps a second copy of its own text to go stale.
 */
const buildIndex = async (): Promise<Chunk[]> => {
  const { renderToStaticMarkup } = await import('react-dom/server');
  const chunks: Chunk[] = [];
  for (const s of SECTIONS) {
    const html = renderToStaticMarkup(
      <GuideSectionContext.Provider value={s.id}><LightboxProvider><s.Body /></LightboxProvider></GuideSectionContext.Provider>,
    );
    const doc = new DOMParser().parseFromString(html, 'text/html');
    let cur: Chunk = { sectionId: s.id, heading: s.title, headingId: null, text: '' };
    const flush = () => { if (cur.text.trim()) chunks.push({ ...cur, text: cur.text.replace(/\s+/g, ' ').trim() }); };
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const heading = node.parentElement?.closest('h2,h3');
      const text = node.nodeValue || '';
      if (heading && heading.id.startsWith('g-')) {
        if (!cur.text.trim() || cur.headingId !== heading.id.slice(2)) {
          flush();
          cur = { sectionId: s.id, heading: heading.textContent?.trim() || s.title, headingId: heading.id.slice(2), text: '' };
        }
        continue;
      }
      cur.text += ' ' + text;
    }
    flush();
  }
  return chunks;
};

interface Hit { chunk: Chunk; score: number; snippet: string }

const search = (chunks: Chunk[], query: string): Hit[] => {
  const terms = query.toLowerCase().split(/\s+/).filter(t => t.length > 1);
  if (!terms.length) return [];
  const hits: Hit[] = [];
  for (const chunk of chunks) {
    const section = SECTIONS.find(s => s.id === chunk.sectionId)!;
    const hay = chunk.text.toLowerCase();
    const head = `${section.title} ${chunk.heading} ${section.keywords || ''}`.toLowerCase();
    if (!terms.every(t => hay.includes(t) || head.includes(t))) continue;
    let score = 0;
    for (const t of terms) {
      if (head.includes(t)) score += 10;
      score += Math.min(hay.split(t).length - 1, 5);
    }
    const at = Math.max(0, hay.indexOf(terms.find(t => hay.includes(t)) || terms[0]) - 60);
    const raw = chunk.text.slice(at, at + 200);
    hits.push({ chunk, score, snippet: (at > 0 ? '… ' : '') + raw + (at + 200 < chunk.text.length ? ' …' : '') });
  }
  return hits.sort((a, b) => b.score - a.score).slice(0, 25);
};

const Marked: React.FC<{ text: string; terms: string[] }> = ({ text, terms }) => {
  if (!terms.length) return <>{text}</>;
  const re = new RegExp(`(${terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi');
  return <>{text.split(re).map((part, i) => (i % 2 ? <mark key={i} className="bg-yellow-100 text-gray-900 rounded px-0.5">{part}</mark> : part))}</>;
};

// ------------------------------------------------------------------------ page

interface TocItem { id: string; text: string; level: number }

export const UserGuidePage: React.FC = () => {
  const [route, setRoute] = useState(readRoute);
  const [query, setQuery] = useState('');
  const [index, setIndex] = useState<Chunk[] | null>(null);
  const [indexing, setIndexing] = useState(false);
  const [toc, setToc] = useState<TocItem[]>([]);
  const [activeHeading, setActiveHeading] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const section: GuideSection = SECTIONS.find(s => s.id === route.section) || SECTIONS[0];
  const position = SECTIONS.findIndex(s => s.id === section.id);
  const previous = position > 0 ? SECTIONS[position - 1] : null;
  const next = position < SECTIONS.length - 1 ? SECTIONS[position + 1] : null;

  // The address is the source of truth: Back, a pasted link and a click all arrive here.
  useEffect(() => {
    const onHash = () => { if (window.location.hash.startsWith('#/user-guide')) { setRoute(readRoute()); setQuery(''); } };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  // A bare `#/user-guide` becomes its first section's address, so every page has one.
  useEffect(() => {
    if (window.location.hash === '#/user-guide') window.history.replaceState(window.history.state, '', guideHash(route.section));
  }, [route.section]);

  // Land on the heading a link names, or at the top of a new section; collect headings for the rail.
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const root = contentRef.current;
      if (!root) return;
      setToc(Array.from(root.querySelectorAll<HTMLElement>('[data-guide-heading]')).map(h => ({
        id: h.id.slice(2), text: h.textContent?.replace(/Link copied/, '').trim() || '', level: Number(h.dataset.guideHeading),
      })));
      const target = route.anchor ? document.getElementById(`g-${route.anchor}`) : null;
      if (target) target.scrollIntoView({ block: 'start' });
      else scrollRef.current?.scrollTo({ top: 0 });
    });
    return () => cancelAnimationFrame(frame);
  }, [route.section, route.anchor, query]);

  // Which heading is on screen, for the rail.
  useEffect(() => {
    const root = scrollRef.current;
    if (!root || !toc.length) return;
    const seen = new Map<string, boolean>();
    const observer = new IntersectionObserver(entries => {
      for (const e of entries) seen.set(e.target.id.slice(2), e.isIntersecting);
      const first = toc.find(t => seen.get(t.id));
      if (first) setActiveHeading(first.id);
    }, { root, rootMargin: '0px 0px -70% 0px' });
    toc.forEach(t => { const el = document.getElementById(`g-${t.id}`); if (el) observer.observe(el); });
    return () => observer.disconnect();
  }, [toc]);

  // "/" jumps to search, like most documentation sites.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (document.activeElement?.tagName || '').toLowerCase();
      if (e.key === '/' && !e.metaKey && !e.ctrlKey && tag !== 'input' && tag !== 'textarea') {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const onQuery = useCallback((value: string) => {
    setQuery(value);
    if (value.trim() && !index && !indexing) {
      setIndexing(true);
      buildIndex().then(setIndex).catch(e => console.error('Building the guide search failed', e)).finally(() => setIndexing(false));
    }
  }, [index, indexing]);

  const terms = useMemo(() => query.toLowerCase().split(/\s+/).filter(t => t.length > 1), [query]);
  const hits = useMemo(() => (index && query.trim() ? search(index, query) : []), [index, query]);
  const searching = query.trim().length > 0;

  return (
    <LightboxProvider>
      <div className="flex h-full bg-white">
        {/* Sidebar */}
        <div className="w-72 shrink-0 border-r border-gray-200 bg-gray-50 flex flex-col">
          <div className="p-4 border-b border-gray-200">
            <h1 className="text-lg font-bold text-brand-navy flex items-center gap-2">
              <Book className="w-5 h-5 text-brand-blue" />
              User Guide
            </h1>
            <div className="relative mt-3">
              <Search className="w-4 h-4 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                ref={searchRef}
                value={query}
                onChange={e => onQuery(e.target.value)}
                onKeyDown={e => { if (e.key === 'Escape') { setQuery(''); searchRef.current?.blur(); } }}
                placeholder="Search the guide  ( / )"
                aria-label="Search the guide"
                className="w-full pl-8 pr-8 py-1.5 text-sm bg-white border border-gray-300 rounded-md focus:outline-none focus:border-brand-blue focus:ring-1 focus:ring-brand-blue"
              />
              {query && (
                <button type="button" aria-label="Clear search" onClick={() => setQuery('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>
          <nav className="flex-1 overflow-y-auto p-4 space-y-6">
            {GROUP_ORDER.map(group => {
              const items = SECTIONS.filter(s => s.group === group);
              if (!items.length) return null;
              return (
                <div key={group}>
                  <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 px-3">{GROUP_TITLES[group]}</h3>
                  <div className="space-y-0.5">
                    {items.map(s => {
                      const Icon = s.icon;
                      const active = !searching && section.id === s.id;
                      return (
                        <a
                          key={s.id}
                          href={guideHash(s.id)}
                          aria-current={active ? 'page' : undefined}
                          className={clsx(
                            'flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-md transition-colors',
                            active ? 'bg-brand-blue text-white' : 'text-gray-600 hover:bg-gray-200 hover:text-gray-900',
                          )}
                        >
                          <Icon className={clsx('w-4 h-4 shrink-0', active ? 'text-white' : 'text-gray-400')} />
                          {s.title}
                        </a>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </nav>
        </div>

        {/* Page */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          <div className="max-w-5xl mx-auto px-8 py-8 flex gap-10">
            <div ref={contentRef} className="min-w-0 flex-1 max-w-3xl">
              {searching ? (
                <div>
                  <h2 className="text-2xl font-bold text-gray-900 mb-1">Search</h2>
                  <p className="text-sm text-gray-500 mb-5">
                    {indexing || !index ? 'Reading the guide…' : hits.length ? `${hits.length} result${hits.length === 1 ? '' : 's'} for “${query.trim()}”` : `Nothing in the guide matches “${query.trim()}”. Try fewer or simpler words.`}
                  </p>
                  <div className="space-y-3">
                    {hits.map((h, i) => {
                      const s = SECTIONS.find(x => x.id === h.chunk.sectionId)!;
                      return (
                        <a key={i} href={guideHash(s.id, h.chunk.headingId || undefined)} className="block rounded-lg border border-gray-200 p-4 hover:border-brand-blue hover:shadow-sm transition">
                          <div className="text-xs text-gray-500 mb-0.5">{GROUP_TITLES[s.group]} › {s.title}</div>
                          <div className="font-semibold text-gray-900"><Marked text={h.chunk.heading} terms={terms} /></div>
                          <div className="text-sm text-gray-600 mt-1 leading-relaxed"><Marked text={h.snippet} terms={terms} /></div>
                        </a>
                      );
                    })}
                  </div>
                </div>
              ) : (
                <GuideSectionContext.Provider value={section.id}>
                  <div className="text-xs font-medium uppercase tracking-wider text-brand-blue mb-2">{GROUP_TITLES[section.group]}</div>
                  <h2 className="text-3xl font-bold text-gray-900 mb-2">{section.title}</h2>
                  <p className="text-gray-500 mb-6">{section.summary}</p>
                  <section.Body />
                  <nav className="mt-14 pt-6 border-t border-gray-200 grid grid-cols-2 gap-4" aria-label="Previous and next page">
                    {previous ? (
                      <a href={guideHash(previous.id)} className="group rounded-lg border border-gray-200 p-4 hover:border-brand-blue transition">
                        <div className="text-xs text-gray-500 flex items-center gap-1"><ArrowLeft className="w-3 h-3" /> Previous</div>
                        <div className="font-semibold text-gray-900 group-hover:text-brand-blue">{previous.title}</div>
                      </a>
                    ) : <span />}
                    {next ? (
                      <a href={guideHash(next.id)} className="group rounded-lg border border-gray-200 p-4 text-right hover:border-brand-blue transition">
                        <div className="text-xs text-gray-500 flex items-center gap-1 justify-end">Next <ArrowRight className="w-3 h-3" /></div>
                        <div className="font-semibold text-gray-900 group-hover:text-brand-blue">{next.title}</div>
                      </a>
                    ) : <span />}
                  </nav>
                </GuideSectionContext.Provider>
              )}
            </div>

            {/* On this page */}
            {!searching && toc.length > 1 && (
              <aside className="hidden xl:block w-52 shrink-0">
                <div className="sticky top-6">
                  <div className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-3">On this page</div>
                  <ul className="space-y-1.5 border-l border-gray-200">
                    {toc.map(t => (
                      <li key={t.id}>
                        <a
                          href={guideHash(section.id, t.id)}
                          className={clsx(
                            'block -ml-px border-l-2 text-[13px] leading-snug py-0.5 transition-colors',
                            t.level === 3 ? 'pl-6' : 'pl-3',
                            activeHeading === t.id ? 'border-brand-blue text-brand-blue font-medium' : 'border-transparent text-gray-500 hover:text-gray-900',
                          )}
                        >
                          {t.text}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              </aside>
            )}
          </div>
        </div>
      </div>
    </LightboxProvider>
  );
};
