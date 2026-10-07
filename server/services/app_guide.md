<!--
  Knowledge base for the `app_help` tool (services/app_help.py) — this is what
  the chat agent reads when a user asks how the Command Center app itself works.

  Conventions:
    * One topic per `##` section. The section titles are advertised verbatim in
      the tool description, so name them the way a user would ask.
    * Keep it factual and user-facing: what the button is called, what happens
      when you click it, who is allowed to. No implementation detail — the model
      cannot see the code and must not speculate about it.
    * This is a SEPARATE audience from src/pages/UserGuidePage.tsx (humans) and
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

The left sidebar holds views (My Views and Global Views), the Widget Library,
Widget Studio, Agent Studio, and — under Resources — the User Guide, Release
Notes, and Admin Panel. The assistant (this chat) opens from the button at the
bottom of the sidebar.

## Views and layouts

A view is a named set of widgets, laid out on one or more tabs. Views are
per-user unless they are global.

- **New View** in the sidebar creates a blank one. The pencil icon renames it.
- **Add tab** (top right) gives a one-tab view a second tab, asking what to
  call the new tab and the one already there (left empty, that one becomes
  "Overview"); a tab bar then appears under the header with a **+** for more (up
  to 50). Double-click a tab, or select it and press F2, to rename it; drag it to
  reorder, and use its **×** to delete it (asking first in a dialog if it holds
  widgets; the last tab can't be deleted). From the keyboard, Tab reaches the
  tab bar, the arrow keys and Home/End move along it, and Enter or Space opens
  a tab. Whoever may move widgets
  in a view may change its tabs: not while it is locked, and in a global view
  only an admin. A widget added from the Widget Library goes on the tab being
  shown.
- A tab is **Cards on a grid** (several widgets, each in a card; the default)
  or a **Full page** (one widget filling the whole tab, with no card around it,
  for a landing page or hub). **Add tab** and the **+** ask which. The small grid/page icon on the
  tab being shown switches it; a grid holding more than one widget can't
  become a full page until the others are removed. On a one-tab view, **Add
  tab** → **Or make this whole view one full page** does the same. Any tab may be a page, in
  any order.
- On a page, drag a widget from the Widget Library onto it (dropping another
  replaces it, after asking). The toolbar in its top-right corner — shown only
  to whoever may change the tab, inside Command Center — offers **Change
  widget**, **Edit in Widget Studio**, the gear for the widget's settings (where
  its links are set), and remove (after asking). The gear is grayed out for a
  widget built without settings. To turn the page back into cards on a grid, use
  the grid/page icon on the tab.
  A view opened on its own shows the page without the toolbar. Any widget can
  go on a page, but one built as a page in Widget Studio (marked **PAGE** in
  the Widget Library) is the one made to fill it.
- The address names the tab being shown, so a link opens on that tab and Back
  steps between tabs. A link to the first tab doesn't name it, so it opens
  whichever tab is first.
- **Global Views** are shared templates. A user only sees the global views whose
  domain they have at least Viewer access to. Hovering one and clicking the copy
  icon duplicates it into My Views, where it becomes editable.
- **Lock** (top right, on a view; not on the Admin Panel, guides or studios) freezes the layout so widgets cannot be dragged or
  resized by accident; **Unlock** reverses it. A global view is read-only for
  anyone who is not an admin.
- **Share** (top right, on a view) copies a link to the current view. The share icon on an
  individual widget copies a link that opens that widget full-screen. The address
  in the browser is the same link, so copying it from there works too.
- Opening a link to someone else's personal view adds it to the opener's
  **Shared Views**, read-only; the hover **×** there removes it. Links still need
  the usual sign-in, and a global view opens only for people with access to its
  domain. Links copied before the link format changed (`?shared_view=…`,
  `#/view/…`) keep working; new ones look like `#/app/…`.
- **Settings** (top right, for anyone who may rename the view) has four
  sections listed down its left side: **Opening**, **Look**, **Filters** and
  **Assistant**. A red dot marks a section with something to fix, and the
  footer names it, because **Save** stays off until it is fixed.
- **Opening** decides how the view's link opens. **Inside Command Center** is the default and how every view has
  always opened. **On its own** opens just that view: no sidebar, no Widget
  Library, no studios, under the title, logo and browser-tab icon set there; those
  three fields only appear once **On its own** is chosen. The assistant appears
  too, unless the view's agent is **No agent**. Branding is only used on its
  own; inside Command Center the view keeps its name.
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
  small print) turns light by itself. **Header** (White or The dark color) colors
  the bar along the top when the view is opened on its own, and the assistant's
  header beside it, which is always the same height so the two make one line;
  inside Command Center, Command Center's header is used. **Cards** sets their
  corners, edges (flat, outlined, shadowed), title (in a gray bar, in an
  accent-color or dark-color bar with a white title, plain, or **No title**,
  which leaves the title off and shows the card's buttons only on hover) and
  **Spacing** between them (compact, standard, roomy); a card's body stays
  white so widgets stay readable. Inside Command Center the look covers the
  view's tabs, filter bar, background and the assistant panel, while the
  sidebar and header stay Command Center's; opened on its own, the whole page
  uses it. A view with no look, and every page that isn't a view (studios, User
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
- **Version history.** Changes to a personal view within five minutes of each
  other are kept as one version, so a burst of moving and resizing doesn't fill
  its history. Every save to a global view is still its own version, because
  promotion copies and rolls back to those.
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
  default.
  A view built from several views keeps their filters.
- A view opened on its own is read-only for everyone, including its owner; its
  tabs can be switched but not changed.
  **Copy link** there goes to the same people who get **Share** in Command
  Center, and **Edit** goes to anyone who may change the view's settings.
  **Edit** reopens it inside Command Center at an address starting
  `#/workspace/…`, which keeps it there on reload; **Preview** in the header goes
  back to seeing it on its own. A view opened with **Preview** is labelled
  **Preview** and has **Back to editing** (or **Back to Command Center** for
  someone who can't change it) in place of **Edit**, returning to the same tab;
  the label and button are only there for whoever pressed **Preview**, not for
  people opening the link. Who can open the link is unchanged, and opening
  someone else's personal view on its own still adds it to **Shared Views**.

## Widgets

Widgets are the building blocks of a view — charts, tables, text, forms, embedded
pages, or buttons that perform an action.

- Add one by dragging it out of the Widget Library onto the grid, or with the
  `+` button on its library card.
- Move a widget by its drag handle (the grip at its top-left); surrounding
  widgets flow out of the way. Resize from the bottom-right corner.
- The widget header carries per-widget controls: full-screen, copy link, remove,
  and — when the widget was built to accept runtime inputs — a gear that opens
  its settings. On a view someone can't change (locked, global, shared) a card
  shows only its title and full-screen, plus copy link; on its own, not even
  that. Long titles are cut short with "…"; hover for the whole name.
- Widgets that exist in more than one version have a version picker in the
  header, so a user can pin an older version on their own view. Saving a
  widget's settings keeps that pin.

**What a widget is allowed to contain.** Saving a widget — in Widget Studio or by
importing one — is refused if its code uses `eval`, `new Function`,
`document.write`, `innerHTML` or `dangerouslySetInnerHTML`, or if it references
any address other than this app's own `/api/...` paths and the approved CDNs
(cdn.jsdelivr.net, code.highcharts.com, unpkg.com, cdnjs.cloudflare.com). The
browser enforces the same rule independently, so a widget that got round the save
check still could not load a script or send data off-list. Widget code is
generated from a prompt, and these two rules are what keep "generated" from
meaning "can reach anywhere".

A widget whose SQL data source **changes** data (INSERT, UPDATE, DELETE, MERGE and
so on) can only be saved if the widget is marked **Executable**. That is what
records every change its controls make in **Action Logs**, with who made it. There
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
It lists the widgets available to the user, filtered to the domains they can
view, and is searchable. Widgets certified in production are flagged as such,
and widgets built as pages are marked **PAGE**.

## Widget Studio

Where widgets are created and edited, at **Widget Studio** in the sidebar
(visible only to users who can create widgets). No React expertise is required
for simple and moderately complex widgets — they are generated from a
description.

1. **Configuration tab** — name, description, help text, category, domain,
   default size, whether the widget performs an executable action, and its
   configuration mode (whether end users can pass runtime inputs). The Data
   Source (None, API, Databricks API, or SQL) can be tested here with **Test &
   Extract Schema**; the schema — real column types for SQL — and a few sample
   rows are shown and handed to the generating agent. Tests run as you, with your
   own permissions. A SQL statement that changes data (INSERT, UPDATE, MERGE…) is
   never run to test it; the studio says so instead. An external API is called
   from your browser, exactly as the widget will call it, so a CORS block shows up
   here. Testing a SQL source also counts the rows it
   returns, which decides how the agent builds. Searching, sorting and paging can
   happen in the browser or in the query, and both work at any row count; the
   deciding factor is how much data the browser would download, about 10 MB
   (rows times columns). Under that, the widget fetches everything once and works
   locally; over it, paging, sorting, searching and totals are pushed into SQL so
   the widget only ever holds one page. An untested source is treated as large.
   A query returns its first 500 rows unless the widget asks for more, and the
   response says when rows were left out; a user who "hit a row limit" usually
   means this, and the fix is to ask the studio agent to fetch the whole result
   or to page in SQL.
2. **The agent** — describe the widget in the chat and it writes the TSX. Asking
   for a change edits the existing code in place rather than rewriting the whole
   component. After generating, it also proposes Configuration-tab values;
   anything already filled in by hand is left alone. While it works, **Thinking**
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
3. **Attachments and screenshots** — the paperclip attaches spreadsheets,
   documents and images for the agent to read, a screenshot or copied image can
   be pasted straight into the message box, and **Send screenshot to agent**
   under the preview attaches a picture of the widget as it currently looks.
   Neither sends on its own: the file waits on the next message, so "this column
   is too narrow" arrives with the thing it describes.
4. **TSX Editor / Live Preview** — the code and its live rendering. **Reload**
   re-runs the widget so anything that only happens on first load can be
   repeated without editing code. The studio watches the preview run: each
   request the widget makes (and how many rows came back), anything it logs as an
   error, and errors it throws. If code the agent just wrote fails when it runs —
   a query rejected as invalid, a crash in its data handling — the agent is sent
   what happened and fixes it on its own, up to twice. It does not try to fix
   failures code can't fix: a permission error (403), a server error, or the
   configured data source itself failing, which needs fixing on the
   Configuration tab.
   **Problems**, the bar under the preview and the code, lists two things: rule
   checks on the code (an import widgets can't use, a script from a CDN that
   isn't allowed, a write without the audit trail, text too light to read, a
   class the app's stylesheet doesn't have and so does nothing, a font that
   isn't bundled, and similar) and what happened in the last run. The agent is given both with every
   request. **Fix with agent** asks it to fix everything listed. Rule errors in
   code the agent wrote are fixed automatically, like a failed run; warnings are
   left to you.
5. **Card or page** — the switch above the preview. A **Card** sits on a
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
6. **Agent settings** (the sliders icon above the chat) — two options, remembered
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
7. **Save / Publish** — saves to the Dev environment and increments the version,
   and leaves you in the studio to carry on working. The widget is immediately
   available in the Widget Library to users with Dev access. The **X** closes the
   studio.
8. **Stop** — while the agent works, the send button becomes a red Stop button
   and Enter does nothing. Stop ends the turn at once: steps that already
   finished stay in the editor (each has a History entry) and nothing else is
   applied. **Stop after this step**, on multi-step builds, lets the current step
   finish first.

Layout: only the agent settings sit above the chat. Everything about the widget
is in the right-hand header — the tabs, then **History**, **Reload**,
**Promote** (see *Environments and promoting work*), a **⋯** menu with *Import
from file*, *Export to file* and *Reset studio*, then **Save / Publish** and the
X.

A widget can also be exported to a JSON file and imported elsewhere, which is
how widgets move between disconnected environments.

## Domains

A domain is a logical grouping of assets — global views, widgets, and saved
agents — used to control who can see and change what. Finance, Supply Chain,
Sales are typical. Assigning a widget holding sensitive data to a domain means
users without access to that domain cannot see or embed it.

## Roles and permissions

Access is role-based, per domain, at three levels:

| Level | Can do |
| --- | --- |
| Viewer | See and interact with that domain's global views and widgets |
| Editor | Everything a Viewer can, plus create, edit, and reorganize the domain's widgets and global views, and promote, roll back and certify them in environments where they hold Editor |
| Admin | Everything an Editor can, plus manage that domain's role mappings |

Key rules:

- **The highest level wins.** Permissions are additive: a user mapped to both
  Viewer and Editor on the same domain gets Editor. Being a Viewer on one domain
  never limits Editor rights on another.
- The app keeps **no user directory of its own**. It reads the signed-in user's
  Databricks groups, roles, and username through SCIM/entitlements, and a
  mapping links one of those external names to a domain at a level.
- A **Global Admin** (a mapping of a role to the `global` domain at Admin level)
  bypasses all domain checks. Running locally with `DEV_MODE=true` grants this.
- Permissions apply at the next session, so a newly granted user may need to
  reload.

## Managing access and requesting access

Global admins map roles in the UI, no database work required: **Admin Panel**
(shield icon, under Resources) → **Role Mappings**. Pick the Databricks group or
user from the search box, the domain from the list, and the level, then **Add
Mapping**. **Assign Global Administrator** at the top of the same page does the
same for the `Global` domain.

The group field checks the name against Databricks as you type, because a mapping
only applies to someone whose group (or username) matches it **exactly, capitals
included**. A name that doesn't exist, or exists with different capitals, is
refused with the reason — for a capitalisation slip it offers the right spelling.
If Databricks can't be reached for the check, the name is saved as typed and the
form says so. Domains come from **Categories & Domains**, so add a new domain
there first; an existing mapping whose domain has since been renamed or deleted is
flagged "not a domain" in the table.

A user who is blocked should ask a global admin to add a mapping for a Databricks
group they belong to. Access to *data* (a catalog, schema, or table) is separate
and is granted in Databricks itself, not here.

## Environments and promoting work

There are three environments — **Dev**, **Test**, and **Prod** — so
work in progress cannot disrupt production users.

- Saving a widget in Dev increments its version, giving an immutable history.
- Promote a widget from **Widget Studio** — the **Promote** button in its header
  opens a Dev → Test → Prod panel for that widget — or from **Admin Panel →
  Widget Promotion**, which lists every widget. Both do the same thing.
  **Promote to Test** copies Dev's latest *saved* version (save unsaved edits
  first); **Promote to Prod** copies Test's. Each environment numbers its own
  versions, so Dev v8 can arrive in Test as v3. A widget must be published before
  it can be promoted.
- **Roll back to** an older version in Test or Prod makes it current again,
  restoring that exact historical definition.
- **Certify**, in Prod, flags the current version as reviewed and
  enterprise-ready. It is a signal to end users, not a permission.
- **View Promotion** does the same for global views, every tab at once. Before
  promoting, the confirmation checks the target environment and lists widgets
  the view uses that it doesn't have (with **Promote them too**, on by default,
  which copies each at its current version in the source and needs Editor on
  that widget's domain), widgets pinned to a version that differs there, pinned
  agents that aren't there (agents can't be promoted, so recreate them there or
  re-pin), and, when global views must hold certified widgets, the uncertified
  ones. A view promoted without its widgets shows without them.
- **Removing a global view** is two steps, both on the View Promotion screen and
  both needing Editor or Admin on the view's domain. **Remove** archives it: it
  leaves everyone's sidebar in Dev, Test and Prod, and every version is kept. The
  **Archived** button lists archived views, where **Restore** brings one back
  exactly as it was and **Delete permanently** removes every version for good. A
  global view must be archived before it can be deleted. A user's personal views
  are closed from the sidebar, which deletes them.
- Promotion, rollback, and certification require Editor or Admin on the asset's
  domain in the environment being promoted into. Without it the studio panel
  shows the status read-only.

Promotion moves single widgets and views between Dev, Test and Prod *inside one
app*. Moving everything to a different app — which has a database of its own — is
**Moving data to another app**, below.

## Moving data to another app

Each deployment of the Command Center (the dev app, the test app, production) has
its own database, so widgets, views and agents made in one don't appear in
another. **Admin Panel → Data Migration** (global admins) moves them:

1. In the app that has the data, choose what to include and **Download
   snapshot**. The file holds every version of every widget, view and agent, plus
   — if ticked — the taxonomy and role mappings, deployment settings, activity
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

An import is all-or-nothing: if anything fails, nothing is changed. A Replace
that would remove your own global admin mapping is refused, so you can't lock
yourself out. Exports and imports are recorded in Action Logs. The two apps never
connect to each other; the file is the only thing that moves, so treat it like a
database backup.

## Agent Studio and saved agents

**Agent Studio** in the sidebar is where the assistants offered in this chat are
authored. An agent is a saved bundle of:

- a **prompt** defining its persona and task instructions,
- optional **skills** — named blocks of guidance layered onto the prompt,
- selected **tools** from the AI Gateway MCP catalog (SQL, Genie, Unity Catalog,
  and so on),
- optional small **Python tools** the author writes for it.

**Python tools carry real privilege, and authoring one is a trusted activity.**
The code an author writes runs on the server whenever the agent decides to call
it. It runs in a restricted subprocess with the app's credentials stripped out
and limits on time and memory, which stops the common accidents — but it is a
validation sandbox, not a jail, and it is not a substitute for review. Domain
admins should grant the editor rights that allow Python tool authoring only to
people who have been through the organisation's secure-development training, and
should treat a new Python tool as code to be read before the agent goes anywhere
near a shared domain or global visibility.

While drafting, the authoring assistant can **research your data** so the
prompt describes it accurately: it confirms tables and columns, runs read-only
SQL as you (to learn, say, which status values really exist), and can ask Genie
what a business term means here. Those are tools for writing the agent, not tools
the agent gets — its own tools are still the ones selected from the catalog.

Layout: above the chat, **New conversation** (speech-bubble icon) restarts the
authoring chat and keeps the draft. On the right, beside the agent's name (with
an *Unsaved changes* marker when there are any), sit **New agent**, **Open**, and
**Save**. New agent and Open ask before discarding unsaved work. **Delete agent**
is at the bottom of the **Settings** tab. While the authoring assistant writes,
its send button becomes **Stop**; stopping keeps what it wrote and leaves the
agent unchanged. Enter never stops it. If its reply describes an agent but the
draft didn't arrive in a usable form, a note under the reply says so (cut off, or
not valid JSON) and the editor is left as it was; asking again usually works. A
draft cut off at the length limit means raising **Agent Studio response length
limit** in Admin Panel → Settings.

The **Try it** tab runs the draft agent exactly as the sidebar chat would.
Saved agents have one of three visibilities: **personal** (only the author),
**domain** (anyone with access to that domain; domain editors can edit), or
**global** (everyone; only global admins can create or edit). Users pick which
agent they are talking to from the agent picker in the chat panel; the default
agent is used when none is chosen.

## Which model the assistant uses

Global admins choose the model in **Admin Panel → Settings**, from a searchable
list of the workspace's chat-capable models. Four are set separately: the model
behind this chat, the one that writes widget code in Widget Studio, a small
helper model for the studio's quick jobs (summarising a long conversation,
deciding whether to ask a question before a big build), and the one that drafts
agents in Agent Studio. The helper defaults to `system.ai.gpt-6-luna`, asked to
answer without reasoning so the quick jobs stay quick; on a workspace that doesn't
serve that model, the widget generation model is used instead. To use the
generation model deliberately, enter its name as the helper. The same page holds the chat agent's limits — how many tool calls
it may make in one turn, and how long a single answer may be.

The response length limit is a ceiling, not a target — raising it costs nothing
until an answer needs the room, and models that allow less than the configured
number are adjusted down to their own limit automatically.

An individual saved agent can pin its own model in Agent Studio, which overrides
the deployment default for that agent only; left blank, it follows the default.
Changes apply to new conversations. Non-admins cannot see or change these
settings, and there is nothing to configure for a normal user.

## The assistant panel

This chat. It opens from the button at the bottom of the sidebar and knows which
view and widgets are currently on screen. Tools run **on behalf of the signed-in
user**, so results reflect that user's own Databricks permissions and no
passwords or tokens are ever needed. A permission error from a tool describes the
user's access, not the assistant's.

The **pin** button beside the agent picker makes a view open the assistant with
the agent selected there (for anyone who may change the view's settings). On a
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
- **Send images and PDFs to the model directly** governs whether raw attachments
  are uploaded to the model. Off, files are only ever read through text
  extraction, so scanned documents and screenshots stop working.
- **Tell the assistant what is on screen** governs whether each question carries a
  summary of the current dashboard. Off, the assistant cannot answer "what am I
  looking at" but nothing about the layout leaves the app.

## Where to find help and what changed

**User Guide** under Resources documents the app for end users and admins.
**Release Notes**, directly below it, lists what changed in each release, newest
first. Both are in the sidebar's Resources group.
