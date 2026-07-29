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

A view is a tab: a named grid of widgets. Views are per-user unless they are
global.

- **New View** in the sidebar creates a blank one. The pencil icon renames it.
- **Global Views** are shared templates. A user only sees the global views whose
  domain they have at least Viewer access to. Hovering one and clicking the copy
  icon duplicates it into My Views, where it becomes editable.
- **Lock** (top right) freezes the layout so widgets cannot be dragged or
  resized by accident; **Unlock** reverses it. A global view is read-only for
  anyone who is not an admin.
- **Share** (top right) copies a link to the current view. The share icon on an
  individual widget copies a link that opens that widget full-screen.

## Widgets

Widgets are the building blocks of a view — charts, tables, text, forms, embedded
pages, or buttons that perform an action.

- Add one by dragging it out of the Widget Library onto the grid, or with the
  `+` button on its library card.
- Move a widget by its drag handle (the grip at its top-left); surrounding
  widgets flow out of the way. Resize from the bottom-right corner.
- The widget header carries per-widget controls: full-screen, copy link, remove,
  and — when the widget was built to accept runtime inputs — a gear that opens
  its configuration.
- Widgets that exist in more than one version have a version picker in the
  header, so a user can pin an older version on their own view.

## Widget Library

Opens from the **Widget Library** button in the sidebar, or by pressing `w`.
It lists the widgets available to the user, filtered to the domains they can
view, and is searchable. Widgets certified in production are flagged as such.

## Widget Studio

Where widgets are created and edited, at **Widget Studio** in the sidebar
(visible only to users who can create widgets). No React expertise is required
for simple and moderately complex widgets — they are generated from a
description.

1. **Configuration tab** — name, description, help text, category, domain,
   default size, whether the widget performs an executable action, and its
   configuration mode (whether end users can pass runtime inputs). The Data
   Source (None, API, or SQL) can be tested here, and the extracted schema is
   handed to the generating agent.
2. **The agent** — describe the widget in the chat and it writes the TSX. Asking
   for a change edits the existing code in place rather than rewriting the whole
   component. After generating, it also proposes Configuration-tab values;
   anything already filled in by hand is left alone.
3. **TSX Editor / Live Preview** — the code and its live rendering. **Reload**
   re-runs the widget so anything that only happens on first load can be
   repeated without editing code.
4. **Publish / Update** — saves to the Dev environment and increments the
   version. The widget is immediately available in the Widget Library to users
   with Dev access.

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
| Editor | Everything a Viewer can, plus create, edit, and reorganize the domain's widgets and global views |
| Admin | Everything an Editor can, plus promote and certify across environments and manage that domain's role mappings |

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

Domain admins map roles in the UI, no database work required: **Admin Panel**
(shield icon, under Resources) → **Access Management** → Create New Mapping.
Supply the exact Databricks group or role name (`finance-team`), the domain
(`Finance`), and the level, then Add Role Mapping. Admins can only manage
mappings for domains where they are admins; global admins can manage all.

A user who is blocked should ask an admin of that domain to add a mapping for a
Databricks group they belong to. Access to *data* (a catalog, schema, or table)
is separate and is granted in Databricks itself, not here.

## Environments and promoting work

There are three environments — **Dev**, **Test**, and **Prod** — so
work in progress cannot disrupt production users.

- Saving a widget in Dev increments its version, giving an immutable history.
- **Widget Promotion** (in the Admin Panel) copies a chosen version into a
  higher environment. Selecting an older version in the same dropdown is how a
  rollback is done — it restores that exact historical definition.
- **Certify**, in the production column, flags a widget as reviewed and
  enterprise-ready. It is a signal to end users, not a permission.
- **View Promotion** does the same for global views. Promote every widget a view
  uses *before* promoting the view, or it will render with missing widgets in the
  target environment.
- Promotion, rollback, and certification require Admin on the asset's domain.

## Agent Studio and saved agents

**Agent Studio** in the sidebar is where the assistants offered in this chat are
authored. An agent is a saved bundle of:

- a **prompt** defining its persona and task instructions,
- optional **skills** — named blocks of guidance layered onto the prompt,
- selected **tools** from the AI Gateway MCP catalog (SQL, Genie, Unity Catalog,
  and so on),
- optional small **Python tools** the author writes for it.

The **Try it** tab runs the draft agent exactly as the sidebar chat would.
Saved agents have one of three visibilities: **personal** (only the author),
**domain** (anyone with access to that domain; domain editors can edit), or
**global** (everyone; only global admins can create or edit). Users pick which
agent they are talking to from the agent picker in the chat panel; the default
agent is used when none is chosen.

## The assistant panel

This chat. It opens from the button at the bottom of the sidebar and knows which
view and widgets are currently on screen. Tools run **on behalf of the signed-in
user**, so results reflect that user's own Databricks permissions and no
passwords or tokens are ever needed. A permission error from a tool describes the
user's access, not the assistant's.

## Where to find help and what changed

**User Guide** under Resources documents the app for end users and admins.
**Release Notes**, directly below it, lists what changed in each release, newest
first. Both are in the sidebar's Resources group.
