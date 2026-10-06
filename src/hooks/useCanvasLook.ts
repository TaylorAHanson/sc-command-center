import { useEffect, useMemo } from 'react';
import { backgroundStyle, cardClasses, effectiveTheme, isPage, type App, type AppTab } from '../store/appSpec';
import { fontById, loadFont } from '../fonts';

/**
 * How the tab on screen is drawn: its look over the view's, key by key. A page
 * draws its own background and has no cards, so it gets only the colours and font.
 */
export const useCanvasLook = (app?: App | null, tab?: AppTab | null) => {
  const theme = useMemo(() => effectiveTheme(app, tab), [app, tab]);
  const font = fontById(theme.font);
  useEffect(() => { loadFont(font?.id); }, [font?.id]);
  const page = isPage(tab);
  const background = page ? undefined : theme.background;
  const cards = page ? undefined : theme.cards;
  return useMemo(() => ({
    theme,
    fontStack: font?.stack,
    canvasStyle: backgroundStyle(background),
    cards: cardClasses(cards),
  }), [theme, font?.stack, background, cards]);
};
