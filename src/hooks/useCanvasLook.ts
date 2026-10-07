import { useEffect, useMemo } from 'react';
import { backgroundStyle, canvasTone, cardClasses, effectiveTheme, isPage, type App, type AppTab } from '../store/appSpec';
import { fontById, loadFont } from '../fonts';

/**
 * How the view on screen is drawn. Its background covers everything under the
 * header (tabs, filters, canvas and the assistant) as one surface, so nothing
 * there draws a band of its own; a page has no cards.
 */
export const useCanvasLook = (app?: App | null, tab?: AppTab | null) => {
  const theme = useMemo(() => effectiveTheme(app), [app]);
  const font = fontById(theme.font);
  useEffect(() => { loadFont(font?.id); }, [font?.id]);
  const cards = isPage(tab) ? undefined : theme.cards;
  return useMemo(() => ({
    theme,
    fontStack: font?.stack,
    /** For the area under the header; unset leaves Command Center's gray. */
    areaStyle: backgroundStyle(theme.background),
    hasBackground: !!theme.background,
    tone: canvasTone(theme.background),
    cards: cardClasses(cards),
  }), [theme, font?.stack, cards]);
};
