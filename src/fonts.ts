// The typefaces a view's look may use. They ship with the app because the CSP
// allows fonts only from it; each one's CSS (and so its files) is fetched the
// first time something asks for it. Mirrors FONTS in server/services/app_spec.py.

export interface BundledFont {
  id: string;
  label: string;
  /** The CSS family a widget names in `fontFamily`. */
  family: string;
  stack: string;
  load: () => Promise<unknown>;
}

const SANS = 'ui-sans-serif, system-ui, sans-serif';

export const FONTS: BundledFont[] = [
  { id: 'inter', label: 'Inter', family: 'Inter Variable', stack: `'Inter Variable', ${SANS}`, load: () => import('@fontsource-variable/inter') },
  { id: 'manrope', label: 'Manrope', family: 'Manrope Variable', stack: `'Manrope Variable', ${SANS}`, load: () => import('@fontsource-variable/manrope') },
  { id: 'space-grotesk', label: 'Space Grotesk', family: 'Space Grotesk Variable', stack: `'Space Grotesk Variable', ${SANS}`, load: () => import('@fontsource-variable/space-grotesk') },
  { id: 'fraunces', label: 'Fraunces (serif)', family: 'Fraunces Variable', stack: `'Fraunces Variable', ui-serif, Georgia, serif`, load: () => import('@fontsource-variable/fraunces') },
  { id: 'ibm-plex-sans', label: 'IBM Plex Sans', family: 'IBM Plex Sans Variable', stack: `'IBM Plex Sans Variable', ${SANS}`, load: () => import('@fontsource-variable/ibm-plex-sans') },
  { id: 'jetbrains-mono', label: 'JetBrains Mono (monospace)', family: 'JetBrains Mono Variable', stack: `'JetBrains Mono Variable', ui-monospace, monospace`, load: () => import('@fontsource-variable/jetbrains-mono') },
];

const byId = new Map(FONTS.map(f => [f.id, f]));
const loading = new Map<string, Promise<unknown>>();

export const fontById = (id?: string | null): BundledFont | undefined => (id ? byId.get(id) : undefined);

/** Starts fetching a font once; later calls get the same load. */
export const loadFont = (id?: string | null): void => {
  const font = fontById(id);
  if (!font || loading.has(font.id)) return;
  loading.set(font.id, font.load().catch(err => {
    loading.delete(font.id);
    console.warn(`Could not load the font ${font.label}:`, err);
  }));
};

/** Loads every bundled font a widget's code names, so a page can use one the view's look doesn't. */
export const loadFontsNamedIn = (code: string): void => {
  for (const font of FONTS) if (code.includes(font.family)) loadFont(font.id);
};
