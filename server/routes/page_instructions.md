## You are building a page, not a card

This widget is a **page**: it fills a whole tab of a view, edge to edge, under the
view's header and tab bar. There is no card around it, no title bar and no grid
tile. Think landing page or hub — a headline, sections, cards of your own, a call
to action — not a panel. Everything above still applies except these rules, which
replace the ones about the card:

- **You own the background.** Ignore "rendered on a solid white background": set
  the page's background on your root element — a Tailwind class, or an inline
  `style` for anything the classes can't express (a gradient between two exact
  colours, a radial glow). Text must contrast with *your* background: light text
  on a dark page, dark text on a light one, and dark text again inside any white
  card you draw on top. Every text colour, including placeholders, helper text
  and hover states, is judged against what is actually behind it.
- **Size.** The root is `className="min-h-full w-full"`, not `h-full`: a page
  scrolls vertically when it is longer than the tab, and must never shrink its
  content to fit. Design for the viewport width, from a narrow laptop up to a wide
  monitor; below about 900px, stack columns into one (`grid-cols-1 lg:grid-cols-3`
  and the like). Constrain reading width with a centred `max-w-6xl mx-auto` (or
  similar) container rather than stretching text across a wide screen.
- **Ignore default width and height.** `defaultW` / `defaultH` in the
  widget-meta block only matter if someone puts the page on a canvas; suggest
  `12` and `10`.
- **Typography.** The page may set its own font with an inline
  `style={{ fontFamily: … }}`, using only these bundled families (anything else
  falls back to the system font, because the app can't load fonts from the
  internet):
  `'Inter Variable'`, `'Manrope Variable'`, `'Space Grotesk Variable'`,
  `'Fraunces Variable'` (a serif, good for display headlines),
  `'IBM Plex Sans Variable'`, `'JetBrains Mono Variable'`.
  Always end the stack with a generic family, e.g.
  `fontFamily: "'Fraunces Variable', ui-serif, Georgia, serif"`. With no
  `fontFamily` the page uses the view's font.
- **Moving around the view.** Pages are how people get around an app. Every card
  or tile that stands for a part of the app (a persona, a team, a topic, "see the
  details") or for an outside site is a **link**: declare it under `links` in the
  `widget-meta` block and follow it with `props.app.link(props.data.<key>)`, as
  the widget contract shows. Do this even when the request doesn't mention tabs:
  the page is built before the view's tabs are, and whoever places it points each
  link at a tab or a web address from its settings. Until they do, `link()`
  returns null and the tile is drawn muted. In the studio's preview, links go to
  stand-in tabs (Overview, Details) and say what they would do instead of doing
  it. Controls that ask something (an "Ask" button, a search box) use
  `props.app.openAssistant`. Never write an address into the code.
- **Connectors and decoration.** Lines joining cards, glows and shapes are inline
  SVG or absolutely positioned elements; keep them `pointer-events-none` and
  `aria-hidden`, and make sure they reflow with the layout (a line drawn for
  three columns must not cross the text when the page stacks).
- **A reference image** attached to the request is the design to follow: match its
  layout, hierarchy and palette with the bundled fonts and real data or tab
  names, rather than copying its text.
