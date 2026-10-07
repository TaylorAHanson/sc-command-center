import React, { useEffect, useState } from 'react';
import { Sparkles, Undo2, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import {
  backgroundStyle, BAR_SURFACE, canvasTone, cardClasses, cardSpacing, DEFAULT_THEME, imageProblem,
  type AppTheme, type CanvasBackground, type CardStyle, type GradientDirection,
} from '../store/appSpec';
import { FONTS, fontById, loadFont } from '../fonts';
import { ColourField, FieldHelp, FieldLabel, ImageField } from './SettingsFields';

const BACKGROUND_START: Record<CanvasBackground['kind'], CanvasBackground> = {
  colour: { kind: 'colour', colour: '#0b1220' },
  gradient: { kind: 'gradient', from: '#0b1220', to: '#1e3a8a', direction: 'to-br' },
  image: { kind: 'image', url: '', fit: 'cover' },
};

const DIRECTIONS: [GradientDirection, string][] = [
  ['to-b', 'Top to bottom'], ['to-r', 'Left to right'], ['to-br', 'Diagonal, downwards'], ['to-tr', 'Diagonal, upwards'],
];

const CARD_CHOICES: { key: keyof CardStyle; label: string; help: string; options: [string, string][] }[] = [
  { key: 'radius', label: 'Corners', help: 'How rounded each card’s corners are, from square to very rounded.', options: [['none', 'Square'], ['sm', 'Slightly rounded'], ['md', 'Rounded'], ['lg', 'More rounded'], ['xl', 'Very rounded']] },
  { key: 'depth', label: 'Edges', help: 'Flat cards have no edge, Outlined adds a thin line, and Shadowed lifts each card off the background.', options: [['flat', 'Flat'], ['border', 'Outlined'], ['shadow', 'Shadowed']] },
  { key: 'header', label: 'Title', help: 'In a gray bar is Command Center’s usual card header; Plain drops the tint and capitals; the color bars put the title in white on the accent or dark color. With No title, a card’s buttons appear when you hover over it.', options: [['bar', 'In a gray bar'], ['accent', 'In an accent-color bar'], ['dark', 'In a dark-color bar'], ['minimal', 'Plain'], ['none', 'No title']] },
  { key: 'spacing', label: 'Spacing', help: 'The space between cards, and around the edge of the tab.', options: [['compact', 'Compact'], ['roomy', 'Roomy']] },
];

const selectClass = 'w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-brand-blue/40';

/** Colors, background, font and cards for a view, the same on every tab. */
export const LookEditor: React.FC<{
  value: AppTheme;
  onChange: (next: AppTheme) => void;
  /** The view is one page, which draws its own background and has no cards. */
  page?: boolean;
}> = ({ value, onChange, page = false }) => {
  const [description, setDescription] = useState('');
  const [asking, setAsking] = useState(false);
  const [note, setNote] = useState<{ text: string; error: boolean } | null>(null);
  const [before, setBefore] = useState<AppTheme | null>(null);
  useEffect(() => { loadFont(value.font); }, [value.font]);

  const set = (change: Partial<AppTheme>) => onChange({ ...value, ...change });
  const setCard = (key: keyof CardStyle, v: string) => set({ cards: { ...value.cards, [key]: v || undefined } });

  const describe = async () => {
    setAsking(true);
    setNote(null);
    try {
      const res = await fetch('/api/apps/look', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description, current: value }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setNote({ text: typeof body.detail === 'string' ? body.detail : 'That didn’t work. Try again in a moment.', error: true });
        return;
      }
      setBefore(value);
      onChange(page ? { ...body.theme, background: undefined, cards: undefined } : body.theme);
      const dropped: string[] = body.dropped || [];
      setNote({
        text: dropped.length
          ? `Filled in below; nothing is saved until you press Save. Left out: ${dropped.join(', ')}, which couldn’t be drawn.`
          : 'Filled in below; nothing is saved until you press Save.',
        error: false,
      });
    } catch {
      setNote({ text: 'That didn’t work. Try again in a moment.', error: true });
    } finally {
      setAsking(false);
    }
  };

  const bg = value.background;
  return (
    <div className="space-y-3">
      <div>
        <div className="flex gap-2">
          <input
            type="text"
            value={description}
            maxLength={1000}
            onChange={e => setDescription(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && description.trim() && !asking) { e.preventDefault(); describe(); } }}
            placeholder="Describe the look: “dark navy, like a control room, rounded cards”"
            aria-label="Describe the look"
            className="flex-1 min-w-0 px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-brand-blue/40"
          />
          <button
            type="button"
            onClick={describe}
            disabled={asking || !description.trim()}
            className="flex items-center gap-1 px-3 py-1.5 text-sm text-white bg-brand-blue rounded-md hover:bg-brand-navy disabled:opacity-50"
          >
            {asking ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            Suggest
          </button>
          <span className="self-center">
            <FieldHelp
              about="Describe the look"
              text="Describe the style you want in your own words and Suggest fills in the choices below. Nothing is saved until you press Save, and Undo puts back what was there."
            />
          </span>
        </div>
        {note && (
          <p className={clsx('text-xs mt-1 flex items-center gap-2', note.error ? 'text-red-600' : 'text-gray-500')}>
            <span>{note.text}</span>
            {before && !note.error && (
              <button
                type="button"
                onClick={() => { onChange(before); setBefore(null); setNote(null); }}
                className="inline-flex items-center gap-0.5 text-brand-blue hover:text-brand-navy shrink-0"
              >
                <Undo2 className="w-3 h-3" /> Undo
              </button>
            )}
          </p>
        )}
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_16rem] gap-5 items-start">
        <div className="space-y-3 min-w-0">
          <div className="grid grid-cols-2 gap-3">
            <ColourField
              label="Accent color"
              help="Takes the place of Command Center’s blue on this view: the selected tab, buttons, links and highlights in widgets. White text sits on it, so it must be dark enough to read."
              fallback={DEFAULT_THEME.primary}
              value={value.primary || ''}
              onChange={v => set({ primary: v || undefined })}
            />
            <ColourField
              label="Dark color"
              help="Takes the place of Command Center’s navy on this view: the title, headings, dark buttons and panels in widgets. It must be dark enough for white text."
              fallback={DEFAULT_THEME.dark}
              value={value.dark || ''}
              onChange={v => set({ dark: v || undefined })}
            />
          </div>

          <div>
            <FieldLabel
              label="Font"
              help="The typeface for the view’s tabs, filters and cards, and the widgets in them. Only fonts bundled with the app are offered."
              className="text-sm font-medium text-gray-700 mb-1"
            />
            <select
              value={value.font || ''}
              onChange={e => set({ font: e.target.value || undefined })}
              aria-label="Font"
              className={selectClass}
            >
              <option value="">Command Center’s</option>
              {FONTS.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}
            </select>
          </div>

          <div>
            <FieldLabel
              label="Header"
              help="The bar along the top with the view’s title, and the assistant’s beside it, when the view is opened on its own. Inside Command Center, Command Center’s header is used. The tabs sit on the background below either way."
              className="text-sm font-medium text-gray-700 mb-1"
            />
            <select
              value={value.bars || ''}
              onChange={e => set({ bars: (e.target.value || undefined) as AppTheme['bars'] })}
              aria-label="Header"
              className={selectClass}
            >
              <option value="">White</option>
              <option value="dark">The dark color</option>
            </select>
          </div>

          {page ? (
            <p className="text-xs text-gray-500">This view is a page: its widget draws its own background, so only the colors and font apply.</p>
          ) : (
            <>
              <div className="space-y-2">
                <FieldLabel
                  label="Background"
                  help="Everything under the header sits on it: the tabs, the filters, the cards and the assistant’s messages. Cards and messages stay white, and text drawn straight on a dark background turns light."
                  className="text-sm font-medium text-gray-700"
                />
                <select
                  value={bg?.kind || ''}
                  onChange={e => set({ background: e.target.value ? BACKGROUND_START[e.target.value as CanvasBackground['kind']] : undefined })}
                  aria-label="Background"
                  className={selectClass}
                >
                  <option value="">Command Center’s light gray</option>
                  <option value="colour">A color</option>
                  <option value="gradient">A gradient</option>
                  <option value="image">An image</option>
                </select>
                {bg?.kind === 'colour' && (
                  <ColourField label="Background color" fallback="#0b1220" value={bg.colour} onWhite={false} clearLabel=""
                    help="The color behind the cards. Light or dark both work."
                    onChange={v => set({ background: { ...bg, colour: v } })} />
                )}
                {bg?.kind === 'gradient' && (
                  <>
                    <div className="grid grid-cols-2 gap-3">
                      <ColourField label="From" fallback="#0b1220" value={bg.from} onWhite={false} clearLabel=""
                        help="The color the gradient starts with, on the side the direction below starts from."
                        onChange={v => set({ background: { ...bg, from: v } })} />
                      <ColourField label="To" fallback="#1e3a8a" value={bg.to} onWhite={false} clearLabel=""
                        help="The color the gradient ends with."
                        onChange={v => set({ background: { ...bg, to: v } })} />
                    </div>
                    <select
                      value={bg.direction}
                      onChange={e => set({ background: { ...bg, direction: e.target.value as GradientDirection } })}
                      aria-label="Gradient direction"
                      className={selectClass}
                    >
                      {DIRECTIONS.map(([d, label]) => <option key={d} value={d}>{label}</option>)}
                    </select>
                  </>
                )}
                {bg?.kind === 'image' && (
                  <>
                    <ImageField label="Background image" hint="Up to 256 KB uploaded, or an https:// address." value={bg.url}
                      help="A picture that fills or tiles the area behind the cards. Upload one, or paste an https:// address."
                      onChange={v => set({ background: { ...bg, url: v } })} />
                    <select
                      value={bg.fit}
                      onChange={e => set({ background: { ...bg, fit: e.target.value as 'cover' | 'tile' } })}
                      aria-label="Image fit"
                      className={selectClass}
                    >
                      <option value="cover">Fill the background</option>
                      <option value="tile">Repeat as tiles</option>
                    </select>
                  </>
                )}
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Cards</label>
                <div className="grid grid-cols-2 gap-2">
                  {CARD_CHOICES.map(choice => (
                    <div key={choice.key}>
                      <FieldLabel label={choice.label} help={choice.help} about={`card ${choice.label.toLowerCase()}`} className="text-xs text-gray-500 mb-0.5" />
                      <select
                        value={value.cards?.[choice.key] || ''}
                        onChange={e => setCard(choice.key, e.target.value)}
                        aria-label={`Card ${choice.label.toLowerCase()}`}
                        className={selectClass}
                      >
                        <option value="">Standard</option>
                        {choice.options.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                      </select>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>

        <div className="sticky top-0">
          <span className="block text-xs text-gray-500 mb-1">Preview</span>
          <LookPreview look={value} page={page} />
        </div>
      </div>
    </div>
  );
};

const LookPreview: React.FC<{ look: AppTheme; page: boolean }> = ({ look, page }) => {
  const primary = look.primary || DEFAULT_THEME.primary;
  const dark = look.dark || DEFAULT_THEME.dark;
  const cards = cardClasses(page ? null : look.cards);
  const drawable = look.background?.kind !== 'image' || (look.background.url && !imageProblem(look.background.url));
  const background = page || !drawable ? undefined : look.background;
  const darkBar = look.bars === 'dark';
  const surface = background ? canvasTone(background) : 'plain';
  const gap = cardSpacing(page ? null : look.cards).margin[0];
  // The preview sits inside the editor, so the draft colors are set inline
  // rather than through --brand-blue / --brand-navy.
  const tint = look.cards?.header === 'accent' ? primary : look.cards?.header === 'dark' ? dark : undefined;
  const card = (title: string, figure: string) => (
    <div className={clsx('bg-white overflow-hidden flex-1 min-w-0', cards.frame)}>
      {!cards.bare && (
        <div className={clsx('px-3 py-1.5 truncate', cards.header)} style={tint ? { background: tint } : undefined}>
          <span className={cards.title}>{title}</span>
        </div>
      )}
      <div className="px-3 py-2 text-sm text-gray-700 truncate">
        <span className="font-semibold" style={{ color: primary }}>{figure}</span>
      </div>
    </div>
  );
  return (
    <div
      className="rounded-md border border-gray-200 overflow-hidden"
      style={{ fontFamily: fontById(look.font)?.stack }}
      data-look-preview
      aria-hidden
    >
      <div
        className={clsx('px-3 py-1.5 text-xs font-semibold border-b', darkBar ? 'text-white border-white/10' : 'bg-white border-gray-200')}
        style={darkBar ? { background: dark } : { color: dark }}
      >
        Your view
      </div>
      <div className={clsx(!background && 'bg-gray-50')} style={backgroundStyle(background)}>
        <div className={clsx('flex gap-3 px-3 pt-1 text-xs border-b', BAR_SURFACE[surface])}>
          <span
            className={clsx('pb-1 border-b-2 font-medium', surface === 'dark' && 'text-white border-white')}
            style={surface === 'dark' ? undefined : { borderColor: primary, color: dark }}
          >
            Tab
          </span>
          <span className={surface === 'dark' ? 'text-white/70' : 'text-gray-500'}>Another</span>
        </div>
        <div style={{ padding: page ? 12 : Math.max(gap, 6) }}>
          {page ? (
            <p className={clsx('text-sm', surface === 'dark' ? 'text-white/70' : 'text-gray-500')}>The page’s widget fills this space.</p>
          ) : (
            <div className="flex" style={{ gap }}>
              {card('Revenue', '$1.2M')}
              {card('Orders', '8,410')}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
