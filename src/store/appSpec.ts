// What an app is on the client. Mirrors `server/services/app_spec.py`, which
// validates every save; keep the two in step.

export interface WidgetLayout {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
  type: string;
  props?: Record<string, any>;
  static?: boolean;
}

/** One canvas of an app — what used to be a whole view. */
export interface AppTab {
  id: string;
  name: string;
  /** A canvas is a grid of cards; a page is one widget drawn edge to edge. */
  layout?: TabLayout;
  widgets: WidgetLayout[];
  /** Overrides the app's agent on this tab. Null = use the app's. */
  pinned_agent_id?: string | null;
}

export type TabLayout = 'canvas' | 'page';

export const isPage = (tab?: AppTab | null): boolean => tab?.layout === 'page';

/** Where a page's one widget sits if the tab later becomes a canvas. */
export const PAGE_WIDGET_PLACE = { x: 0, y: 0, w: 12, h: 10 };

/** Which way a tab's layout switch goes, and why it can't when it can't. */
export const layoutSwitch = (tab: AppTab): { to: TabLayout; title: string; blocked: boolean } => {
  if (isPage(tab)) return { to: 'canvas', title: 'Make this tab cards on a grid', blocked: false };
  const blocked = tab.widgets.length > 1;
  return {
    to: 'page',
    title: blocked ? 'A full page holds one widget; remove the others first' : 'Make this tab a full page: one widget filling the tab',
    blocked,
  };
};

export interface AppBranding {
  title?: string | null;
  logo?: string | null;
  favicon?: string | null;
}

/** Tabs across the top unless this says otherwise. */
export interface AppNav {
  style: 'tabs' | 'sidebar';
}

/**
 * A view's look, the same on every tab. `primary` and `dark` replace
 * Command Center's blue and navy; the rest styles the canvas around the cards.
 */
export interface AppTheme {
  primary?: string | null;
  dark?: string | null;
  background?: CanvasBackground | null;
  /** One of `FONTS` in fonts.ts. */
  font?: string | null;
  cards?: CardStyle | null;
}

export type CanvasBackground =
  | { kind: 'colour'; colour: string }
  | { kind: 'gradient'; from: string; to: string; direction: GradientDirection }
  | { kind: 'image'; url: string; fit: 'cover' | 'tile' };

export type GradientDirection = 'to-b' | 'to-r' | 'to-br' | 'to-tr';

export interface CardStyle {
  radius?: 'none' | 'sm' | 'md' | 'lg' | 'xl';
  depth?: 'flat' | 'border' | 'shadow';
  header?: 'bar' | 'minimal' | 'none';
}

/** The look every tab of a view is drawn with. */
export const effectiveTheme = (app?: App | null): AppTheme => app?.spec?.theme || {};

const GRADIENT_CSS: Record<GradientDirection, string> = {
  'to-b': 'to bottom', 'to-r': 'to right', 'to-br': 'to bottom right', 'to-tr': 'to top right',
};

/** The canvas's background as inline style; empty for Command Center's own. */
export const backgroundStyle = (background?: CanvasBackground | null): Record<string, string> => {
  if (!background) return {};
  if (background.kind === 'colour') return { background: background.colour };
  if (background.kind === 'gradient') {
    return { backgroundImage: `linear-gradient(${GRADIENT_CSS[background.direction] || 'to bottom'}, ${background.from}, ${background.to})` };
  }
  return background.fit === 'tile'
    ? { backgroundImage: `url("${background.url.replace(/"/g, '%22')}")`, backgroundRepeat: 'repeat' }
    : { backgroundImage: `url("${background.url.replace(/"/g, '%22')}")`, backgroundSize: 'cover', backgroundPosition: 'center' };
};

const RADIUS: Record<NonNullable<CardStyle['radius']>, string> = {
  none: 'rounded-none', sm: 'rounded-sm', md: 'rounded-md', lg: 'rounded-lg', xl: 'rounded-xl',
};
const DEPTH: Record<NonNullable<CardStyle['depth']>, string> = {
  flat: 'border border-transparent', border: 'border border-gray-200', shadow: 'border border-transparent shadow-md',
};

/** The classes a card is drawn with. Unset is Command Center's own card. */
export const cardClasses = (cards?: CardStyle | null) => ({
  frame: `${RADIUS[cards?.radius || 'lg']} ${cards?.depth ? DEPTH[cards.depth] : 'border border-gray-200 shadow-sm'}`,
  /** No title bar: the card's controls float over its top-right corner instead. */
  bare: cards?.header === 'none',
  header: cards?.header === 'minimal' ? 'bg-white' : 'bg-gray-50 border-b border-gray-100',
  title: cards?.header === 'minimal' ? 'text-sm font-semibold text-gray-800' : 'text-xs font-semibold text-gray-600 uppercase tracking-wide',
});

/** Command Center's own colours (`--brand-blue` / `--brand-navy` in index.css). */
export const DEFAULT_THEME = { primary: '#007bff', dark: '#001e3c' };

/** A dropdown in the view's filter bar; its choice is the dashboard variable `key`. */
export interface AppFilter {
  key: string;
  label: string;
  options: string[];
  default: string | null;
}

export interface AppSpec {
  schema: number;
  presentation: 'workspace' | 'standalone';
  assistant: 'on' | 'off';
  branding: AppBranding | null;
  tabs: AppTab[];
  nav: AppNav | null;
  theme: AppTheme | null;
  filters: AppFilter[];
}

/**
 * What the sidebar lists and the canvas shows. A view is an app with one tab,
 * and every app stored before apps existed reads that way, under its old id.
 */
export interface App {
  id: string;
  name: string;
  spec: AppSpec;
  locked?: boolean;
  domain?: string;
  is_global?: boolean;
  is_shared?: boolean;
  username?: string;
  version?: number;
  timestamp?: string | null;
  /** Agent Studio profile the assistant opens with on this app. Null = no pin. */
  pinned_agent_id?: string | null;
}

export const newAppSpec = (tabId: string): AppSpec => ({
  schema: 1,
  presentation: 'workspace',
  assistant: 'on',
  branding: null,
  tabs: [{ id: tabId, name: '', layout: 'canvas', widgets: [], pinned_agent_id: null }],
  nav: null,
  theme: null,
  filters: [],
});

/** The tab the canvas shows: the one a link or the tab bar named, else the first. */
export const shownTab = (app?: App | null, tabId?: string | null): AppTab | null =>
  app?.spec?.tabs?.find(t => t.id === tabId) ?? app?.spec?.tabs?.[0] ?? null;

/**
 * What a tab is called on screen. A view's only tab was never named (its name
 * is the view's), so once a second tab joins it, it reads as the app, wherever
 * it is moved to.
 */
export const tabLabel = (app: App, tab: AppTab, index: number): string =>
  tab.name || (index === 0 || tab.id === app.id ? app.name : `Tab ${index + 1}`);

/**
 * What a widget's `link` setting holds once someone picks where it goes: one of
 * the view's tabs, by id so a rename keeps it, or a web address.
 */
export type LinkTarget = { tab: string } | { url: string };

/**
 * The address as typed if it is http(s), else null. A setting is saved as
 * typed, so this is checked where the link opens, not only in the form.
 */
export const webAddress = (raw: unknown): string | null => {
  if (typeof raw !== 'string' || !raw.trim()) return null;
  try {
    const url = new URL(raw.trim());
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch {
    return null;
  }
};

export const isTabLink = (value: unknown): value is { tab: string } =>
  !!value && typeof value === 'object' && typeof (value as { tab?: unknown }).tab === 'string';

/**
 * A placed widget's settings with its tab links moved onto a copy's tab ids.
 * A copy gets new tab ids, and a link still naming the original's would go
 * nowhere.
 */
export const retargetLinks = (props: Record<string, unknown> | undefined, tabIds: Map<string, string>): Record<string, unknown> | undefined => {
  if (!props) return props;
  let changed = false;
  const next: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(props)) {
    const moved = isTabLink(value) ? tabIds.get(value.tab) : undefined;
    next[key] = moved ? { tab: moved } : value;
    if (moved) changed = true;
  }
  return changed ? next : props;
};

/** The agent the drawer opens with: the tab's own pin, else the app's. */
export const pinnedAgentOf = (app?: App | null, tab?: AppTab | null): string =>
  tab?.pinned_agent_id || app?.pinned_agent_id || '';

/** The built-in agent, which answers wherever no other agent is chosen. */
export const DEFAULT_AGENT_NAME = 'EDH Agent';

export const MAX_NAME_LENGTH = 120;
export const MAX_TABS = 50;
export const MAX_IMAGE_CHARS = 256 * 1024;
const IMAGE_DATA_URL = /^data:image\/(png|jpeg|gif|webp|svg\+xml|x-icon|vnd\.microsoft\.icon);base64,[A-Za-z0-9+/=\s]+$/;

/** Why the server would refuse this logo or favicon, or null if it would store it. */
export const imageProblem = (value: string): string | null => {
  if (!value) return null;
  if (value.length > MAX_IMAGE_CHARS) {
    return `That image is ${Math.ceil(value.length / 1024)} KB once stored; the limit is ${MAX_IMAGE_CHARS / 1024} KB.`;
  }
  if (value.startsWith('https://') || IMAGE_DATA_URL.test(value)) return null;
  return 'Use an https:// address, or upload a PNG, JPEG, GIF, WebP, SVG or ICO file.';
};

/** Why the server would refuse this look, or null if it would store it. */
export const lookProblem = (theme: AppTheme): string | null => {
  const colours = colourProblem(theme.primary || '') || colourProblem(theme.dark || '');
  if (colours) return colours;
  const bg = theme.background;
  if (bg?.kind === 'colour' && !HEX_COLOUR.test(bg.colour)) return 'Use a background color written as #rrggbb.';
  if (bg?.kind === 'gradient' && !(HEX_COLOUR.test(bg.from) && HEX_COLOUR.test(bg.to))) return 'Use gradient colors written as #rrggbb.';
  if (bg?.kind === 'image') return bg.url ? imageProblem(bg.url) : 'Choose a background image, or another kind of background.';
  return null;
};

/** A look as it is saved: unset keys left out, and nothing at all if nothing is set. */
export const savedLook = (theme: AppTheme): AppTheme | null => {
  const out: AppTheme = {};
  if (theme.primary) out.primary = theme.primary;
  if (theme.dark) out.dark = theme.dark;
  if (theme.background) out.background = theme.background;
  if (theme.font) out.font = theme.font;
  const cards = Object.fromEntries(Object.entries(theme.cards || {}).filter(([, v]) => v)) as CardStyle;
  if (Object.keys(cards).length) out.cards = cards;
  return Object.keys(out).length ? out : null;
};

export const navStyle = (app?: App | null): AppNav['style'] => app?.spec?.nav?.style === 'sidebar' ? 'sidebar' : 'tabs';

const HEX_COLOUR = /^#[0-9a-fA-F]{6}$/;
/** White text sits on both brand colours, so a theme colour must keep it readable. */
export const MIN_WHITE_CONTRAST = 3;

const channels = (hex: string): [number, number, number] =>
  [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number];

export const whiteTextContrast = (hex: string): number => {
  const [r, g, b] = channels(hex).map(v => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 1.05 / (0.2126 * r + 0.7152 * g + 0.0722 * b + 0.05);
};

/** Why the server would refuse this theme colour, or null if it would store it. */
export const colourProblem = (value: string): string | null => {
  if (!value) return null;
  if (!HEX_COLOUR.test(value)) return 'Use a color written as #rrggbb.';
  if (whiteTextContrast(value) < MIN_WHITE_CONTRAST) return 'Too light: white text on it would be hard to read. Choose a darker color.';
  return null;
};

/** The CSS variables `brand-blue` and `brand-navy` read, for a theme. */
export const themeVariables = (theme?: AppTheme | null): Record<string, string> => {
  const out: Record<string, string> = {};
  if (theme?.primary && !colourProblem(theme.primary)) out['--brand-blue'] = channels(theme.primary).join(' ');
  if (theme?.dark && !colourProblem(theme.dark)) out['--brand-navy'] = channels(theme.dark).join(' ');
  return out;
};

export const MAX_FILTERS = 10;
export const MAX_FILTER_OPTIONS = 100;
const FILTER_KEY = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;

/** Why the server would refuse these filters, or null if it would store them. */
export const filtersProblem = (filters: AppFilter[]): string | null => {
  if (filters.length > MAX_FILTERS) return `A view may have at most ${MAX_FILTERS} filters.`;
  const keys = new Set<string>();
  for (const [index, f] of filters.entries()) {
    const which = `Filter ${index + 1}`;
    if (!FILTER_KEY.test(f.key)) return `${which}: the variable must be letters, digits and underscores, not starting with a digit.`;
    if (keys.has(f.key)) return `${which}: another filter already sets “${f.key}”.`;
    keys.add(f.key);
    if (f.label.length > MAX_NAME_LENGTH) return `${which}: the label is longer than ${MAX_NAME_LENGTH} characters.`;
    if (!f.options.length) return `${which}: add at least one option.`;
    if (f.options.length > MAX_FILTER_OPTIONS) return `${which}: at most ${MAX_FILTER_OPTIONS} options.`;
    if (f.options.some(o => !o || o.length > MAX_NAME_LENGTH)) return `${which}: options can't be empty or longer than ${MAX_NAME_LENGTH} characters.`;
    if (new Set(f.options).size !== f.options.length) return `${which}: an option is listed twice.`;
    if (f.default && !f.options.includes(f.default)) return `${which}: the default must be one of its options.`;
  }
  return null;
};

/** The variables a view's filters start with, before anyone chooses. */
export const filterDefaults = (filters?: AppFilter[] | null): Record<string, string> => {
  const out: Record<string, string> = {};
  for (const f of filters || []) if (f.default) out[f.key] = f.default;
  return out;
};

export const withTab = (app: App, tabId: string, change: (tab: AppTab) => AppTab): App => ({
  ...app,
  spec: { ...app.spec, tabs: app.spec.tabs.map(t => (t.id === tabId ? change(t) : t)) },
});
