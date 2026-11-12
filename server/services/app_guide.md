<!--
  Knowledge base for the `app_help` tool (services/app_help.py) — this is what
  the chat agent reads when a user asks how the Command Center app itself works.

  Conventions:
    * One topic per `##` section. The section titles are advertised verbatim in
      the tool description, so name them the way a user would ask.
    * Keep every section well under 6,000 characters. A lookup returns at most
      6,000 in all, so a longer section fills the answer by itself, crowds out
      the section that actually answers the question, and is cut off partway.
      Split a growing section under a new heading instead.
    * Keep headings short. The tool description lists all of them within its
      1,024-character limit, and a title past that point is never advertised.
    * Keep it factual and user-facing: what the button is called, what happens
      when you click it, who is allowed to. No implementation detail — the model
      cannot see the code and must not speculate about it.
    * This is a SEPARATE audience from src/pages/guide/sections/*.tsx (humans) and
      RELEASE_NOTES.md (what changed). When you change app behavior, update the
      user guide and this file together, or the agent will confidently describe
      a version of the app that no longer exists.
-->

## What the Command Center is

A configurable dashboard application. Users assemble **widgets** onto a grid to
build **views**, take actions from those widgets, and share layouts with
colleagues. It runs as a Databricks App, so every user is signed in with their
own Databricks identity and sees only the data and assets that identity can
reach.

The left sidebar holds views (**My views**, **Shared with me**, and a collapsed
**Archived** group), the Widget Library, Widget Studio, Agent Studio, and —
under Resources — Getting Started, the User Guide, Release Notes, and, for
Administrators, the Admin Panel. The assistant (this chat) is the panel on the
right; collapsed, it is the round button at the bottom right of the screen.

Everything people build — views, widgets and agents — works the same way. Each
has a **draft** that the people who can manage it edit, and **published
versions** that everyone it is shared with sees. Each has its own access list,
like a Databricks dashboard: see *Sharing and permissions* and *Drafts and
publishing*.

Someone with no views of their own sees a welcome panel over the canvas the
first time they open the app, with the assistant opened beside it. It offers
five things: ask the assistant (starter questions are typed into the message box,
never sent), browse views shared with them, find widgets in the Widget Library,
build a widget in Widget Studio, and build an agent in Agent Studio. Anyone can
use both studios. Hovering a card outlines where that feature lives. It doesn't
open for someone arriving by a link to a view. **Resources → Getting Started**
shows it again; **Got it**, the X or Esc close it.

## Views and layouts

A view is a named set of widgets, laid out on one or more tabs. Whoever creates
a view owns it and can manage it; nobody else sees it until it is shared with
them and published (see *Sharing and permissions* and *Drafts and publishing*).

- The sidebar groups views into **My views** (ones you own), **Shared with me**
  (ones other people shared with you) and a collapsed **Archived** group (archived
  views you manage, each with **Restore** and **Delete permanently**). Each view
  shows an icon for who it is shared with: a lock (only the people on its access
  list, often just you), people (shared with particular people or groups) or a
  globe (everyone in this app). A small dot beside it, for people who can manage
  it, means it has changes nobody else sees yet: grey if it has never been
  published, amber if it has unpublished changes.
- Administrators can manage every view, but their sidebar lists only the views
  they own or that are shared with them; **Admin Panel → Content** lists all of
  them, and an Administrator can open any view by its link.
- **New View** in the sidebar creates a blank one: a draft that only you can see
  until you share and publish it. The pencil icon (shown on hover) renames it:
  type the name and press Enter, or Esc to cancel. Drag a view by the grip beside
  its name to reorder My views.
- **Closing one of your own views** with the **×** on hover asks first, then
  deletes it if only you can open it, or archives it if it is shared with anyone
  else (see *Archiving*, below).
- A view under **Shared with me** offers two buttons on hover: **Copy**, which
  makes a copy of your own in My views, and **Close**, which only takes it off
  your sidebar. It stays shared with you, and opening its link brings it back.
- **The view header** shows the view's name and, for people who can manage it,
  a state chip beside the name: **Not published yet**, **Published** or
  **Unpublished changes**; hovering the chip explains what it means. On the
  right, in this order: the **Draft** / **Published** switch (only when there
  are unpublished changes, or while you are looking at Published, so you can get
  back), the **⋯** menu (*More view options*), **Share**, and **Publish**, the
  last and only filled button. **Publish** is there only when there is
  something to publish; on a view that is already up to date it is hidden, not
  greyed out. People who can only use the view see just the ⋯ menu (when it has
  anything for them) and **Share**.
- **The ⋯ menu** holds everything used now and then, in three groups:
  - **Layout** (called **This tab** when the view has several tabs): **Cards on
    a grid** or **Full page**, with a check against the current one, and **Add
    a tab…** on a one-tab view. Shown to whoever may change the view's tabs.
  - **View**: **Preview as a viewer** (on a view set to open on its own),
    **View settings…**, and **Lock layout** / **Unlock layout**.
  - **Versions**, for managers: **Version history…** once the view has been
    published, and **Discard draft…** when it has unpublished changes (it asks
    to confirm first).
- **Lock layout** (in the ⋯ menu, on a view) stops widgets being moved,
  resized or removed by accident. Once locked the menu item reads **Unlock
  layout**. A locked widget card loses its grip, version box and remove
  button, and the Widget Library says "View is Locked" instead of adding
  widgets. **Lock layout**, **View settings…**, the state chip and **Publish**
  appear only for people who can manage the view; for someone who can only use
  it, the view is read-only.
- **Share** (top right, on a view) is there for everyone who can open the view.
  It shows who the view is shared with; people who can manage the view also give
  a person, a group or everyone in this app **Can use** or **Can manage** there
  (see *Sharing something and getting access*), and for anyone else the list is
  read-only. **Copy link** in that dialog copies a link to the current view, set
  the way it is now (see *View links*). The chain-link icon on an
  individual widget copies a link that opens that widget full-screen, with the
  view's filters and that widget's own settings. The address
  in the browser is the same link, so copying it from there works too.
- **Every change a manager makes** — moving a widget, renaming a tab, View
  settings, the agent pin — goes into the view's draft and reaches other people
  only when the view is published. **Discard draft…** is offered only when the
  view has unpublished changes; a view that has never been published is deleted
  instead. See *Drafts and publishing*.
- A widget on a view that has never been published shows a **Not published
  yet** card to people using the view, in place of the widget.
- **Archiving** takes a view you manage out of everyone's sidebar without
  deleting anything; it then appears under **Archived**, where **Restore** brings
  it back exactly as it was and **Delete permanently** removes every version. A
  view shared with anyone besides its owner must be archived before it can be
  deleted; a private view can be deleted straight away.
- **View settings…** (in the ⋯ menu) is covered in *View
  settings*: how the view opens, its look, its filters and its agent.
- Tabs and full pages are covered in *Tabs and pages*, and how a view's link
  works and who it opens for in *View links*.

## Tabs and pages

- **Add a tab…** (in the ⋯ menu) gives a one-tab view a second tab, asking what to
  call the new tab and the one already there (left empty, that one becomes
  "Overview"); a tab bar then appears under the header with a **+** for more (up
  to 50). Double-click a tab, or select it and press F2, to rename it; drag it to
  reorder, and use its **×** to delete it (asking first in a dialog if it holds
  widgets; the last tab can't be deleted). From the keyboard, Tab reaches the
  tab bar, the arrow keys and Home/End move along it, and Enter or Space opens
  a tab. Whoever may move widgets
  in a view may change its tabs: someone who can manage it, in its draft, and
  not while it is locked. The published version is read-only for everyone. A
  widget added from the Widget Library goes on the tab being shown.
- A tab is **Cards on a grid** (several widgets, each in a card; the default)
  or a **Full page** (one widget filling the whole tab, with no card around it,
  for a landing page or hub). **Add a tab…** and the **+** ask which for a new
  tab. To switch the tab being shown, pick **Cards on a grid** or **Full page**
  in the ⋯ menu; the choice is there for whoever may change the view's tabs,
  including on a view with only one tab (the usual way to make a whole view one
  full page). **Full page** can't be picked on a grid holding more than one
  widget, and hovering it says why: remove all but one first. Any tab may be a
  page, in any order.
- On a page, drag a widget from the Widget Library onto it (dropping another
  replaces it, after asking). The toolbar in its top-right corner — shown only
  to whoever may change the tab, inside Command Center — offers **Change
  widget**, **Edit in Widget Studio**, the gear for the widget's settings (where
  its links are set), and remove (after asking). The gear is grayed out for a
  widget built without settings. To turn the page back into cards on a grid,
  pick **Cards on a grid** in the ⋯ menu.
  A view opened on its own shows the page without the toolbar. Any widget can
  go on a page, but one built as a page in Widget Studio (marked **PAGE** in
  the Widget Library) is the one made to fill it.

## View links

- The address names the tab being shown, so a link opens on that tab and Back
  steps between tabs. A link to the first tab doesn't name it, so it opens
  whichever tab is first.
- **A link keeps what the view is set to.** A moment after each change, the
  address picks up the view's filters, the values widgets pass to each other,
  and the settings a widget keeps in the link (typically a sort, a search, a
  date range, a selected segment or tab, a page size). So a reload, Back, and a
  copied or pasted link open the view set the same way. They sit before the
  `#`, like `?v.region=West&w.3f2a91c0.sort=revenue#/app/sales`. A setting
  still at its default is left out, and if a view's settings would make the link
  longer than about 1,500 characters, the largest are left out of it. Switching
  tabs keeps them; opening a different view starts that view without them.
- **A link that carries settings opens with exactly those**, not with the
  filter choices that person last left the view on. A filter option the view no
  longer offers falls back to the filter's default. Settings in a link never
  change who may see what: the view still opens only for people it is shared
  with, and its data still comes back as each person may see it.
- **Which widget settings go in the link is up to the widget.** Widgets that
  Widget Studio builds keep their filters, search, sort, date range, selected
  segment or tab and page size there by default, and the agent says which; ask
  it to keep any out and it does. Hover states, open menus and other passing
  details are never saved. In the studio's preview these settings are only
  kept in memory, since the studio has no view link.
- Links use names, not codes. A published view's link is its name, like
  `#/app/supply-hub/inventory`; a second view with the same name gets
  `supply-hub-2`. Renaming a view gives it a new link when it is next
  published, and links to the old name keep opening it. A view that has never
  been published is linked by its name followed by its id, like
  `#/app/q3-review-3f2a…`. A tab goes by its name unless two tabs would share
  one; after a tab is renamed, an old link to it opens the first tab. Links with
  ids from before this, and links that still carry `?env=` from the old
  Dev/Test/Prod switcher, keep working.
- **A link opens only for people the view is shared with.** Anyone else is told
  the view isn't there, exactly as if it didn't exist, so a link never confirms
  that something exists. An archived view's link stops opening too, until it is
  restored. Inside the Command Center, people who can manage the view see its
  draft and people who can use it see the latest published version. A view set
  to open on its own from its link always shows the published version there,
  read-only, even to its managers, who use **Edit** to go back to the draft.
  Everyone who could open a view before the upgrade to sharing still can. Links
  still need the usual
  sign-in, and links copied before the link format changed
  (`?shared_view=…`, `#/view/…`) keep working; new ones look like `#/app/…`.

## View settings

**View settings…** (in the view's ⋯ menu) is offered to people who can manage
the view; people who can only use it don't see it. It has four sections listed down its
left side: **Opening**, **Look**, **Filters** and **Assistant**. A red dot marks
a section with something to fix, and the footer names it, because **Save** stays
off until it is fixed. Nothing is stored until **Save**, and **Save** writes the
view's draft: other people see the new settings once the view is published.

- **Opening** decides how the view's link opens. **Inside Command Center** is the default and how every view has
  always opened. **On its own** opens just that view: no sidebar, no Widget
  Library, no studios, under the title, logo and browser-tab icon set there; those
  three fields only appear once **On its own** is chosen. The assistant appears
  too, unless the view's agent is **No agent**. While the view is edited inside
  Command Center its header shows the same title and logo, so editing looks like
  Preview; the sidebar keeps the view's name.
  **Header** there can be **No header: the page has its own**, for a view whose
  page draws its own title bar. On its own the view then starts straight with
  its tabs (or its page), the logo field goes away, and the title is used only on
  the browser tab. **Share**, **Edit** (or **Back to editing** in a preview)
  and the environment label move to a small bar at the bottom left, shown only
  to people who get at least one of them. Inside Command Center the header goes
  too, and the view's controls (the state chip, **Draft** / **Published**, the
  ⋯ menu, **Share** and **Publish**) sit in the same bar at the bottom left.
- Each field in **Settings** has a **?** beside it; hovering it (or tabbing to
  it) explains what the field does.
- **Assistant** in **Settings** has the **Agent** picker: the agent the view
  opens with, inside Command Center and on its own; it is the same pin as the
  pin button in the assistant panel (below). **Whichever agent is open** pins
  nothing, so people keep the agent they had. The launcher button names
  whichever agent is selected.
  **No agent** removes the assistant from the view everywhere: on its own there
  is no assistant, and inside Command Center the launcher and panel disappear
  while that view is on screen (they come back on other views, studios and
  pages). Picking any agent again brings it back.
- **Version history.** Moving, resizing and changing settings edit the view's
  draft in place, so they add no versions. Each **Publish** adds one version,
  and **Version history…** in the ⋯ menu (for managers) lists the published
  versions; **Revert** copies one back into the draft, and publishing it makes
  it live again.
- Two more choices in **Settings** apply wherever the view opens. **Tabs**,
  under **Look**: **Across the top** (the default) or **Down the side**; a view
  with one tab shows no tabs either way. **Filters**: dropdowns under the header, each with a
  label, a variable name, its options (one per line) and the option it starts
  on. Anyone who can see the view can use them. A choice sets that dashboard
  variable for every widget on every tab, exactly as a widget passing a value to
  others does, so only widgets written to follow that variable change. **All**
  clears it. Each person comes back to the choices they last made on that view,
  remembered in their browser (a different browser or computer starts from the
  defaults); a remembered option the filter no longer offers falls back to its
  default. A link that carries filter choices opens on those instead, and the
  address follows each choice, so a copied link shares them (see *View links*).
  A view built from several views keeps their filters.
- A view opened on its own is read-only for everyone, including its owner, and
  always shows the latest published version, never the draft; its tabs can be
  switched but not changed. Publish the view before sending its link to people
  who should see it on its own.
  **Share** there is for everyone who can open the view: it shows who the view is
  shared with and copies its link, and only managers can change the list.
  **Edit** goes to anyone who can manage the view.
  **Edit** reopens it inside Command Center at an address starting
  `#/workspace/…`, which keeps it there on reload; **Preview as a viewer** in the
  ⋯ menu goes back to seeing it on its own. A view opened with **Preview** is labelled
  **Preview** and has **Back to editing** (or **Back to Command Center** for
  someone who can't change it) in place of **Edit**, returning to the same tab;
  the label and button are only there for whoever pressed **Preview**, not for
  people opening the link. The link opens only for people the view is shared
  with.
- **Look** (the colours, font, background, header and cards) is covered in
  *View look*.

## View look

- **Look** in **Settings** styles the view, the same on every tab. **Accent
  color** and **Dark color** replace Command Center's blue and navy, widgets included, and each
  must be dark enough for white text. **Font** is one of Inter, Manrope, Space
  Grotesk, Fraunces, IBM Plex Sans or JetBrains Mono (no others: fonts are
  bundled with the app). **Background** is Command Center's light gray, a
  color, a two-color gradient, or an image (an https:// address, or an upload
  up to 256 KB) that fills or tiles it. The background covers everything under
  the header as one surface: the tab bar and filter bar sit on it rather than
  on white bands of their own, and so do the cards, a page tab's widget and the
  assistant's messages and message box. Text drawn straight on a dark
  background (tab names, filter labels, "This tab is empty", the assistant's
  small print) turns light by itself. On a dark background the assistant's
  replies, its pinned-agent note and the message box turn to translucent glass
  with light text instead of white boxes (a chart in a reply keeps its white
  card); on a light background or an image they stay white. **Header** (White or The dark color) colors
  the bar along the top, on its own and inside Command Center alike, and the
  assistant's header beside it, which is always the same height so the two make
  one line. With Command Center's light gray **Background**, the tab bar and
  filter bar take the dark color too, so the top of the view is one dark block;
  with a background of your own they sit on it instead. On a view set to **No
  header** (Opening) there is no bar along the top, so it colors the assistant's
  header and those bars, and the Look section says so under the field. **Cards** sets their
  corners, edges (flat, outlined, shadowed), title (in a gray bar, in an
  accent-color or dark-color bar with a white title, plain, or **No title**,
  which leaves the title off and shows the card's buttons only on hover) and
  **Spacing** between them (compact, standard, roomy); a card's body stays
  white so widgets stay readable. Inside Command Center the look covers
  everything but the sidebar: the header, the view's tabs, filter bar,
  background and the assistant panel; opened on its own, the whole page uses it. A view with no look, and every page that isn't a view (studios, User
  Guide, Admin Panel), keeps Command Center's colors. A page tab has no cards,
  and its widget usually paints over the background. A preview beside the
  choices shows the result.
- The assistant's header holds just the agent picker, the pin and the history,
  new-conversation and collapse buttons. How many widgets it can see is in the
  small print under the message box, and notes about a pinned agent show at the
  top of the conversation.
- **Suggest**, beside **Describe the look**, turns a
  description ("dark navy, like a control room, rounded cards") into those
  choices. It only fills the fields: nothing is saved until **Save**, **Undo**
  puts back what was there, and anything the model chose that the app can't
  draw is named and left out.

## Widgets

Widgets are the building blocks of a view — charts, tables, text, forms, embedded
pages, or buttons that perform an action.

- Add one from the Widget Library: **click its card** (there is no "+" button)
  to add it, or drag the card onto the grid and drop it where wanted. The
  library stays open after a click, so several can be added in a row. The tab
  being shown receives it. A locked view refuses it.
- Move a widget by holding its header, the bar with the grip and the title, and
  dragging; surrounding widgets flow out of the way. Resize by hovering the
  bottom-right corner until the handle shows. Layouts save as you go.
- The widget header carries per-widget controls, depending on the widget:
  **Widget Version** (a picker; a blue dot means "Update available"), **Open in
  New Tab** (only for a widget with its own web address), **Copy direct link to
  this widget**, **Help** (only for a widget with help text), a cog for **Widget
  settings** (only for a widget built to accept runtime inputs), **Fullscreen**
  (Esc or **Exit Fullscreen** returns) and **Remove Widget**. The X takes the
  widget off the tab at once, with no confirmation, and its settings go with
  it; it stays in the Widget Library. In full screen the X only leaves full
  screen. A direct link doesn't work for a widget on a full-page tab, and the
  person opening it needs access to the view. On a view someone can't change (locked, published, or shared with them to use) a card
  shows only its title and full-screen, plus copy link; on its own, not even
  that. Long titles are cut short with "…"; hover for the whole name.
- Widgets with more than one published version have a version picker in the
  header, so whoever manages a view can pin an older version on it. Saving a
  widget's settings keeps that pin.
- **Who sees a widget on a view.** Anyone who can use a published view sees the
  widgets on it — each at its latest published version, or the version the card
  pins — without needing the widget shared with them separately. A widget placed
  on a view but never published shows "Not published yet" to them instead. In a
  view's draft, its managers see their own unpublished widget changes. Data in a
  widget is still read as the person looking at it, so Unity Catalog decides what
  each person sees.

**What a widget is allowed to contain.** Saving a widget — in Widget Studio or by
importing one — is refused if its code uses `eval`, `new Function`,
`document.write`, `innerHTML` or `dangerouslySetInnerHTML`, or if it references
any address other than this app's own `/api/...` paths and the approved CDNs
(cdn.jsdelivr.net, code.highcharts.com, unpkg.com, cdnjs.cloudflare.com), plus
any Databricks App an Administrator has listed under Admin Panel → Settings →
**Databricks Apps widgets may embed or call**. That list starts empty. Each line
is one app's host, or every app in a workspace written as
`*-<workspace-id>.<region>.databricksapps.com` (an app's host is
`<app-name>-<workspace-id>.<region>.databricksapps.com`, so `*.<workspace-id>…`
matches nothing and is refused with the right form). No other wildcard is
accepted, because every Databricks customer's apps share `databricksapps.com`.
A widget may show any listed app in an iframe, but may fetch only from an app
listed by its own host. Scripts still load only from the CDNs. The browser
enforces the same rule independently, so a widget that got round the save check
still could not load a script or send data off-list. Widget code is generated
from a prompt, and these two rules are what keep "generated" from meaning "can
reach anywhere".

A widget that **changes** data (INSERT, UPDATE, DELETE, MERGE and so on) does it
through its action controls and should be marked **Executable**; Widget Studio's
Problems bar flags a write that skips them, and a widget whose legacy SQL data
source changes data can't be saved unless it is Executable. The action controls
are what record every change in **Action Logs**, with who made it. There
is no confirmation prompt: the action runs as soon as it is recorded, and does not
run at all if it cannot be recorded.

**Widgets that steer the view.** A widget can list its view's tabs and open one,
and can open the assistant with a chosen agent and a question already typed. It
can't send that question: the user reads it and presses Send, because sending is
what runs the assistant's tools as them. If the agent it asks for is one the user
can't open, the assistant keeps the agent it had. In a view whose agent is **No
agent**, the button does nothing. Ask Widget Studio for this in plain words —
"tiles that go to each tab", "an Ask about this button".

**Links.** A widget whose buttons or tiles go somewhere specific (a hub page's
"Sales" and "Operations" tiles, a "Supplier portal" button) names those links,
and whoever places it decides where each goes: the widget's gear lists each link
with a choice of the view's tabs, **Not set**, or **Web address…** (http or https
only). The choice belongs to that card on that view, so the same widget can go to
different tabs on different views. A tab link survives renaming the tab; if the
tab is deleted the tile goes nowhere and the gear says "The tab this went to was
deleted". A web address opens in a new browser tab, never in place of Command
Center. Until a link is set its tile looks muted and does nothing. Widget Studio
adds the links itself when it builds such a widget; an author can also add one by
hand as a settings field of type **Link**. Duplicating a view or building an app
from views keeps each link on the copied tab. A widget can't open another view,
and its code still can't contain an address: an address is only ever a card's
setting.

## Widget Library

Opens from the **Widget Library** button in the sidebar, or by pressing `w`.
It lists the published widgets shared with the user, plus the drafts of widgets
they can manage, and is searchable. Certified widgets are flagged as such, and
widgets built as pages are marked **PAGE**. A widget that has never been shared
with someone doesn't appear for them at all. Widgets on a view shared with you
still show on that view, at their published version, but aren't offered in the
library unless the widget itself is shared with you.

A panel rises over the bottom three quarters of the screen; Esc, the X or a click
outside closes it. It lists the widgets in the domain selected, most used first.

- **Search widgets…** matches names and descriptions across every group,
  ignoring the group picked on the left. **Categories** and **Domains** group the
  list down the left side, each with a count. Domains are only labels for
  finding things; they don't decide who can use a widget.
- **All**, **Mine** and **Shared with me**, beside the domain filter, narrow the
  list to every widget, widgets you built, or widgets other people built and
  shared with you.
- **Grid View** shows cards with previews; **List View** a table of name,
  creator, status, popularity and size. A row's **Status** shows the same
  **CERTIFIED**, **PAGE** and draft badges as a card, and hovering a row shows
  the same icons as hovering a card.
- **Certified** shows certified widgets plus the person's own, remembered in
  that browser. **Top creators** lists who builds the widgets people use;
  clicking a name shows only theirs.
- A card shows a **CERTIFIED** badge and a **PAGE** badge where they apply, how
  many times it has been added, its creator ("by you"), domain and default size,
  plus an icon for who it is shared with. On a widget you can manage, a chip
  reads **NOT PUBLISHED YET** or **UNPUBLISHED CHANGES** when other people don't
  yet see what you have saved. On a widget with no creator recorded, someone who
  can manage it sees **Did you build this? Claim it**.
- Hover icons: **Clone widget** opens a copy in Widget Studio (a new widget of
  your own), the share icon opens **Share** (read-only unless you can manage
  the widget), and **Edit in Widget Studio** and **Delete widget** appear for
  people who can manage the widget. Delete removes the widget from the library
  for everyone, after one confirmation, and can't be undone; to take a widget off
  just one view, use the X on its card instead.

## Widget Studio

Where widgets are created and edited, at **Widget Studio** in the sidebar.
Anyone can build a widget; editing an existing one needs **Can manage** on it.
No React expertise is required for simple and moderately complex widgets —
they are generated from a description.

Layout: only the agent settings sit above the chat. The right-hand header holds
the tabs, then **History**, **Reload**, a **⋯** menu with *Import from file*,
*Export to file* and *Reset studio*, then **Save draft** and the X. For a saved
widget, the bar under the tabs holds **Share**, plus the draft controls and
**Certify** if you can manage it.

- **Save draft and Publish** — **Save draft** writes your draft in place and
  leaves you in the studio to carry on working; it adds no version, and only
  people who can manage the widget see the draft. Once a widget is saved, a bar
  under the tabs holds its state chip (**Not published yet**, **Published** or
  **Unpublished changes**), the **Draft** / **Published** switch (only when there
  are unpublished changes, or while on Published; Published is a read-only
  preview of what people see), **Discard draft** (only with unpublished
  changes), **Publish** (hidden when there is nothing to publish), **Certify**
  and **Share**.
  **Publish** runs the safety check again, then turns the draft into the next
  published version, which is what everyone the widget is shared with sees and
  can place. A new widget is shared with nobody but you until you use
  **Share**. **History** lists earlier code from this session and published
  versions, either of which can be restored into the editor. The **X** closes the
  studio. See *Drafts and publishing*.
- **Stop** — while the agent works, the send button becomes a red Stop button
  and Enter does nothing. Stop ends the turn at once: steps that already
  finished stay in the editor (each has a History entry) and nothing else is
  applied. **Stop after this step**, on multi-step builds, lets the current step
  finish first.

A widget can also be exported to a JSON file and imported elsewhere, which is
how widgets move between disconnected deployments.

The rest of the studio is covered in *Widget Studio: configuration and data*
(the Configuration tab, data sources, row limits and parameters), *Widget
Studio: the agent* (asking for a widget, attachments, agent settings) and
*Widget Studio: preview and pages* (the preview, Problems, cards and pages).

## Widget Studio: configuration and data

- **Configuration tab** — name, description, help text, category, domain (a
  label for finding the widget, not a permission),
  default size, whether the widget performs an executable action, and its
  configuration mode (whether end users can pass runtime inputs). The Data
  Source is None, API or Databricks API, and can be tested here with **Test &
  Extract Schema**; the schema and a few sample rows are shown and handed to the
  generating agent. Tests run as you, with your own permissions. An external API
  is called from your browser, exactly as the widget will call it, so a CORS
  block shows up here. **There is no SQL data source**: for tables, the user
  leaves it on None and names the table in the chat, and the agent writes the SQL
  into the widget's code and runs it to check it (see *Widget Studio: the
  agent*). A widget
  saved earlier with a SQL data source keeps it, shown read-only under **Legacy
  SQL data source**, so the widget and its placed copies keep working; to change
  that query the user asks the agent, which moves it into the code, and **Remove
  legacy SQL** then clears the old one (it stays disabled while the code still
  reads it). How many rows a query returns decides how the agent builds, so it
  counts them when unsure. Searching, sorting and paging can
  happen in the browser or in the query, and both work at any row count; the
  deciding factor is how much data the browser would download, about 10 MB
  (rows times columns). Under that, the widget fetches everything once and works
  locally; over it, paging, sorting, searching and totals are pushed into SQL so
  the widget only ever holds one page. A table of unknown size is treated as large.
  A query returns its first 500 rows unless the widget asks for more, and the
  response says when rows were left out; a user who "hit a row limit" usually
  means this. A widget can ask for every row (`all_rows: true` in its request),
  however large the result — the only stop is the admin's **Most rows one widget
  query can return** setting (Admin Panel → Settings, default 1,000,000). A
  widget that asks for a fixed number such as 5,000 or 10,000 instead goes wrong
  quietly once the data grows past it, and Widget Studio flags that number. The
  fix for either is to ask the studio agent to fetch every row, or to page in
  SQL.

**Parameters that differ between places.** Parameter values belong to the card
placed on a view. For a catalog, schema, threshold or other value that differs
between views, or between this app and another deployment, ask the studio for a
**Required** parameter without a default. Dropping the widget opens **Widget
settings** before it is placed; the card's gear changes it later. Moving a view
to another deployment with Data Migration copies its card settings with it, so
open each card's gear there when those values must differ.

## Widget Studio: the agent

- **The agent** — describe the widget in the chat and it writes the TSX. Asking
  for a change edits the existing code in place rather than rewriting the whole
  component. After generating, it also proposes Configuration-tab values,
  including runtime parameter fields and whether they are Allowed or Required.
  A parameter it creates is read from `props.data` in the code as well as added
  to the placed widget's gear. Existing fields are kept rather than redefined,
  and anything filled in by hand during this studio session is left alone. While it works, **Thinking**
  can be expanded to see what it decided — how it read the request, the steps it
  planned, and anything it skipped — and that stays with the answer afterwards.
  On a large or vague request it may ask up to three questions first rather than
  guess; answer them, or press **Build it anyway** to have it choose defaults.
  It can also **look at your data** before writing code: it runs read-only SQL on
  the app's warehouse and can ask Genie, both as you, so it only sees what you
  are allowed to see. Name the table (`main.supply.shipments`) and it checks the
  real column names and values rather than guessing; what it looked up shows
  under **Thinking**. It never writes data, and what it finds shapes the code
  rather than being pasted in as fixed numbers. Each step of a multi-step build
  can do this too, and it runs any SQL it writes once before handing the code
  back. Admins can switch either tool off in Admin Panel → Settings.
- **Attachments and screenshots** — the paperclip attaches spreadsheets,
  documents and images for the agent to read, a screenshot or copied image can
  be pasted straight into the message box, and **Send screenshot to agent**
  under the preview attaches a picture of the widget as it currently looks.
  Neither sends on its own: the file waits on the next message, so "this column
  is too narrow" arrives with the thing it describes.
- **Agent settings** (the sliders icon above the chat) — two options, remembered
  in that browser rather than set for everyone. *Conduct review after change*
  (off by default) has the agent re-read its own code once it has compiled and
  run in the preview, as a QA pass over behaviour, states, layout and
  legibility, and fix what it finds. It is shown a screenshot of the rendered
  widget and what happened when it ran, when the model can read images. It
  then adds a *Worth considering* note — up to three changes that would make the
  widget better at its job, judged as a product owner would rather than against
  the request. Those are only ever suggestions; the review never implements them,
  so it cannot quietly grow a widget. Each one appears as a chip under **Do
  next**: clicking it writes that instruction into the message box, ready to
  edit or send, so acting on a suggestion is one click rather than retyping it.
  It costs an extra turn. *Ask before large builds* (on by default) is the
  clarifying-question behaviour above, and can be switched off by anyone who
  would rather it always guessed.

## Widget Studio: preview and pages

- **TSX Editor / Live Preview** — the code and its live rendering. **Reload**
  re-runs the widget so anything that only happens on first load can be
  repeated without editing code. The studio watches the preview run: each
  request the widget makes (and how many rows came back), anything it logs as an
  error, and errors it throws. If code the agent just wrote fails when it runs —
  a query rejected as invalid, a crash in its data handling — the agent is sent
  what happened and fixes it on its own, up to twice. It does not try to fix
  failures code can't fix: a permission error (403), a server error, or a
  widget's legacy SQL data source itself failing, which it reports so the user
  can ask for a replacement query.
  **Problems**, the bar under the preview and the code, lists two things: rule
  checks on the code (an import widgets can't use, a script from a CDN that
  isn't allowed, a write without the audit trail, text too light to read, a
  class the app's stylesheet doesn't have and so does nothing, a font that
  isn't bundled, and similar) and what happened in the last run. The agent is given both with every
  request. **Fix with agent** asks it to fix everything listed. Rule errors in
  code the agent wrote are fixed automatically, like a failed run; warnings are
  left to you.
- **Card or page** — the switch above the preview. A **Card** sits on a
  tab with other widgets; a **Page** fills a whole tab of a view, brings its
  own background and layout, and is what a landing page or hub should be. A
  new widget whose first request asks for a landing page, hub or full-screen
  page starts as a page, and the studio says so; anything else starts as a
  card, and the switch changes it at any time. The agent is told which it is
  building. A page previews under a stand-in header and three stand-in tabs
  (Home, Overview, Details), at **Laptop**, **Wide** or **Narrow** width,
  scaled to fit the pane. Only the frame changes width: classes like `md:` and
  `lg:` follow the browser window, so a narrow layout is best checked by
  narrowing the window. Its buttons that go to a tab or open the assistant say
  what they would do in a view rather than doing it. Attach a picture of the
  page you want and the agent works from it. Cards on a page that name a part
  of the view (a persona, a team) open the tab of that name when the view has
  one, found by name when clicked, and otherwise ask the assistant; so add the
  tabs, named as the cards are, and the cards start leading to them.

## Domains

A domain is a label — Finance, Supply Chain, Sales are typical — put on views,
widgets and saved agents so people can find them. The Widget Library groups and
filters by domain. **Domains don't control access**: who can see or
change something is decided only by its own access list (see *Sharing and
permissions*). Administrators manage the list of domains under **Admin Panel →
Categories & Domains**.

## Sharing and permissions

Access works like sharing a Databricks dashboard. Every view, widget and agent
has its own access list, and each entry gives one of two levels:

| Level | Can do |
| --- | --- |
| **Can use** | See the published version in the sidebar or the Widget Library, open it, place a published widget on your own views, chat with a published agent |
| **Can manage** | Everything Can use allows, plus see and edit the draft, publish, discard the draft, revert to an older version, change who it is shared with, certify (widgets), and archive, restore or delete it |

An entry names one of three kinds of principal:

- **A person**, by their Databricks username (case doesn't matter).
- **A group**, by its Databricks group name, which must match **exactly,
  capitals included**.
- **Everyone in this app**, which covers every signed-in user.

Key rules:

- **The owner** — whoever created it — gets Can manage automatically and is
  shown with an **Owner** tag in the share dialog. Something must always keep at
  least one person or group with Can manage; only an Administrator can remove the
  last one.
- **The highest level wins.** Someone who gets Can use as a person and Can
  manage through a group can manage it.
- **Administrators** can manage everything in the app and are the only people
  who see the **Admin Panel**. They are listed under **Admin Panel →
  Administrators**. Running locally with `DEV_MODE=true` makes you one.
- **Anyone can build.** Widget Studio and Agent Studio are open to everyone, and
  what you build starts out shared with nobody but you.
- **People who can use something see only its published version.** Something
  that has never been published is invisible to them, even if it is shared with
  them. See *Drafts and publishing*.
- **A view carries its widgets.** Anyone who can use a published view sees the
  published widgets on it without each widget being shared with them. Those
  widgets render on the view, but the Widget Library doesn't offer them.
- **A view doesn't carry its agent.** Someone who can use a view but not its
  pinned agent gets the default assistant on it.
- **Links open only for people something is shared with**; anyone else is told
  it isn't there. Everyone who could open something before sharing was introduced
  still can: the upgrade gave each person the access they already had.
- **Domains have no effect on access.** They are labels for filtering.
- The app keeps **no user directory of its own**. It reads the signed-in user's
  Databricks username and groups. Group membership is remembered for a few
  minutes, so someone just added to a group may need to wait and reload.
- Access to *data* (a catalog, schema, or table) is separate and is granted in
  Databricks itself. A widget or agent always reads data as the person using it.

**How access carried over in the upgrade.** Before sharing, access followed
domain role mappings. The upgrade turned each mapping into entries once: a
Viewer mapping on a domain became Can use, and Editor or Admin became Can
manage, on every widget filed under that domain, every view that used to be
global, and every agent that belonged to that domain. Owners got Can manage, and
people who had added someone's personal view to their sidebar got Can use on
it. Agents that used to be global are shared with Everyone in this app. An Admin
mapping on the global domain (Global, All or App) made an Administrator; a
Viewer or Editor mapping there covers only items filed under that exact name,
which is all it ever did.

## Sharing something and getting access

To share a view, open it and click **Share** in the view header. For a widget,
use **Share** in Widget Studio, or hover the widget in the Widget Library and
click the share icon; for an agent, **Share** in Agent Studio. Anyone who can
use a view, widget or agent can open **Share** to see who has access (and copy
a view's link); changing the list needs Can manage. In the share dialog:

1. Type a person or a group in the box at the top. Suggestions list names the
   app has already seen, with your own groups marked **Your group**. A name it
   hasn't seen is still accepted, with a reminder that it must match the
   Databricks user or group name exactly.
2. Pick **Can use** or **Can manage**, then **Add**.
3. **People with access** lists each entry with its level, "(you)" beside
   yourself and **Owner** beside the owner. Change a level with its picker or
   remove an entry. A line underneath says Administrators can always manage.
4. **General access** is **Only people with access** or **Everyone in this app
   can use**.

Every change saves as soon as it is made; **Done** closes the dialog and **Copy
link** copies the link. If the item has never been published, the dialog says
that people with Can use will see it once you publish.

**Getting access.** Someone who needs something should ask its owner, or anyone
who can manage it, to share it with them or with a group they belong to; an
Administrator can share anything. A link to something not shared with you looks
exactly like a link to nothing, so ask the person who sent it. If an entry
naming your group doesn't seem to work, compare the group name with the
workspace's Groups page, character for character, and allow a few minutes after
being added to a group.

**Administrators** are managed under **Admin Panel → Administrators**, by
Administrators: add a person or group with the same picker, or remove one. The
last Administrator can't be removed, and Everyone in this app can't be made one.
Keep the list small — Administrators can change anything in the app. If no role
mapping made anyone an admin before the upgrade, the upgrade made the group
`users` (essentially everyone) an Administrator so nobody was locked out;
replace it with your admin group.

## The Admin Panel

**Admin Panel** is under Resources at the bottom of the sidebar. It appears only
for Administrators (see *Sharing and permissions*). Its tabs are **Content**,
**Categories & Domains**, **Administrators**, **Settings**, **Data Migration**
and **Action Logs**, and all of them apply to the whole app.

- **Content** lists every view, widget and agent in the app, whoever owns it,
  with its owner, whether it is published or has unpublished changes, and how
  widely it is shared. It is where an Administrator finds something nobody else
  can reach any more — for example after its owner left — and shares it with
  someone who should manage it.
- **Categories & Domains**: *categories* group widgets by function (Monitoring,
  Analytics…) in Widget Studio and the Widget Library; *domains* label widgets,
  views and agents with a business area so people can filter by it. Neither
  decides who gets in. Add a name and click **Add Category** or **Add Domain**.
- **Administrators** lists the people and groups who are Administrators; see
  *Sharing something and getting access*.
- After the upgrade to sharing, a notice at the top of the Admin Panel reports
  the one-time move: role mappings becoming access lists and Administrators, and
  Dev and Test work becoming drafts. **View details** shows who gained or lost
  access and anything it couldn't carry over. The move runs once; if part of it
  failed, the notice stays red and **Retry** in its details runs that part again
  (restarting the app doesn't), leaving anything already moved as it is.
- **Action Logs** (titled "Action Logs (Telemetry)") is the audit trail for the
  whole app. Two kinds of event write a row: a button press in an
  **Executable** widget (the widget, the action name, who pressed it, when, and
  the view it was on) and a data migration export or import. Views, publishing
  and sharing changes are not logged. The columns are Timestamp, Widget, Action,
  User, Domain, User Explanation and Action ID; opening a row also shows a
  **Request ID** and **Dashboard Context**, a snapshot of the view's name, tab
  and every widget on the tab with its settings. **Search logs…** searches only
  the 100 most recent entries; there are no date filters or export. The Request
  ID is added as a comment (`cc-action: <id>`) at the front of the SQL an
  executable widget runs, so searching Databricks query history for it finds the
  exact statement. The row is written first; if it can't be, the action doesn't
  run. Only Administrators can read the log: the app refuses it to anyone else,
  though everyone's actions are still recorded.

## Drafts and publishing

Views, widgets and agents all work the same way, like a Databricks dashboard.
Each has a **draft** — the working copy that people who can manage it edit — and
**published versions**, which is what everyone it is shared with sees.

- **Saving writes the draft.** Every change a manager makes, from dragging a
  widget to saving in Widget Studio or Agent Studio, updates the draft in place.
  It adds no version and nobody with only Can use sees it.
- **Publish** turns the draft into the next published version. People with Can
  use see it straight away, and the draft is gone until the next change. A chip
  says where things stand: **Not published yet**, **Published** (people see
  exactly what you see) or **Unpublished changes**; hover it for what it means.
  **Publish** shows only when there is something to publish, so on something
  already published with no changes it is hidden, not greyed out.
- **The Draft / Published switch** lets a manager look at the published version
  everyone else sees, then switch back to the draft. It appears only when there
  are unpublished changes (the two differ), or while you are on Published, so
  you can get back.
- **Discard draft** throws away every unpublished change and goes back to the
  latest published version, after asking. It is offered only when there are
  unpublished changes: on a view it is **Discard draft…** in the ⋯ menu, in the
  studios it is in the bar. Something that has never been published has nothing
  to go back to, so it can't be discarded; delete it instead.
- **History** lists the published versions, who published each and when. On a
  view it is **Version history…** in the ⋯ menu, for managers; in Widget Studio
  it is **History** in the header, and in Agent Studio it is in the bar.
  **Revert** copies an older version into the draft; publish it to make it live
  again. Nothing published is ever overwritten.
- **Publishing a widget checks it again.** The same safety check that runs on
  Save draft runs on Publish, so a widget can't be published with code the
  studio would refuse to save.
- **Something never published is invisible** to everyone except the people who
  can manage it, even if it is shared with others.
- **Saved, but colleagues still see the old version?** Saving only changes the
  draft. Publish to make the change reach your colleagues, and check it is shared
  with them at all.

**Publishing a view checks what is on it.** The Publish dialog lists the widgets
on the view that have never been published or have unpublished changes, and the
agent pinned to it if that agent is in the same state. The dialog offers to
publish them together with the view; anything you can't manage is named so you
can ask whoever manages it. A widget left unpublished shows a "Not published yet"
card to people using the view. When an Administrator has turned on **Shared views
may only contain certified widgets** and the view is shared with anyone besides
its owner, the dialog also names the uncertified widgets, and the view can't be
published until they are certified. A view doesn't share its pinned agent: share
the agent with the same people so they can chat with it.

**Certify** flags a published version of a widget as reviewed and ready for
wide use. Anyone who can manage the widget can certify it, from the bar under
the Widget Studio tabs; it applies to the latest published version. Each new
version starts uncertified, because certification is a review of that particular
code. It is a signal to people browsing the Widget Library, and a requirement
for shared views only when an Administrator turns that setting on.

**Archive, Restore and Delete permanently.** Archiving a view takes it out of
everyone's sidebar, stops its link opening, and keeps every version; it then
shows under **Archived** for the people who manage it, where **Restore** brings
it back exactly as it was and **Delete permanently** removes every version for
good. A view shared with anyone besides its owner must be archived before it can
be deleted, so someone can notice it gone first; a private view can be deleted
straight away.

**Where did Dev and Test go?** Earlier releases had a **Workspace** switcher with
Dev, Test and Prod inside one app, and work was promoted from one to the next.
Drafts replace that. During the upgrade, everything that was in Prod became the
published version, and newer work from Dev (or Test, if it wasn't in Dev) became
its draft, ready for its managers to publish. Work that only ever existed in Dev
or Test became a draft that has never been published. Old links that name a
workspace still open. Widget Studio work that was never saved before the upgrade
isn't restored when the studio next opens. Separate deployments of the app — a development app, a
stage app and production — are unchanged; moving content between them is
*Moving data to another app*, below.

## Moving data to another app

Each deployment of the Command Center (the dev app, the test app, production) has
its own database, so widgets, views and agents made in one don't appear in
another. **Admin Panel → Data Migration** (Administrators) moves them:

1. In the app that has the data, choose what to include and **Download
   snapshot**. The file holds every published version and unpublished draft of
   every widget, view and agent, plus — if ticked — sharing (who can use and
   manage each item, and the Administrators) with the categories and domains,
   deployment settings, activity
   history (action logs and widget usage), and saved conversations with their
   attached files. Conversations are off by default: the file would contain
   everyone's chats.
2. In the other app, open Data Migration, choose the file, and pick a mode.
   **Merge** adds only what that app is missing and changes nothing already there;
   running it twice adds nothing the second time. **Replace** makes the chosen
   parts an exact copy of the snapshot, deleting that app's own rows in them.
3. **Preview** runs the whole import and undoes it, showing per table what would
   be added, skipped and deleted. **Import** is only offered after a preview of
   the same file and options.

On a Merge, the target keeps its own access level and its own draft wherever
both apps have one. A snapshot taken before the upgrade to sharing still imports:
its role mappings are turned into access lists and Administrators the same way
the upgrade turned this app's own, and the preview says so.

An import is all-or-nothing: if anything fails, nothing is changed. A Replace
that would leave you no longer an Administrator is refused, so you can't lock
yourself out. Exports and imports are recorded in Action Logs. The two apps never
connect to each other; the file is the only thing that moves, so treat it like a
database backup.

## Agent Studio and saved agents

**Agent Studio** in the sidebar is where the assistants offered in this chat are
authored. An agent is a saved bundle of:

- a **prompt** defining its persona and task instructions,
- optional **skills** — named blocks of guidance layered onto the prompt,
- selected **tools** from the AI Gateway MCP catalog (SQL, Genie, Unity Catalog
  functions, vector search indexes, external MCP connections), including the
  tools of any **Genie space** the author can open,
- optional small **Python tools** the author writes for it.

The tools an agent can be given (Genie, SQL, AI Gateway, MCP servers and
Python tools) are covered in *Agent tools*.

While drafting, the authoring assistant can **research your data** so the
prompt describes it accurately: it confirms tables and columns, runs read-only
SQL as you (to learn, say, which status values really exist), and can ask Genie
what a business term means here. Those are tools for writing the agent, not tools
the agent gets — its own tools are still the ones selected from the catalog.

Layout: above the chat, **New conversation** (speech-bubble icon) restarts the
authoring chat and keeps the draft. On the right, beside the agent's name (with
an *Unsaved changes* marker when there are any), sit **New agent**, **Open** and
**Save**. A bar under the header holds, for people who can manage the agent, its
state chip, the **Draft** / **Published** switch (only when there are
unpublished changes, or while on Published), **History** once it has been
published, **Discard draft** (only with unpublished changes) and **Publish**
(hidden when there is nothing to publish), with **Share** at the end for
everyone. **Save** writes the agent's draft; chat always
runs the published version, for everyone including its managers, so changes
reach people only after **Publish**. Switched to **Published**, the agent is
read-only. Someone who can only use an agent can open it and read it; for them
**Save** becomes **Save a copy**, which saves it as a new agent of their own.
New agent and Open ask before discarding unsaved work. **Delete agent**
is at the bottom of the **Settings** tab. While the authoring assistant writes,
its send button becomes **Stop**; stopping keeps what it wrote and leaves the
agent unchanged. Enter never stops it. If its reply describes an agent but the
draft didn't arrive in a usable form, a note under the reply says so (cut off, or
not valid JSON) and the editor is left as it was; asking again usually works. A
draft cut off at the length limit means raising **Agent Studio response length
limit** in Admin Panel → Settings.

The agent's tabs, on the right, are **Prompt** (its instructions, written as
markdown), **Skills**, **Python tools**, **Try it**, **Review** and **Settings**.
The **Settings** tab holds **Agent Name** (required to save, and what the
assistant's agent picker shows), **Description**, **Model**, the tool list, and **Delete agent**. Clicking the agent's name above the tabs jumps
to it.

The **Review** tab shows what the authoring assistant concluded: **Suggested
tools**, **Missing capabilities** (things asked for that no available tool
provides), **Open questions**, **Schema checks** (the queries it ran, OK or
FAILED) and **Python tool safety** notes. It reads **Review • stale** once the
draft has been edited since; asking the assistant to refine the agent refreshes
it. The **Try it** tab runs what is on screen — the draft with unsaved edits
included, or the published version when that is the one shown — exactly as the
sidebar chat would run the agent, with tools limited to what the author can reach;
nothing from that chat is saved, and **Clear** empties it. **Open** lists every
agent the author can manage or use, with a **Shared** badge and the author's
name on ones other people shared. If someone else saved the agent in the meantime,
saving is refused with a message to reload first.

Every agent also gets a tool for looking up how the Command Center itself works;
it is always attached and isn't in the tool list.

A new agent is shared with nobody but its author. **Share** gives people,
groups or everyone in this app **Can use** (they can pick it in the chat panel
once it is published) or **Can manage** (they can edit, publish and share it), as
described in *Sharing something and getting access*. Agents that were global
before the upgrade to sharing are shared with everyone in this app. Users pick
which agent they are talking to from the agent picker in the chat panel, which
lists only published agents they can use; the default agent is used when none is
chosen. A view whose pinned agent someone can't use opens with the default agent
for them. If an agent stops being available mid-conversation (it was unshared,
or never published), the next message answers "That agent isn't available to
you" instead of quietly switching agents; pick another agent to continue.

## Agent tools

The Genie tool to attach for plain-language questions about data is
**genie_one** (Genie One), listed under **Genie** as `genie/genie_one`. It runs
as the person chatting, so it sees only the data their Unity Catalog
permissions allow, and the app waits for Genie's answer itself. It used to be
listed as `genie_ask`; agents saved with that name use Genie One without being
edited.

Chips above Agent Studio's tool list show or hide each source of tools.
**SQL**, **Genie**, **AI Gateway** and **Custom apps** start shown (the last two
hold only servers an admin added); **Genie spaces**, **UC functions**, **Vector
search**, **External** and **Other** start hidden because there can be hundreds,
so turn a chip on to pick from it.

Jira and Confluence come from the built-in AI Gateway server
`system.ai.atlassian`, which the app doesn't find by itself: an Administrator adds
it under Admin Panel → Settings → **MCP servers agents can use**, and its tools
appear under the **AI Gateway** chip. Each person also signs in to Atlassian
once in Databricks under **AI Gateway → MCPs**; until then Agent Studio shows an
amber note naming the server instead of its tools, and **Refresh** lists them
after signing in. The same note appears when a server on that list doesn't
answer, which usually means its name is wrong. A chip only appears when it holds at least
one tool the author can reach, and each shows a count; a line under the list says
how many tools the chips are hiding, and a filter box narrows the list by name or
description. A Genie space is listed under its own name,
not the internal tool name. **Internal** lists plumbing the app drives itself,
such as Genie's poll tool, which can't be attached. The choice is remembered in
the browser, and a tool already selected stays visible whatever the chips say.
The list is kept for five minutes; **Refresh** asks the servers again, for
example after being given access to a new Genie space. The list is what the
author can reach as themselves in the workspace this app runs in, so a kind can
be empty for them, and Genie spaces, functions or indexes in a different
Databricks workspace are not listed.

**Python tools carry real privilege, and authoring one is a trusted activity.**
The code an author writes runs on the server whenever the agent decides to call
it. It runs in a restricted subprocess with the app's credentials stripped out
and limits on time and memory, which stops the common accidents — but it is a
validation sandbox, not a jail, and it is not a substitute for review. Anyone
can build an agent, so treat a Python tool as code to be read before the agent
is shared: before giving someone Can manage on an agent with Python tools, make
sure they have been through the organisation's secure-development training, and
read a new Python tool before sharing the agent widely or with everyone in this
app.

## Admin Settings: models and limits

Administrators choose the model in **Admin Panel → Settings**, from a searchable
list of the workspace's chat-capable models. Four are set separately: the model
behind this chat, the one that writes widget code in Widget Studio, a small
helper model for the studio's quick jobs (summarising a long conversation,
deciding whether to ask a question before a big build), and the one that drafts
agents in Agent Studio. The helper defaults to `system.ai.gpt-6-luna`, asked to
answer without reasoning so the quick jobs stay quick; on a workspace that doesn't
serve that model, the widget generation model is used instead. To use the
generation model deliberately, enter its name as the helper. The same page holds the chat agent's limits — how many tool calls
it may make in one turn, and how long a single answer may be.

**Model parameter overrides** (optional JSON, per model, such as
`{"gpt-5.6-luna": {"reasoning_effort": "medium"}}`; `null` stops sending one)
adjust a model's parameters; any a model refuses are dropped automatically. A
label above each Settings field says where its value comes from: **Set here**,
**Built-in default** or **From the deployment configuration**.

The limits, each a ceiling that costs nothing until something needs the room:

| Setting | Starts at | Allowed |
| --- | --- | --- |
| Response length limit (tokens) | 16,000 | 256 to 128,000 |
| Tool call timeout (seconds) | 90 | 5 to 600 |
| Genie query timeout (seconds) | 150 | 10 to 900 |
| Widget response length limit (tokens) | 16,000 | 1,000 to 128,000 |
| Widget generation timeout (seconds) | 300 | 30 to 1,800 |
| Agent Studio response length limit (tokens) | 16,000 | 1,000 to 128,000 |
| Tool calls per turn | 8 | 1 to 30 |
| Most rows one widget query can return | 1,000,000 | 1,000 to 10,000,000 |

A call to an MCP tool (SQL, Genie, a function) gets at least 30 seconds whatever
the tool call timeout says, because a Genie space takes 10 to 15 seconds to answer.

A deployment can start with other values, so the label above the field decides.

The response length limit is a ceiling, not a target — raising it costs nothing
until an answer needs the room, and models that allow less than the configured
number are adjusted down to their own limit automatically.

An individual saved agent can pin its own model in Agent Studio, which overrides
the deployment default for that agent only; left blank, it follows the default.
Changes apply to new conversations. Non-admins cannot see or change these
settings, and there is nothing to configure for a normal user.

Some features need setup only the organisation's own administrators can do, such
as an email account or a search feature switched on for the database. Each stays
off until its setup is in place, and the rest of the app works without it. The
**Setup** card at the top of Admin Panel → Settings lists them, says whether each
is ready, and for one that isn't, what is missing and the next step. **Check
again** re-checks after something has changed; otherwise the card can lag by up
to a minute. The same card shows when each background job (work the app does on
a timer, such as refreshing a search index) last ran, and whether it failed. If
someone asks why a feature is missing or greyed out, send their administrator to
that card.

## The assistant panel

This chat. It is the panel on the right of the screen; collapsed, it is the
round button at the bottom right, named for the selected agent. It knows which
view and widgets are on screen: the small print under the message box says how
many it can see ("Sees 3 widgets on this tab"). What it sees is a summary of
them — names, titles and configuration — not the rows or numbers drawn inside
them; to answer from that data it has to query it with its tools, and it may say
it can't tell which table feeds a widget. Tools run **on behalf of the signed-in
user**, so results reflect that user's own Databricks permissions and no
passwords or tokens are ever needed. A permission error from a tool describes the
user's access, not the assistant's.

The **pin** button beside the agent picker makes a view open the assistant with
the agent selected there (for anyone who can manage the view). Like every
change to a view, a pin goes into the view's draft and reaches other people when
the view is published. On a
view with several tabs it asks where: **This tab** or **Every tab** of the view;
a tab's own pin wins over the view's on that tab. Clicking a ticked choice
unpins it. **Settings → Assistant** sets the view's pin too, and shows how many tabs
pin their own. A pin is a starting point, not a lock: anyone can pick another agent
while they're on the view.

While an answer is being written, the send button becomes a red **Stop** button.
Stop ends the turn: no further tools run, and what was already written is kept and
marked *Stopped*. Enter never stops it, so the next question can be typed while it
works. Reloading or switching conversations does not stop a turn; the answer is
saved and there on return.

The assistant, and agents built in Agent Studio, can draw **charts** in the chat
from data they have just retrieved — ask for one ("chart that by month") if it
isn't offered. The menu on a chart exports it as PNG or SVG. Charts only use data
already in the answer; they cannot load anything from elsewhere.

Images in chat answers (here, in Widget Studio and in Agent Studio) are only shown
when they come from this app itself. An image from another site appears as a
small "image from … not loaded" placeholder: loading it would let a manipulated
answer send data to that site just by being displayed.

## Attaching files to the assistant

The paperclip in the assistant panel attaches a file to the conversation, and
files can also be dragged onto the panel. A screenshot or copied image pasted
into the message box (Cmd+V / Ctrl+V) is attached too, named "Pasted image" and
the time; when the clipboard also holds text, as it does for cells copied from
Excel, the text is pasted instead. Spreadsheets and CSVs, PDFs, Word
documents, JSON, plain text and images are accepted, up to 25 MB each and five
files per conversation. A chip above the message box shows each file being read
and then what it contains, such as "5,000 rows x 6 columns"; the X removes it.

Files are private to the person who uploaded them and stay available for the rest
of that conversation, so later questions can refer back to them. Deleting the
conversation deletes its files.

How the assistant reads them is worth knowing, because it explains what to expect:

- For a spreadsheet or CSV it sees the structure — sheets, columns, row counts and
  a few sample rows — and then queries the file to answer, so totals and counts
  come from every row rather than a sample, however large the file.
- For a document it searches for the passages that bear on the question and cites
  the page.
- Images, and short PDFs, are read directly, so charts, screenshots and scanned
  pages work.

If a file will not read, the chip says so. The usual causes are a scanned PDF with
no text layer, a password-protected file, or a format that is not in the list
above.

## Saved conversations

Conversations in the assistant panel are saved automatically. Reloading the
browser or leaving and coming back reopens the last conversation where it left
off. The clock icon in the panel header lists recent conversations, each of which
can be reopened, renamed with the pencil, or deleted with the trash. The
speech-bubble icon starts a new conversation and keeps the current one in the
list.

Conversations are private to each user; nobody else, including admins, sees them
in the app. The 50 most recent per user are kept, and older ones are removed
automatically. Choosing a different agent in the picker starts a new conversation,
leaving the previous one in the history list.

**Delete all my conversations** sits at the bottom of that clock-icon list and
removes every conversation the user owns, with their attached files. It asks for
confirmation once and cannot be undone.

An admin may also set **Delete conversations after (days)** in Admin Panel →
Settings. When set, any conversation untouched for that long is deleted for
everyone, attachments included; the default of 0 keeps them indefinitely.

## What the assistant is and is not

Answers come from a generative model. They can be wrong, and they can be
confidently wrong, so anything being acted on should be checked against the
source. A notice to that effect sits under the message box.

Everything the assistant reads, it reads as the signed-in user: Unity Catalog
decides which tables and Genie spaces are visible, and two people asking the same
question can correctly get different answers. Generating the reply itself is the
one exception — that runs as the application, because per-user entitlements to
foundation models proved unreliable — but no user data is read on that path.

Admins can narrow what the assistant may reach, in Admin Panel → Settings:

- **Allow the assistant to query Genie** and **Allow the assistant to run SQL**
  remove those tools entirely when off. The assistant still answers questions
  about the app itself and about attached files.
- **MCP servers agents can use** lists, one per line, the MCP servers every
  agent gets (the assistant uses them all; Agent Studio lists their tools). It
  starts with SQL and Genie One. An entry is a built-in server by name, such as
  `system.ai.atlassian`, or a path in this workspace such as
  `/api/2.0/mcp/functions/main/sales`; a URL on another host is refused, because
  each server is called with the signed-in person's own access. A custom MCP app
  can only be added in the deployment configuration.
- **Send images and PDFs to the model directly** governs whether raw attachments
  are uploaded to the model. Off, files are only ever read through text
  extraction, so scanned documents and screenshots stop working.
- Three settings are about the app rather than the assistant. **Enforce the
  Content Security Policy** (on) makes the browser block widget code from loading
  scripts or sending data anywhere except this app, the approved CDNs and the
  listed Databricks Apps; off, it only reports violations in the browser console,
  which is for diagnosing a widget that stopped rendering and shouldn't stay off.
  **Databricks Apps widgets may embed or call** (empty to start) lists, one per
  line, the other apps a widget may embed or fetch from — one app's host (a pasted
  URL is reduced to it) or a whole workspace as `*-<workspace-id>.<region>.databricksapps.com`.
  A workspace entry allows embedding its apps; fetching needs the app listed
  itself. **Shared
  views may only contain certified widgets** (off by default) means a view shared
  with anyone besides its owner can only be published while every widget on it is
  certified; the Publish dialog names any that aren't. A private view is never
  affected. Leave it off on a development deployment, where little is certified
  yet.
- **Tell the assistant what is on screen** governs whether each question carries a
  summary of the current dashboard. Off, the assistant cannot answer "what am I
  looking at" but nothing about the layout leaves the app.

## Where to find help and what changed

**Getting Started** under Resources reopens the welcome panel: the five ways
into the app, each a button that opens it.
**User Guide** under Resources documents the app for end users and admins.
**Release Notes**, directly below it, lists what changed in each release, newest
first. Both are in the sidebar's Resources group.
