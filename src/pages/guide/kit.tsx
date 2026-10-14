/* eslint-disable react-refresh/only-export-components -- the kit exports components beside a few helpers and a context */
// The pieces the user guide's sections are written with. Sections are plain JSX
// built from these, so a page reads as a page rather than as a wall of
// paragraphs: a short lead, numbered steps, a picture, a call-out, and the long
// explanation folded away until someone wants it.
import React, { createContext, useContext, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, ArrowUpRight, ChevronRight, ExternalLink, Info, Lightbulb, Link as LinkIcon, Lock, X } from 'lucide-react';
import clsx from 'clsx';

/** Which section is being drawn, so a heading can build its own deep link. */
export const GuideSectionContext = createContext<string>('');

export const guideHash = (section: string, anchor?: string) =>
  `#/user-guide/${section}${anchor ? `/${anchor}` : ''}`;

// ------------------------------------------------------------------ headings

const copyLink = (hash: string) => {
  const url = `${window.location.origin}${window.location.pathname}${window.location.search}${hash}`;
  navigator.clipboard?.writeText(url).catch(() => { /* a link that can't be copied is still in the address bar */ });
};

/** A heading the table of contents lists and a link can point at. */
const Heading: React.FC<{ id: string; level: 2 | 3; children: React.ReactNode }> = ({ id, level, children }) => {
  const section = useContext(GuideSectionContext);
  const [copied, setCopied] = useState(false);
  const Tag = level === 2 ? 'h2' : 'h3';
  const hash = guideHash(section, id);
  return (
    <Tag
      id={`g-${id}`}
      data-guide-heading={level}
      className={clsx(
        'group scroll-mt-6 flex items-center gap-2 font-semibold text-gray-900',
        level === 2 ? 'text-xl mt-10 mb-3 pb-2 border-b border-gray-200' : 'text-base mt-7 mb-2',
      )}
    >
      <span>{children}</span>
      <a
        href={hash}
        onClick={() => { copyLink(hash); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
        title="Copy a link to this heading"
        aria-label="Copy a link to this heading"
        className="opacity-0 group-hover:opacity-100 focus:opacity-100 text-gray-400 hover:text-brand-blue transition-opacity"
      >
        <LinkIcon className="w-3.5 h-3.5" />
      </a>
      {copied && <span className="text-xs font-normal text-green-600">Link copied</span>}
    </Tag>
  );
};

export const H2: React.FC<{ id: string; children: React.ReactNode }> = ({ id, children }) => <Heading id={id} level={2}>{children}</Heading>;
export const H3: React.FC<{ id: string; children: React.ReactNode }> = ({ id, children }) => <Heading id={id} level={3}>{children}</Heading>;

// --------------------------------------------------------------------- prose

/** The sentence or two that says what this page is for. */
export const Lead: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <p className="text-lg leading-relaxed text-gray-700">{children}</p>
);

export const P: React.FC<{ children: React.ReactNode; className?: string }> = ({ children, className }) => (
  <p className={clsx('text-[15px] leading-relaxed text-gray-700 my-3', className)}>{children}</p>
);

export const List: React.FC<{ children: React.ReactNode; ordered?: boolean }> = ({ children, ordered }) => {
  const Tag = ordered ? 'ol' : 'ul';
  return <Tag className={clsx('pl-5 my-3 space-y-1.5 text-[15px] leading-relaxed text-gray-700', ordered ? 'list-decimal' : 'list-disc')}>{children}</Tag>;
};

/** The name of something on screen: a button, a menu, a field. */
export const UI: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <strong className="font-semibold text-gray-900">{children}</strong>
);

export const Kbd: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <kbd className="px-1.5 py-0.5 rounded border border-gray-300 bg-gray-50 text-xs font-mono text-gray-700 shadow-[0_1px_0_rgba(0,0,0,0.08)]">{children}</kbd>
);

export const Code: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <code className="px-1 py-0.5 rounded bg-gray-100 text-[13px] font-mono text-gray-800">{children}</code>
);

// --------------------------------------------------------------------- steps

/** Numbered steps. Each child is a <Step>; a step may hold a <Shot> or a paragraph after its first line. */
export const Steps: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <ol className="my-4 space-y-4 [counter-reset:step]">{children}</ol>
);

export const Step: React.FC<{ title?: string; children: React.ReactNode }> = ({ title, children }) => (
  <li className="relative pl-11 [counter-increment:step] before:content-[counter(step)] before:absolute before:left-0 before:top-0 before:w-7 before:h-7 before:rounded-full before:bg-brand-blue before:text-white before:text-sm before:font-semibold before:flex before:items-center before:justify-center">
    {title && <div className="font-semibold text-gray-900 leading-7">{title}</div>}
    <div className={clsx('text-[15px] leading-relaxed text-gray-700', title ? '' : 'pt-0.5')}>{children}</div>
  </li>
);

// ------------------------------------------------------------------ callouts

const CALLOUTS = {
  tip: { icon: Lightbulb, label: 'Tip', box: 'bg-emerald-50 border-emerald-200 text-emerald-900', ic: 'text-emerald-600' },
  note: { icon: Info, label: 'Good to know', box: 'bg-blue-50 border-blue-200 text-blue-900', ic: 'text-blue-600' },
  warn: { icon: AlertTriangle, label: 'Careful', box: 'bg-amber-50 border-amber-200 text-amber-900', ic: 'text-amber-600' },
  admin: { icon: Lock, label: 'Needs a role', box: 'bg-violet-50 border-violet-200 text-violet-900', ic: 'text-violet-600' },
} as const;

export const Callout: React.FC<{ kind?: keyof typeof CALLOUTS; title?: string; children: React.ReactNode }> = ({ kind = 'note', title, children }) => {
  const c = CALLOUTS[kind];
  const Icon = c.icon;
  return (
    <aside className={clsx('my-5 flex gap-3 rounded-lg border p-4 text-[14px] leading-relaxed', c.box)}>
      <Icon className={clsx('w-5 h-5 shrink-0 mt-0.5', c.ic)} />
      <div className="min-w-0">
        <div className="font-semibold mb-0.5">{title || c.label}</div>
        <div className="[&_p]:my-1.5">{children}</div>
      </div>
    </aside>
  );
};

/** A small badge saying who a feature is for. */
export const Needs: React.FC<{ role: string }> = ({ role }) => (
  <span className="inline-flex items-center gap-1 align-middle ml-1 px-2 py-0.5 rounded-full bg-violet-100 text-violet-800 text-[11px] font-medium">
    <Lock className="w-3 h-3" /> {role}
  </span>
);

// ------------------------------------------------------------------- details

/** The long explanation, folded away. Native <details>, so it is searchable and works without script. */
export const Details: React.FC<{ summary: string; children: React.ReactNode; open?: boolean }> = ({ summary, children, open }) => (
  <details open={open} className="group my-4 rounded-lg border border-gray-200 bg-white open:shadow-sm">
    <summary className="flex items-center gap-2 cursor-pointer select-none px-4 py-3 text-[15px] font-medium text-gray-800 hover:bg-gray-50 rounded-lg list-none [&::-webkit-details-marker]:hidden">
      <ChevronRight className="w-4 h-4 text-gray-400 transition-transform group-open:rotate-90" />
      {summary}
    </summary>
    <div className="px-4 pb-4 pt-1 border-t border-gray-100 [&>p:first-child]:mt-3">{children}</div>
  </details>
);

// ------------------------------------------------------------------- figures

const LightboxContext = createContext<(img: { src: string; alt: string } | null) => void>(() => {});

/** Provides the click-to-enlarge overlay for every <Shot> beneath it. */
export const LightboxProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [img, setImg] = useState<{ src: string; alt: string } | null>(null);
  useEffect(() => {
    if (!img) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setImg(null); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [img]);
  return (
    <LightboxContext.Provider value={setImg}>
      {children}
      {img && createPortal(
        <div
          role="dialog"
          aria-label={img.alt}
          className="fixed inset-0 z-[100] bg-black/80 flex items-center justify-center p-6 cursor-zoom-out"
          onClick={() => setImg(null)}
        >
          <button type="button" aria-label="Close" className="absolute top-4 right-4 text-white/80 hover:text-white" onClick={() => setImg(null)}>
            <X className="w-6 h-6" />
          </button>
          <img src={img.src} alt={img.alt} className="max-w-full max-h-full rounded-lg shadow-2xl bg-white" />
        </div>,
        document.body,
      )}
    </LightboxContext.Provider>
  );
};

/**
 * A screenshot from public/guide/<name>.png. `legend` lists what the numbered red
 * rings in the picture point at, in order; leave it off for an unmarked picture.
 */
export const Shot: React.FC<{ name: string; alt: string; caption?: string; legend?: string[]; narrow?: boolean }> = ({ name, alt, caption, legend, narrow }) => {
  const open = useContext(LightboxContext);
  const src = `/guide/${name}.png`;
  const [missing, setMissing] = useState(false);
  if (missing) return null; // a picture that isn't there is better left out than shown broken
  return (
    <figure className={clsx('my-5', narrow && 'max-w-md')}>
      <button
        type="button"
        onClick={() => open({ src, alt })}
        className="block w-full rounded-lg border border-gray-200 shadow-sm overflow-hidden bg-gray-50 cursor-zoom-in hover:shadow-md hover:border-gray-300 transition"
        title="Click to enlarge"
      >
        <img src={src} alt={alt} loading="lazy" onError={() => setMissing(true)} className="block w-full h-auto" />
      </button>
      {(caption || legend) && (
        <figcaption className="mt-2 text-[13px] text-gray-500 leading-snug">
          {caption}
          {legend && (
            <ol className="mt-2 space-y-1">
              {legend.map((item, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="shrink-0 w-5 h-5 rounded-full bg-red-500 text-white text-[11px] font-bold flex items-center justify-center mt-px">{i + 1}</span>
                  <span>{item}</span>
                </li>
              ))}
            </ol>
          )}
        </figcaption>
      )}
    </figure>
  );
};

// --------------------------------------------------------------------- links

/** A link to another section of this guide, or to a heading in it. */
export const GuideLink: React.FC<{ to: string; anchor?: string; children: React.ReactNode }> = ({ to, anchor, children }) => (
  <a href={guideHash(to, anchor)} className="text-brand-blue font-medium hover:underline">{children}</a>
);

/** A link that opens a page of the app itself, such as Agent Studio. */
export const OpenLink: React.FC<{ page: 'studio' | 'agent-studio' | 'admin' | 'settings' | 'release-notes' | 'about'; children: React.ReactNode }> = ({ page, children }) => (
  <a href={`#/${page}`} className="inline-flex items-center gap-0.5 text-brand-blue font-medium hover:underline">
    {children}<ArrowUpRight className="w-3.5 h-3.5" />
  </a>
);

/** A link to another site, always in a new tab. */
export const Ext: React.FC<{ href: string; children: React.ReactNode }> = ({ href, children }) => (
  <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 text-brand-blue font-medium hover:underline">
    {children}<ExternalLink className="w-3.5 h-3.5" />
  </a>
);

// --------------------------------------------------------------------- cards

/** A grid of cards, for a section's index of what it covers. */
export const Cards: React.FC<{ children: React.ReactNode; cols?: 2 | 3 }> = ({ children, cols = 2 }) => (
  <div className={clsx('my-5 grid gap-3 grid-cols-1', cols === 3 ? 'md:grid-cols-3' : 'md:grid-cols-2')}>{children}</div>
);

export const Card: React.FC<{ title: string; icon?: React.ReactNode; to?: string; anchor?: string; children: React.ReactNode }> = ({ title, icon, to, anchor, children }) => {
  const body = (
    <>
      <div className="flex items-center gap-2 font-semibold text-gray-900 mb-1">{icon}{title}</div>
      <div className="text-sm text-gray-600 leading-relaxed [&_p]:m-0">{children}</div>
    </>
  );
  const cls = 'block rounded-lg border border-gray-200 bg-white p-4 shadow-sm';
  return to
    ? <a href={guideHash(to, anchor)} className={clsx(cls, 'hover:border-brand-blue hover:shadow-md transition')}>{body}</a>
    : <div className={cls}>{body}</div>;
};

// -------------------------------------------------------------------- tables

export const Table: React.FC<{ head: string[]; rows: React.ReactNode[][] }> = ({ head, rows }) => (
  <div className="my-4 overflow-x-auto rounded-lg border border-gray-200">
    <table className="w-full text-[14px] text-left">
      <thead className="bg-gray-50 text-gray-600">
        <tr>{head.map(h => <th key={h} className="px-3 py-2 font-semibold border-b border-gray-200">{h}</th>)}</tr>
      </thead>
      <tbody className="divide-y divide-gray-100">
        {rows.map((row, i) => (
          <tr key={i} className="align-top">{row.map((cell, j) => <td key={j} className="px-3 py-2 text-gray-700">{cell}</td>)}</tr>
        ))}
      </tbody>
    </table>
  </div>
);
