import React, { useEffect } from 'react';
import { ArrowRight, Bot, Code, LayoutGrid, Lock, Plus, Search, Sparkles, X } from 'lucide-react';
import clsx from 'clsx';

/** The part of the workspace a welcome card is about, so Layout can light it up. */
export type WelcomeSpot = 'assistant' | 'global-views' | 'library' | 'studio' | 'agent-studio';

const STARTER_QUESTIONS = [
  'What can you help me with?',
  'What data can I look at here?',
  'Which global view should I start with?',
];

const VIEWS_SHOWN = 3;

const Tile: React.FC<{
  spot: WelcomeSpot;
  onSpot: (spot: WelcomeSpot | null) => void;
  icon: React.ReactNode;
  title: string;
  body: string;
  locked?: boolean;
  children: React.ReactNode;
}> = ({ spot, onSpot, icon, title, body, locked, children }) => (
  <div
    onMouseEnter={() => onSpot(spot)}
    onMouseLeave={() => onSpot(null)}
    onFocus={() => onSpot(spot)}
    onBlur={() => onSpot(null)}
    className={clsx(
      'flex flex-col rounded-xl border p-4 transition-all',
      locked ? 'border-gray-200 bg-gray-50' : 'border-gray-200 bg-white hover:border-brand-blue/40 hover:shadow-md',
    )}
  >
    <div className="flex items-center gap-2 mb-1">
      <span className={clsx('flex h-7 w-7 items-center justify-center rounded-lg', locked ? 'bg-gray-200 text-gray-500' : 'bg-brand-blue/10 text-brand-blue')}>
        {icon}
      </span>
      <h3 className={clsx('text-sm font-semibold', locked ? 'text-gray-600' : 'text-gray-900')}>{title}</h3>
    </div>
    <p className="text-xs text-gray-600 leading-relaxed mb-3">{body}</p>
    <div className="mt-auto">{children}</div>
  </div>
);

const TileAction: React.FC<{ onClick: () => void; children: React.ReactNode }> = ({ onClick, children }) => (
  <button
    type="button"
    onClick={onClick}
    className="inline-flex items-center gap-1 text-xs font-semibold text-brand-blue hover:underline"
  >
    {children}
    <ArrowRight className="w-3.5 h-3.5" />
  </button>
);

const NeedsEditor: React.FC = () => (
  <p className="flex items-center gap-1.5 text-xs text-gray-500">
    <Lock className="w-3.5 h-3.5" />
    Needs editor access in a domain; ask an admin.
  </p>
);

/**
 * What a first visit can do, laid over the canvas. Each card is a doorway rather
 * than a description: it opens the thing it names. Hovering one reports its spot,
 * and Layout outlines that part of the sidebar or the assistant, so the next
 * visit knows where to find it without this.
 */
export const WelcomeOverlay: React.FC<{
  /** Null when the view on screen has no assistant. */
  agentName: string | null;
  /** Opens the assistant; a prompt is typed in for the user to send, never sent. */
  onAsk: (prompt?: string) => void;
  globalViews: { id: string; name: string }[];
  onOpenView: (id: string) => void;
  onOpenLibrary: () => void;
  canBuild: boolean;
  onOpenStudio: (page: 'studio' | 'agent-studio') => void;
  onBlankView: () => void;
  onSpot: (spot: WelcomeSpot | null) => void;
  /** Absent when there is nothing behind the panel to go back to. */
  onDismiss?: () => void;
}> = ({ agentName, onAsk, globalViews, onOpenView, onOpenLibrary, canBuild, onOpenStudio, onBlankView, onSpot, onDismiss }) => {
  useEffect(() => {
    if (!onDismiss) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onDismiss(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onDismiss]);

  const shownViews = globalViews.slice(0, VIEWS_SHOWN);
  const moreViews = globalViews.length - shownViews.length;

  return (
    <div className="absolute inset-0 z-30 flex justify-center overflow-y-auto bg-brand-navy/30 backdrop-blur-sm p-6">
      <div
        role="dialog"
        aria-labelledby="welcome-title"
        className="relative my-auto w-full max-w-3xl overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-black/5"
      >
        <div className="relative overflow-hidden bg-brand-navy px-6 py-5 text-white">
          <div className="pointer-events-none absolute -right-10 -top-16 h-48 w-48 rounded-full bg-brand-blue/40 blur-3xl" />
          <div className="pointer-events-none absolute right-32 -bottom-20 h-40 w-40 rounded-full bg-brand-blue/20 blur-3xl" />
          <p className="relative text-xs font-semibold uppercase tracking-wider text-white/60">Welcome to Command Center</p>
          <h2 id="welcome-title" className="relative mt-1 text-xl font-semibold">See your data and act on it, in one place</h2>
          <p className="relative mt-1 text-sm text-white/70">Five ways in. Hover one to see where it lives.</p>
          {onDismiss && (
            <button
              type="button"
              onClick={onDismiss}
              className="absolute right-4 top-4 rounded-md p-1 text-white/60 hover:bg-white/10 hover:text-white"
              title="Close (Esc)"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>

        <div className="space-y-3 p-5">
          {agentName && (
            <div
              onMouseEnter={() => onSpot('assistant')}
              onMouseLeave={() => onSpot(null)}
              onFocus={() => onSpot('assistant')}
              onBlur={() => onSpot(null)}
              className="rounded-xl border border-brand-blue/30 bg-gradient-to-br from-brand-blue/10 via-white to-white p-4"
            >
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-blue text-white shadow-sm">
                  <Bot className="w-5 h-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <h3 className="text-base font-semibold text-gray-900">Ask {agentName}</h3>
                  <p className="text-sm text-gray-600">
                    Ask in plain words. It can see the view on screen and looks up data as you, so it only reaches what you can.
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {STARTER_QUESTIONS.map(q => (
                      <button
                        key={q}
                        type="button"
                        onClick={() => onAsk(q)}
                        className="rounded-full border border-brand-blue/30 bg-white px-3 py-1 text-xs text-brand-navy hover:border-brand-blue hover:bg-brand-blue hover:text-white transition-colors"
                      >
                        {q}
                      </button>
                    ))}
                    <button
                      type="button"
                      onClick={() => onAsk()}
                      className="inline-flex items-center gap-1 px-2 py-1 text-xs font-semibold text-brand-blue hover:underline"
                    >
                      Ask your own
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <Tile
              spot="global-views"
              onSpot={onSpot}
              icon={<LayoutGrid className="w-4 h-4" />}
              title="Browse global views"
              body="Ready-made views your team shares. Open one as it is, or copy it to My Views to make it yours."
            >
              {shownViews.length > 0 ? (
                <div className="flex flex-wrap items-center gap-1.5">
                  {shownViews.map(v => (
                    <button
                      key={v.id}
                      type="button"
                      onClick={() => onOpenView(v.id)}
                      className="max-w-[12rem] truncate rounded-md bg-gray-100 px-2 py-1 text-xs text-gray-700 hover:bg-brand-blue hover:text-white transition-colors"
                      title={`Open ${v.name}`}
                    >
                      {v.name}
                    </button>
                  ))}
                  {moreViews > 0 && <span className="text-xs text-gray-500">+{moreViews} more in the sidebar</span>}
                </div>
              ) : (
                <p className="text-xs text-gray-500">None in your domain yet.</p>
              )}
            </Tile>

            <Tile
              spot="library"
              onSpot={onSpot}
              icon={<Search className="w-4 h-4" />}
              title="Find widgets"
              body="Search the library of charts, tables and actions, then drag the ones you want onto a view."
            >
              <TileAction onClick={onOpenLibrary}>
                Open the Widget Library <kbd className="ml-1 rounded border border-gray-300 bg-gray-50 px-1 font-sans text-[10px] font-normal text-gray-500">W</kbd>
              </TileAction>
            </Tile>

            <Tile
              spot="studio"
              onSpot={onSpot}
              icon={<Code className="w-4 h-4" />}
              title="Build your own widget"
              body="Describe what you need. Widget Studio writes it, connects your data and shows it running as it goes."
              locked={!canBuild}
            >
              {canBuild ? <TileAction onClick={() => onOpenStudio('studio')}>Open Widget Studio</TileAction> : <NeedsEditor />}
            </Tile>

            <Tile
              spot="agent-studio"
              onSpot={onSpot}
              icon={<Sparkles className="w-4 h-4" />}
              title="Build your own agent"
              body="Give an assistant its own instructions, data and tools, try it out, then pin it to a view."
              locked={!canBuild}
            >
              {canBuild ? <TileAction onClick={() => onOpenStudio('agent-studio')}>Open Agent Studio</TileAction> : <NeedsEditor />}
            </Tile>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 bg-gray-50 px-5 py-3">
          <button
            type="button"
            onClick={onBlankView}
            className="inline-flex items-center gap-1.5 text-xs text-gray-600 hover:text-brand-blue"
          >
            <Plus className="w-3.5 h-3.5" />
            Or start from a blank view
          </button>
          <div className="flex items-center gap-4">
            <span className="text-xs text-gray-500">Reopen from <strong>Resources → Getting Started</strong></span>
            {onDismiss && (
              <button
                type="button"
                onClick={onDismiss}
                className="rounded-md bg-brand-navy px-4 py-1.5 text-sm font-semibold text-white hover:bg-brand-blue transition-colors"
              >
                Got it
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
