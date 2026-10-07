# ADR-002 — Page tabs: a tab that is one full-screen widget

| Field | Value |
| --- | --- |
| Status | Accepted — being built slice by slice (see §4) |
| Date | 2026-10-05 |
| Builds on | ADR-001 (apps, tabs, `nav` / `theme` / `filters` in the spec) |
| Scope | Page tabs; page widgets in Widget Studio; an app API for widget code; app and tab style (background, colours, font, cards) |
| Out of scope | Model-written CSS or shell code; a separate page artifact; dark-mode remapping of existing widgets; responsive grid layouts |

---

## 1. The ask

**Any tab** of an app should be able to be a **designed page**, a landing hub like
"Kairos Intelligence Hub": a warm gradient, a display headline, persona cards
joined by connector lines to a central "Ask Kairos AI" card, chips, quotes, a
call to action. It is vibed into existing, not configured. Pages and widget
canvases mix freely, in any order and any number: a hub first, two canvases, a
page per persona, a closing page. Canvas tabs each carry their own background and
colours.

**A page is a widget.** It's authored in Widget Studio, stored and versioned in
`widgets`, governed, certified and promoted the way widgets are. The new things
are where it's *placed* (filling a tab instead of a grid card) and what it may
*do* (move around the app, open the assistant). No new artifact, no second
studio for pages, no model-written CSS.

### 1.1 What the code allows today

- **A widget can already draw that page.** Widgets render in the app's own DOM
  with the app's compiled Tailwind stylesheet (only classes the app itself uses,
  plus a safelist: see the slice 3 entry in the change log); arbitrary values aren't available,
  but inline `style` is, and so are SVG (the connector lines), gradients
  (`bg-gradient-to-*` or inline), and https images. Icons must be inline SVG
  (no `lucide-react` in widget code).
- **But it can't own a tab.** Every widget sits in a `BaseWidget` card on the
  12-column grid (white, bordered, title bar, drag handle, height in 60px rows).
  Fullscreen exists only as a temporary overlay inside a white card.
- **Widget Studio builds cards.** The contract (`agent_instructions.md`) says
  "rendered on a **solid white background**", insists on dark text, and frames
  every widget as a resizable grid tile; `widgetLint` flags light text without a
  dark *class* background, so a page that sets its background inline is flagged
  wrongly. The preview is card-sized.
- **A widget can't act on the app.** It gets `id`, `data`, `variables`,
  `setVariable`, `executeAction`. It can't switch tabs or open the assistant, so
  "Ask the supervisor" and a persona card that opens its tab are impossible.
- **Fonts:** the CSP allows `font-src 'self' data:` only, so a display face must
  be bundled with the app.

---

## 2. Design

### 2.1 Page tabs (spec + shell)

A tab gets a layout:

```json
{ "id": "home", "name": "Hub", "layout": "page", "widgets": [ { "i": "w-1", "type": "kairos-hub", "props": {…} } ] }
```

- `layout` is per tab, on any tab: `"canvas"` (default, today's grid) or
  `"page"`. Nothing ties it to position; an app may be all pages, all canvases,
  or any mix, and reordering tabs carries each tab's layout. A page tab holds **at
  most one** widget instance; the validator refuses more on write, and on read a
  page tab with several keeps the first (read lenient, write strict, as always).
- **Rendering**: a page tab draws its widget edge to edge in the tab area, no card,
  no title bar, no grid; the widget gets the area's full width and height and may
  scroll vertically. Header, tab bar and filter bar stay above it.
- **Editing**: in the workspace, editors get a small floating toolbar on a page
  tab — *Change widget*, *Edit in Widget Studio*, *Configure* — the same actions a
  card's title bar offers, under the same `canEditLayout` rule. An empty page tab
  shows "Pick a widget for this page" with the library.
- **Making one**: **Add tab** offers *Canvas* or *Page*; a canvas tab with one
  widget can be switched to a page and back.
- `widgets_json` still mirrors tab one, whatever its layout, so a pre-apps reader
  of an app that opens on a page sees one widget, as it would on a canvas.

### 2.2 Page widgets in Widget Studio

Same studio, same widget table, one more shape:

- **Kind**: a widget is a *card* (today) or a *page*, stored on the widget row
  (`layout_kind`), chosen in the studio or inferred from the brief ("a landing
  page", "a hub"). A page widget can still be placed on a canvas (it's just a
  widget); the library shows the kind so people know what they're picking.
- **Contract**: a "Pages" section in `agent_instructions.md`: the page owns its
  background and typography; design for the viewport width (stack below ~900px);
  scroll vertically rather than shrink; use `props.app` (below) for navigation and
  the assistant; icons as inline SVG; display fonts from the bundled list only.
  The card rules ("solid white background", "fill the grid tile") stop applying
  to pages.
- **Lint**: contrast checks resolve inline `style` backgrounds and gradients, not
  only `bg-*` classes, so a page on a dark or warm background isn't flagged for
  light text; pages are checked against their own backgrounds.
- **Preview**: page widgets preview full width at a real viewport height, with a
  width switch (laptop / wide / narrow), inside a mock of the app's header and tab
  bar so the result is seen in place. The existing screenshot review applies, and
  matters more here: it is how a page's legibility and balance get checked.
- **Vibe inputs**: Widget Studio's attachments carry a reference image (a brand
  guide, a screenshot like the Kairos one) to the model through `native_files`.
- **Data**: unchanged. A page may query (live counts on persona cards) through the
  normal data sources, OBO, as any widget does.

### 2.3 The app API for widget code (`props.app`)

The one new capability, available to every widget, used mostly by pages:

```ts
props.app = {
  tabs: { id: string; name: string; layout: 'canvas' | 'page' }[];  // in order
  activeTabId: string;
  goToTab(idOrName: string): void;              // within this app only
  openAssistant(opts?: { agentId?: string; prompt?: string }): void;
  theme: { primary: string; dark: string };     // the view's colours (slice 4 adds the tab's)
}
```

Rules, each a constraint the runtime enforces rather than the contract asks for:

- **No sending on the user's behalf.** `openAssistant` opens the panel, selects the
  agent if the user can open it (otherwise keeps the agent it had, as a pin to an
  agent they can't open does), and
  *prefills* the prompt. The user presses Send. A widget that could send would run
  OBO tools as the user without their choosing to.
- **Navigation stays in the app.** `goToTab` moves between this app's tabs and
  updates the address as a tab click does; there is no URL navigation in the API,
  and the existing lint rules on addresses still apply.
- **No new data reach.** Nothing in `props.app` reads data or settings beyond the
  app's own tab names and colours.
- On a page **inside Command Center**, `openAssistant` opens the workspace's
  panel; on its own, the app's drawer. An app whose agent is **No agent**
  (`assistant: 'off'`) has no assistant in either shell, so the call does
  nothing and returns.

### 2.4 App and tab style

What the brief asks for on canvas tabs: background and theme colours, per tab,
without setting them ten times on a ten-tab app.

- **One look per app.** The app's `theme` (ADR-001 §4.3f) grows to
  `{ primary, dark, background, font, cards }` and applies to every tab. Tabs
  carry no `theme` (a per-tab override was built and then dropped as redundant;
  a stored one is ignored on read). Composing views takes the first source's
  look, as it does filters.
- `font`: one of the bundled families (§2.5), or none for Command Center's. The
  canvas, its cards and the widgets in them inherit it.
- `cards`: `{ radius: none|sm|md|lg|xl, depth: flat|border|shadow, header:
  bar|minimal|none }`. `minimal` drops the title bar's tint and capitals;
  `none` drops the title, and the drag handle and the card's controls float
  over its top-right corner, shown on hover or focus.
- `background`: `{kind: 'colour', colour}`, `{kind: 'gradient', from, to,
  direction: to-b|to-r|to-br|to-tr}`, or `{kind: 'image', url, fit: cover|tile}`
  (logo rules for `url`: https or a `data:` image up to 256 KB). It paints the canvas *behind* the
  cards, which stay white — so the widget contract still holds and no remapping
  of widget classes is needed. That is why this plan drops ADR-002-v0's neutral
  remapping and dark mode: a dark canvas with white cards is readable as it is.
- `primary` / `dark`: as today, contrast-checked against white text.
- Page tabs ignore `background` and `cards` (the page draws its own) but still
  pass the colours and font to the widget through `props.app.theme`, so a page
  can match the tabs around it.
- Edited in **View settings** under **Look**, beside a preview, and by
  describing it: a "Describe
  the look" box asks the widget helper model for a theme and shows the result
  before it is applied (validated by the same rules). `POST /api/apps/look`
  saves nothing and runs no tool: inference is signed by the service principal,
  as Widget Studio's is, and the description and the current look are all it
  sends.

### 2.5 Fonts

Bundle 4–6 OFL families (`@fontsource`, self-hosted, so CSP is unchanged) —
e.g. Inter, Manrope, Space Grotesk, Fraunces, IBM Plex Sans, JetBrains Mono —
loaded only when used. Pages name them in inline `fontFamily`; the contract
lists them; lint flags any other family.

---

## 3. Security model (unchanged)

Everything that was true for views is true here (ADR-001 §2.3, Q7):

- A page tab is a tab: who can add, swap or remove its widget is `canEditLayout`;
  per-tab style is `canEditApp`; global apps need what global views always needed.
- A page widget is a widget: authored, linted, certified and promoted as widgets
  are; placed only if the library shows it to the user (`_visible`); the same CSP
  and CDN allowlist; data through OBO.
- `props.app` adds navigation and an assistant prefill, nothing that reads data or
  acts as the user.

---

## 4. Slices

| # | Slice | Ships | Done when |
| --- | --- | --- | --- |
| 1 | **Page tabs** | `layout` on tabs + validator; edge-to-edge rendering in both shells; editor toolbar; Add tab → Page; switch canvas ↔ page | An app mixing pages and canvases in any order (page, canvas, page) renders each correctly inside Command Center and on its own, survives reordering, and promotion and versions carry `layout` |
| 2 | **`props.app`** | Tabs, `goToTab`, `openAssistant` (prefill only), theme; contract entry | A widget switches tabs and opens the assistant with an agent and a prefilled question, in both shells |
| 3 | **Page widgets in Widget Studio** | Kind on the widget row; Pages contract; inline-background-aware lint; full-width preview with app chrome and width switch; reference images; the bundled fonts from slice 4 (built before this one) | The Kairos screenshot, attached with "build this hub for our five Genie spaces", yields a page that passes review and navigates to the persona tabs |
| 4 | **App and tab style** | `theme` gains background (colour / gradient / image), font, cards; the same `theme` on a tab overrides key by key; bundled fonts; editors in View settings; "Describe the look" | A three-tab app has one look set once, with one tab overriding only its background |

Each slice is usable alone; 1 + 2 already let a hand-written or regenerated
widget act as a hub page.

---

## 5. Verify before building

1. **Page height.** A page tab's area is the viewport minus header, tabs and
   filters; check widgets that use `h-full` + inner scroll behave, and that
   fullscreen (still available) doesn't fight the page layout.
2. **Lint on inline styles.** Resolving `style={{ background… }}` statically is
   heuristic; measure false positives on existing widgets before tightening.
3. **Prefill path.** `useAgentChat` has no "prefill" today (only send). Add one
   that the panel shows in its composer, and make sure a pin applied on arrival
   doesn't overwrite an agent `openAssistant` chose in the same moment.
4. **Thumbnail capture** (`ThumbnailCapture`) of page widgets: card-sized
   thumbnails of a full-width page may need their own aspect.
5. **Promotion** copies `layout` and `tab.style` with the spec; the page's widget
   must exist in the target (preflight already reports missing widgets).

---

## 6. Alternatives considered

- **Design tokens for the whole canvas** (this ADR's first draft): a style spec
  with remapped neutral classes and dark mode. Rejected: it themes cards, it
  can't produce a page like the Kairos hub, and remapping every widget's classes
  is the riskiest part of it. Per-tab backgrounds behind white cards cover what
  canvas tabs need.
- **A separate "page" artifact** (HTML pages next to widgets). Rejected: it would
  duplicate the widget runtime, studio, governance and promotion for something a
  widget already is.
- **Model-written CSS or shell code.** Rejected as before: it can restyle or fake
  controls in a shared app and nothing validates it.
- **A separate App Studio.** Deferred: with page tabs and per-tab style, the
  design work happens in Widget Studio (pages) and View settings (tabs). Revisit
  if assembling apps from a brief becomes the bottleneck.

---

## 7. Open questions

| # | Question | Lean |
| --- | --- | --- |
| Q1 | Should a page tab be able to hide the app's header and tab bar (immersive), relying on the page's own navigation? | Not in v1: a page that forgets `goToTab` would strand people |
| Q2 | Can `openAssistant` ever send, e.g. behind a confirmation the runtime shows? | No; prefill only |
| Q3 | Should "Describe the look" (per-tab style) use the widget helper model or the authoring model? | Helper: it's a small structured answer |
| Q4 | Which fonts to bundle? | The six above |
| Q5 | Is a page widget allowed on a canvas tab? | Yes; it's a widget, shown with its kind |

---

## Change log

| Date | Change |
| --- | --- |
| 2026-10-05 | Proposed as an App Studio + design-token plan. |
| 2026-10-05 | Redirected: page tabs (a tab is one full-screen widget), page widgets in Widget Studio, `props.app`, per-tab backgrounds and colours. Tokens, dark remapping and App Studio dropped or deferred. |
| 2026-10-05 | Slice 1 built: `layout` on each tab, page rendering in both shells, the page toolbar, Canvas/Page on Add tab and the switch on the tab being shown. Slice 4 is built before slice 3, since page widgets use its fonts. |
| 2026-10-05 | Slice 2 built: `props.app` on every widget in both shells; `openAssistant` prefills only and keeps the current agent when the asked-for one can't be opened. |
| 2026-10-06 | Slice 3 built: `widgets.layout_kind`, the Card/Page switch (a first request asking for a landing page or hub starts as a page), and `page_instructions.md` appended for pages only, rather than as a section of `agent_instructions.md` that every card would pay for. The preview is a mock header and tabs at laptop / wide / narrow width, scaled to fit, with a stand-in `props.app`; Tailwind breakpoints still follow the browser window, not the frame. Lint judges light text against the nearest enclosing background, and adds `missing-class` and `unknown-font`, because widget code is never scanned by Tailwind and the stylesheet lacked most page-sized classes until a safelist added them. A page's review gets 240s, not 120s. Done-when run against the real model: the Kairos image with "Build this hub for our five Genie spaces" built a page, the review finished with real fixes, and all five persona cards opened their tabs in a view. |
| 2026-10-06 | Slice 4 built: background, font and cards on the app and tab `theme`, six bundled fonts, **Look** / **This tab's look** in View settings, and `POST /api/apps/look` behind **Suggest**. `props.app.theme.font` is the CSS font stack. |
| 2026-10-06 | After review: tab looks dropped (one look per app; compose takes the first source's), cards gain `header: none`, and **Settings → Agent** gains **No agent**, which sets `assistant: 'off'` and replaces the **Offer the assistant** checkbox. It now hides the assistant inside Command Center too, while that view is shown. **Suggest** deepens a too-light accent instead of dropping it. |
| 2026-10-06 | UX review: View settings split into Opening / Look / Filters / Assistant, branding shown only for **On its own**; plainer words (**Cards on a grid** / **Full page**, **Preview**, **Whichever agent is open**); the header's **Add tab** names both tabs; keyboard tabs; in-app confirmations; filter choices remembered per person in `localStorage`. A built-in **Tab links** widget and a missing-tab warning (from `goToTab('…')` literals) were built and then rolled back to be redesigned. |
