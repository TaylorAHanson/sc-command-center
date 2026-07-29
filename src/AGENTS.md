# AGENTS.md — Frontend (React SPA)

Read `../AGENTS.md` first. This file covers conventions inside `src/`.

React 19 + TypeScript + Vite, styled with Tailwind (Qualcomm palette:
`qualcomm-navy` `#001E3C`, `qualcomm-blue` `#007BFF`). Dashboard grid is
`react-grid-layout`; charts use Highcharts.

## Talking to the backend

Always use relative `/api/...` paths. `src/api.ts` sets `const API_BASE =
'/api'` and Vite proxies that to `127.0.0.1:8001` in dev (`vite.config.ts`); in
production FastAPI serves this bundle from `dist/`, so the same relative paths
work with no origin config. Never introduce a hardcoded host or port.

**No secrets, ever.** No API keys, tokens, or connection strings in `src/` —
not in code, not in `localStorage`. Anything requiring a credential goes through
a backend route. Client-side integration is acceptable only for embeds that
manage their own session (a Tableau iframe, for example).

Prefer adding a typed helper to `api.ts` over scattering raw `fetch` calls, and
follow the existing pattern there: catch, log, and return a safe fallback so one
failing widget can't blank the dashboard.

## The dynamic widget runtime — the biggest constraint here

Widgets are **not** files in this repo. They're TSX strings in the database,
compiled in the browser at load time by `loadCustomWidgets()` in
`widgetRegistry.ts`, which also holds the type contracts (`WidgetProps`,
`WidgetDefinition`, `ConfigField`).

Read that function before touching anything widget-related. It does a
deliberately ordered two-pass `@babel/standalone` transform — pass 1
(`react` + `typescript` presets) compiles JSX and elides *type-only* imports,
pass 2 (`transform-modules-commonjs`) rewrites any remaining runtime `import`
— then evaluates the result in `new Function('React', 'useScript', ...)` with a
minimal CommonJS shim. So `useScript` is a genuine injected parameter, and
`require` resolves only to React, ReactDOM, or a matching `window` global,
throwing a clear per-widget error otherwise (which keeps one bad widget from
failing the whole registry load).

Practical consequences for widget code:

- `import React, { useState } from 'react'` does work (pass 2 turns it into the
  shimmed `require`), but the generator prompt tells the model never to import
  anything and to use `React.useState` instead. Keep it that way — the
  conservative rule avoids a class of failures that are invisible until a widget
  runs in a user's dashboard. Anything not React or a loaded global still throws.
- Third-party libraries load through `useScript(url, globalName)` from the
  jsDelivr CDN (do not redefine it), initialized imperatively against a `useRef`
  container with a cleanup function to avoid duplicate renders.
- `lucide-react` icons are unavailable inside widget code.
- Arbitrary Tailwind values (`w-[150px]`, `bg-[#ff0000]`) don't work, because only
  standard utility classes exist in the compiled stylesheet — use an inline
  `style={{ ... }}` for exact measurements or colors.
- Widgets render on white and are user-resizable, so they need dark text
  (`text-slate-800`, `text-gray-900`) and fluid layout (`w-full`, `h-full`).

The authoritative, more detailed contract is
`server/routes/agent_instructions.md` — it's the prompt sent to the widget
generator, so if you change what the runtime supports, change that file too or
the LLM will keep emitting code the runtime rejects.

## Widget Studio (`pages/WidgetStudio.tsx`)

Two behaviors there are easy to break by accident:

- **The agent may fill Configuration fields, but never overwrite a person's.**
  `touchedSettingsRef` records every field the user typed into or picked, plus
  every field on a widget opened for editing or imported from a file; a field is
  also considered theirs once a suggestion has filled it. `applySuggestedSettings`
  skips anything in that set, and the keys are sent to the backend as
  `locked_settings` so the model doesn't even propose them. If you add a
  Configuration field, wire `markSettingTouched` into its `onChange` or the agent
  will start clobbering it.
- **Reload re-fires the widget without changing its code.** `previewNonce` is a
  dependency of the compile effect, so bumping it recompiles; the new component
  function is a different type to React, which remounts and therefore re-runs
  mount-time data loads.

Category and domain come from `/api/taxonomy/*`. A failed load keeps the previous
values and shows a retry rather than falling back to an empty list — an empty
picker is indistinguishable from a deleted taxonomy, which has caused real
confusion. The load also guards against races with a run counter.

## Code editing (`components/CodeEditor.tsx`)

Every code box in the app — the Widget Studio TSX editor, its SQL data-source
field, Agent Studio's Python tool editor — is this one component: a transparent
`<textarea>` over a highlight.js-rendered `<pre>`, plus a line-number gutter. It
stays a textarea deliberately, so the value is controlled exactly as the plain
textareas it replaced were, without adopting an editor framework.

Three invariants hold it together; breaking any of them shows up as text drifting
out from under the caret:

- **Nothing wraps.** The gutter prints one number per newline, so a wrapped line
  would desynchronize it. Long lines scroll horizontally instead and the gutter is
  `sticky left-0`.
- **The `<pre>` sizes the box; the textarea is stretched over it** with matching
  font, padding, and line height. One scroll container moves both, so there is no
  scroll-sync code to get wrong.
- **The caller supplies the background** via `className`. The gutter inherits it
  to mask code scrolling underneath, so a transparent container leaks text behind
  the numbers.

Languages are registered individually in that file (TSX is highlighted with
highlight.js's TypeScript grammar, which handles embedded JSX); registering the
full language set would cost hundreds of KB in the bundle. The theme import
supplies token colors only — `.hljs`'s own background is intentionally unused.

## Release notes

`RELEASE_NOTES.md` at the repo root is imported with `?raw` by
`pages/ReleaseNotesPage.tsx`, reached from the Resources group in the sidebar. It
is bundled at build time, so a deployment's notes always match its code. Update
it in the same commit as any user-visible change.

That page strips HTML comments before rendering. `react-markdown` has no raw-HTML
plugin here, so it *escapes* HTML into visible text rather than dropping it, and
the file opens with a comment holding the authoring conventions.

## Browser tab title

`index.html` ships `Command Center`; `App.tsx` then appends the deployment
environment (`Command Center - Dev`) for anything that is not prod. The
environment comes from `GET /api/health` (`APP_ENVIRONMENT` on the server, set
per bundle target) rather than a `import.meta.env` constant, because the same
built assets are promoted from dev to stage to prod — a build-time value would
lie everywhere except where it was built. `npm run dev` assumes `local`.

## State and cross-widget communication

- `store/dashboardStore.tsx` — `DashboardProvider` / `useDashboardStore`, owning
  tabs, layouts (`WidgetLayout`, `Tab`), and dashboard variables.
- `contexts/ActionContext.tsx` — `useActionContext` plus
  `ExecuteActionPropInjector`, which clones children to inject an
  `executeAction(name, callback)` prop into executable widgets.
  `components/BaseWidget.tsx` hosts `ActionConfirmationModal`, which collects a
  mandatory explanation before the callback runs. Every "Submit / Run / Sync"
  control must go through `executeAction`: that confirmation *is* the audit
  trail, and the audit trail is the product.
- `hooks/useActionLogger.ts` — the `logAction` telemetry path.
- Emitter/receiver pattern: emitters call `props.data.setVariable(key, value)`,
  receivers read `props.data.variables?.key`. Emitters must seed their variable
  on mount, or receivers render with nothing on first load.

## Assistant panel

`components/AgentPanel.tsx` + `components/AgentConversation.tsx` render the chat;
`hooks/useAgentChat.ts` consumes the SSE stream and switches on frame `type`:
`chunk`, `reasoning`, `reclassify`, `final`, `tool_calls`, `trace_id`, `error`,
plus `pending_poll`. If you add a frame type on the backend, add the matching
case here — unknown types are silently dropped, which looks like a hang.

Requests go to the backend proxy, never to an agent service directly, so the
agent URL and credentials stay server-side. `hooks/useDashboardContext.ts`
assembles the hidden preamble (widget titles, descriptions, configs, user email
and roles, dashboard variables) that grounds the assistant in the current view —
which is why giving widgets clear names and descriptions measurably improves
answers.

## Layout of `src/`

```
api.ts                  Typed fetch helpers against /api
widgetRegistry.ts       Runtime widget loading + shared type contracts
App.tsx main.tsx        Router/providers and entry point
pages/                  Screens: WidgetStudio, AgentStudio, ActionLogs, Settings,
                        Help/About/UserGuide, AdminPage
pages/admin/            WidgetManager, ViewManager, RoleMappings, TaxonomyManager
components/             BaseWidget, WidgetPreview, WidgetTray, Layout, modals,
                        AgentPanel/AgentConversation, ThumbnailCapture
hooks/                  useAgentChat, useActionLogger, useDashboardContext, useScript
contexts/ store/        ActionContext, dashboardStore
```

Run `npm run lint` before finishing; `npm run build` type-checks via `tsc -b`
and is the real gate, since dev mode won't surface every type error.
