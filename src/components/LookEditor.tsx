import React, { useEffect, useState } from 'react';
import { Sparkles, Undo2, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import {
  backgroundStyle, cardClasses, DEFAULT_THEME, imageProblem, mergeLook,
  type AppTheme, type CanvasBackground, type CardStyle, type GradientDirection,
} from '../store/appSpec';
import { FONTS, fontById, loadFont } from '../fonts';
import { ColourField, ImageField } from './SettingsFields';

const BACKGROUND_START: Record<CanvasBackground['kind'], CanvasBackground> = {
  colour: { kind: 'colour', colour: '#0b1220' },
  gradient: { kind: 'gradient', from: '#0b1220', to: '#1e3a8a', direction: 'to-br' },
  image: { kind: 'image', url: '', fit: 'cover' },
};

const DIRECTIONS: [GradientDirection, string][] = [
  ['to-b', 'Top to bottom'], ['to-r', 'Left to right'], ['to-br', 'Diagonal, downwards'], ['to-tr', 'Diagonal, upwards'],
];

const CARD_CHOICES: { key: keyof CardStyle; label: string; options: [string, string][] }[] = [
  { key: 'radius', label: 'Corners', options: [['none', 'Square'], ['sm', 'Slightly rounded'], ['md', 'Rounded'], ['lg', 'More rounded'], ['xl', 'Very rounded']] },
  { key: 'depth', label: 'Edges', options: [['flat', 'Flat'], ['border', 'Outlined'], ['shadow', 'Shadowed']] },
  { key: 'header', label: 'Title', options: [['bar', 'In a grey bar'], ['minimal', 'Plain']] },
];

const selectClass = 'w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md bg-white focus:outline-none focus:ring-2 focus:ring-brand-blue/40';

/**
 * Colours, background, font and cards for a view, or for one tab over its view.
 * With `inherited`, every choice can be left as "Same as the view".
 */
export const LookEditor: React.FC<{
  value: AppTheme;
  onChange: (next: AppTheme) => void;
  /** The view's look, for a tab: what each unset choice falls back to. */
  inherited?: AppTheme;
  /** The tab is a page, which draws its own background and has no cards. */
  page?: boolean;
  /** Distinguishes the view's editor from the tab's for assistive technology. */
  name: string;
}> = ({ value, onChange, inherited, page = false, name }) => {
  const [description, setDescription] = useState('');
  const [asking, setAsking] = useState(false);
  const [note, setNote] = useState<{ text: string; error: boolean } | null>(null);
  const [before, setBefore] = useState<AppTheme | null>(null);
  const shown = mergeLook(inherited, value);
  const sameLabel = inherited ? 'Same as the view' : null;
  useEffect(() => { loadFont(shown.font); }, [shown.font]);

  const set = (change: Partial<AppTheme>) => onChange({ ...value, ...change });
  const setCard = (key: keyof CardStyle, v: string) => set({ cards: { ...value.cards, [key]: v || undefined } });

  const describe = async () => {
    setAsking(true);
    setNote(null);
    try {
      const res = await fetch('/api/apps/look', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description, current: shown }),
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
    <div className="space-y-3" aria-label={name} role="group">
      <div>
        <div className="flex gap-2">
          <input
            type="text"
            value={description}
            maxLength={1000}
            onChange={e => setDescription(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && description.trim() && !asking) { e.preventDefault(); describe(); } }}
            placeholder="Describe the look: “dark navy, like a control room, rounded cards”"
            aria-label={`Describe the look (${name})`}
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

      <div className="grid grid-cols-2 gap-3">
        <ColourField
          label="Accent colour"
          fallback={inherited?.primary || DEFAULT_THEME.primary}
          value={value.primary || ''}
          onChange={v => set({ primary: v || undefined })}
          clearLabel={inherited ? 'As the view' : undefined}
        />
        <ColourField
          label="Dark colour"
          fallback={inherited?.dark || DEFAULT_THEME.dark}
          value={value.dark || ''}
          onChange={v => set({ dark: v || undefined })}
          clearLabel={inherited ? 'As the view' : undefined}
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Font</label>
        <select
          value={value.font || ''}
          onChange={e => set({ font: e.target.value || undefined })}
          aria-label={`Font (${name})`}
          className={selectClass}
        >
          <option value="">{sameLabel || 'Command Center’s'}</option>
          {FONTS.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}
        </select>
      </div>

      {page ? (
        <p className="text-xs text-gray-500">This tab is a page: its widget draws its own background, so only the colours and font apply.</p>
      ) : (
        <>
          <div className="space-y-2">
            <label className="block text-sm font-medium text-gray-700">Background</label>
            <select
              value={bg?.kind || ''}
              onChange={e => set({ background: e.target.value ? BACKGROUND_START[e.target.value as CanvasBackground['kind']] : undefined })}
              aria-label={`Background (${name})`}
              className={selectClass}
            >
              <option value="">{sameLabel || 'Command Center’s light grey'}</option>
              <option value="colour">A colour</option>
              <option value="gradient">A gradient</option>
              <option value="image">An image</option>
            </select>
            {bg?.kind === 'colour' && (
              <ColourField label="Background colour" fallback="#0b1220" value={bg.colour} onWhite={false} clearLabel=""
                onChange={v => set({ background: { ...bg, colour: v } })} />
            )}
            {bg?.kind === 'gradient' && (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <ColourField label="From" fallback="#0b1220" value={bg.from} onWhite={false} clearLabel=""
                    onChange={v => set({ background: { ...bg, from: v } })} />
                  <ColourField label="To" fallback="#1e3a8a" value={bg.to} onWhite={false} clearLabel=""
                    onChange={v => set({ background: { ...bg, to: v } })} />
                </div>
                <select
                  value={bg.direction}
                  onChange={e => set({ background: { ...bg, direction: e.target.value as GradientDirection } })}
                  aria-label={`Gradient direction (${name})`}
                  className={selectClass}
                >
                  {DIRECTIONS.map(([d, label]) => <option key={d} value={d}>{label}</option>)}
                </select>
              </>
            )}
            {bg?.kind === 'image' && (
              <>
                <ImageField label="Background image" hint="Up to 256 KB uploaded, or an https:// address." value={bg.url}
                  onChange={v => set({ background: { ...bg, url: v } })} />
                <select
                  value={bg.fit}
                  onChange={e => set({ background: { ...bg, fit: e.target.value as 'cover' | 'tile' } })}
                  aria-label={`Image fit (${name})`}
                  className={selectClass}
                >
                  <option value="cover">Fill the canvas</option>
                  <option value="tile">Repeat as tiles</option>
                </select>
              </>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Cards</label>
            <div className="grid grid-cols-3 gap-2">
              {CARD_CHOICES.map(choice => (
                <div key={choice.key}>
                  <span className="block text-xs text-gray-500 mb-0.5">{choice.label}</span>
                  <select
                    value={value.cards?.[choice.key] || ''}
                    onChange={e => setCard(choice.key, e.target.value)}
                    aria-label={`Card ${choice.label.toLowerCase()} (${name})`}
                    className={selectClass}
                  >
                    <option value="">{sameLabel ? 'As the view' : 'Standard'}</option>
                    {choice.options.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                  </select>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      <LookPreview look={shown} page={page} />
    </div>
  );
};

const LookPreview: React.FC<{ look: AppTheme; page: boolean }> = ({ look, page }) => {
  const primary = look.primary || DEFAULT_THEME.primary;
  const dark = look.dark || DEFAULT_THEME.dark;
  const cards = cardClasses(page ? null : look.cards);
  const drawable = look.background?.kind !== 'image' || (look.background.url && !imageProblem(look.background.url));
  const background = page || !drawable ? undefined : look.background;
  return (
    <div
      className="rounded-md border border-gray-200 overflow-hidden"
      style={{ fontFamily: fontById(look.font)?.stack }}
      data-look-preview
      aria-hidden
    >
      <div className="flex items-center gap-2 px-3 py-1.5 text-xs text-white" style={{ background: dark }}>
        <span className="font-semibold">Preview</span>
        <span className="ml-auto px-2 py-0.5 rounded" style={{ background: primary }}>Tab</span>
      </div>
      <div className={clsx('p-3', !background && 'bg-gray-50')} style={backgroundStyle(background)}>
        {page ? (
          <p className="text-sm text-gray-500">The page’s widget fills this space.</p>
        ) : (
          <div className={clsx('bg-white overflow-hidden w-2/3', cards.frame)}>
            <div className={clsx('px-3 py-1.5', cards.header)}><span className={cards.title}>A card</span></div>
            <div className="px-3 py-2 text-sm text-gray-700">
              Revenue <span className="font-semibold" style={{ color: primary }}>$1.2M</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
