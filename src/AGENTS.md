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

## Widget Library (`components/WidgetTray.tsx`)

The bottom tray that lists every widget. Three things about attribution:

- **A card only names an author it believes in.** `creatorOf` rejects the values a
  failed identity lookup used to write (`unknown`, `dev`, and friends) and the card
  shows nothing rather than "by unknown". The backend leaves the same values off
  the leaderboard, so keep the two lists in step.
- **The leaderboard is a way in, not a scoreboard.** `CreatorLeaderboard` opens from
  the header and picking someone sets `creatorFilter`, which narrows the library to
  their widgets and shows a chip that clears it. That filter deliberately *replaces*
  the certified filter instead of stacking with it: asking for one person's widgets
  and seeing only their certified ones makes it look like they have fewer than they
  do.
- **Edit and Delete are two different rights, because the server applies two.**
  Edit asks `canEditDomain` (the store's copy of `require_domain_editor`, the only
  check `PUT /custom/{id}` makes); Delete asks `canManageWidget`, which is what
  `delete_custom_widget` checks — the author, or anyone at all if the recorded
  author was never a person. Never test `createdBy === currentUser`: that is what
  broke the library the day authorship started resolving correctly. Every widget
  already stamped `dev` or `unknown` suddenly matched nobody, which took away both
  buttons *and* hid the widget behind the certified filter, which used the same
  test. Both rules live next to `isPerson` in `creators.ts` and the store; if you
  change a permission on the server, change its twin here or the library will
  offer a button the save then refuses.
- **An uncredited widget invites a claim instead of showing a blank byline.** No
  widget built before the identity fix has a recoverable author (see
  `server/routes/custom_widgets.py::claim_custom_widget`), so where a name would go
  the card offers "Did you build this? Claim it" to anyone who could publish to
  that domain. It's the only route back to real attribution, and it's deliberately
  quiet — same size and colour as a byline, because most people should ignore it.

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
  mount-time data loads. That effect deliberately depends on `code` and
  `previewNonce` only. The auto-fix inside it reaches the current generate function
  and flags through `generateRef`/`isGeneratingRef`/`previewErrorRef`, because
  naming them as dependencies would recompile on every render — and reading
  `handleGenerate` directly reaches for a function declared below the effect.
- **Code is never replaced without a snapshot.** `replaceCode` is the only way
  anything programmatic (an agent turn, an import, a restore) writes the editor: it
  refuses empty text and pushes the outgoing code onto `checkpoints` first, which
  the History panel in the TSX Editor toolbar restores from. Typing gets one
  snapshot per burst rather than one per keystroke, so `onChange` goes through
  `handleCodeEdit`, not `setCode`. Call `setCode` directly only where there is
  genuinely nothing to preserve (initial load, Reset's blank template). History is
  capped by count and by bytes, and the session write falls back to saving without
  it if sessionStorage runs out of quota.
  Published versions in the same panel come from `/api/widgets/history` (metadata
  and per-version size) and `/api/widgets/version` (one version's code). Restoring
  loads code into the editor and nothing else — no settings, no publish.
- **How long to wait is the server's call, not ours.** `/generate` answers with
  `timeout_seconds` (the admin's `widget_timeout`) and the poll loop sizes itself
  from that plus a margin. It used to give up after a hardcoded five minutes, so
  raising the limit in Settings changed nothing and the studio declared a timeout
  while the server was still working. The spinner counts seconds for the same
  reason: a long generation with no clock on it reads as a hang.
- **A planned run reports itself step by step.** For a request that asks for
  several things the server answers with `stages` and, as each step lands,
  `stage_index` and `stage_code`. The poll loop applies each `stage_code` through
  `replaceCode` as it arrives, which is what puts one History entry per step in the
  panel and what keeps the finished steps if a later one fails. The spinner becomes
  a checklist, and `Stop after this step` `DELETE`s the job — the server finishes
  the step in flight and keeps what it has, so stopping is never destructive. Don't
  wait for `status: completed` to write the code; that was the old shape and it
  loses everything when a big request runs out of time. The completed handler only
  writes `result.code` when it differs from what's already in the editor, or a
  planned run would end with a duplicate snapshot.

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

Two rules about the conversation id, both learned from bugs:

- **`conversationIdRef` is what uploads and turns are addressed to, and it moves in
  the same tick as the change** (`adoptConversation`). While it was synced from an
  effect it trailed a commit, so a file attached in that window was posted against
  the conversation being navigated away from: it belonged to a chat the user was no
  longer in, and the chip that did appear was the newly-opened conversation's own
  file, which makes it look like the upload simply produced the wrong summary.
- **Engaging claims the conversation** (`engage`, called by `send` and
  `attachFiles`). The id minted at mount is otherwise never remembered — only
  `adoptConversation` writes it — so a user who attached a file or sent a turn while
  the restore was still in flight got the restore's *yield* (correct) but came back
  after a reload to the conversation the restore had declined to open, leaving the
  chat they had actually been working in behind.

Verifying this needs the upload id from the POST response: identical files on two
conversations are indistinguishable by name and size, and `localStorage` is not a
reliable read of which conversation the drawer is live on — the request body of the
next turn is.

## Model picker (`components/ModelSelect.tsx`)

A typeahead over `GET /api/settings/models`, used by Admin Panel → Settings and by
Agent Studio's per-agent model field (`variant="dark"` there). Three things it does
on purpose:

- **Free text still commits.** The list can miss an endpoint or fail to load, and
  this replaced a plain text input, so an unrecognized value is accepted with a
  warning rather than blocked.
- **Options commit on `onMouseDown`, not `onClick`.** Pressing down blurs the input,
  whose handler keeps the typed filter text and closes the list — so a click handler
  never runs and typing then clicking a suggestion silently discards the
  suggestion. `preventDefault` in the same handler stops the focus change too.
- **The typed text lives in a ref as well as state, and `commit` leaves focus in the
  field.** Blur is dispatched synchronously, so a `commit` that blurred the input ran
  the blur handler before `setQuery(null)` applied: it read the stale query and wrote
  the half-typed filter over the option just chosen. That was the "clicking a
  suggestion only keeps my letters" bug. The ref is the blur handler's source of
  truth, and nothing steals focus, which also keeps stray keystrokes from reaching
  the page behind.
- **Only the input's blur decides what happens to abandoned text.** The outside-click
  listener closes the list and nothing more; when both touched the query, whichever
  ran first won.
- **Typing highlights the best match, so Enter completes.** Exceptions: text equal to
  a model's `name` highlights that model, and text equal to a serving endpoint's own
  name highlights nothing so Enter keeps the endpoint rather than substituting the
  AI Gateway alias whose row it matched. With nothing matched, Enter commits the text
  as typed.
- **Enter is always swallowed** (`preventDefault` + `stopPropagation`). This control
  sits on pages with their own forms and key handlers, where an escaping Enter
  submits or navigates and reads as the whole screen resetting.
- **One fetch per page load**, cached at module scope, because the Settings page
  mounts three of these. The empty-list hint keys off `options`, not `rows`: where a
  blank row is offered it would otherwise hide both the loading and no-match
  messages.

`name` is the value stored (the `system.ai.…` AI Gateway alias for foundation
models) and `endpoint` is shown beneath it; the backend derives the request path
from which style you picked.

The endpoint line under each option is `slate-400` in the dark variant: `slate-500`
measures 3.75:1 there, under AA for text that small.

## Deployment settings (`pages/admin/SettingsManager.tsx`)

`draft` holds *effective* values, so the form shows what is in force and saving
records an override only for fields that were actually changed. Two consequences
worth keeping:

- **A load that lands late must not overwrite an edit.** `editedRef` records every
  field touched, and `apply` keeps those values; use the `edit` helper rather than
  `setDraft` directly when adding a field. StrictMode double-mounts in development,
  so two loads are in flight and the form is already interactive when the second
  returns — which used to reset whatever had been typed. This is the same problem
  as Widget Studio's `touchedSettingsRef` and `refreshConversations`' `listEditRef`.
- **Reload discards edits on purpose** (`load(true)`), since asking for the stored
  values and then not being shown them is worse. Note the button passes the flag
  explicitly: wiring it as `onClick={load}` hands React's event object to the first
  parameter, which is truthy.

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

**What belongs in the answer and what belongs in the thinking box.** `chunk` text
streams straight into the answer, so what is on screen is what the agent is
actually saying. The disclosure holds thinking only: `reasoning` frames, and prose
the agent abandoned mid-sentence to call a tool, which the runtime hands back as
`reclassify` so the client can lift it out of the answer. Rendering streamed
content in *both* places is what produced the complaint that "thinking" was just
the answer in grey — the same words arriving greyed out and then again as the
answer. A turn can reclassify several times, so the runs are kept apart.

Requests go to the backend proxy, never to an agent service directly, so the
agent URL and credentials stay server-side. `hooks/useDashboardContext.ts`
assembles the hidden preamble (widget titles, descriptions, configs, user email
and roles, dashboard variables) that grounds the assistant in the current view —
which is why giving widgets clear names and descriptions measurably improves
answers.

### Conversations and attachments

The transcript is **server-owned**. The hook sends a `conversation_id` and the
backend writes both turns and replays history from Postgres, so the client no
longer builds a `conversation_history` array except in draft mode — where nothing
is persisted. That split is what `persists` (true unless `inlineProfile` is set)
governs throughout the hook: history, uploads, and the history list are all off in
Agent Studio's "Try it" tab.

Things worth knowing before changing this:

- **Conversation ids are generated client-side** so files can be attached and the
  panel can render before the first turn exists. The server may write to a
  different id if the one sent belongs to another user, and returns the truth in
  the `X-Conversation-Id` response header — follow it. `localStorage` holds only
  which conversation to reopen, never the messages.
- **The restore-on-mount effect is deliberately not cancellable.** It is guarded by
  `restoredRef` so it runs once; adding a `cancelled` flag in the cleanup breaks it
  outright, because StrictMode's throwaway first cleanup then abandons the only
  attempt the ref will allow and the drawer sits on the greeting forever. It asks
  for the remembered conversation and the list *in parallel* — sequentially is two
  round trips before anything appears, seconds against a remote database — and only
  falls back to the most recent conversation if the remembered one is gone. Because
  it takes that long, `isRestoring` drives a line in the transcript, and
  `engagedRef` (set by `send`, `attachFiles`, `startConversation`, or picking from
  history) makes a late restore yield: whatever the user started wins.
- **Local edits to the conversation list outrank an in-flight read.** Opening the
  history dropdown starts a list fetch; a rename committed while it is in flight
  would be overwritten when it lands. `listEditRef` counts local edits and
  `refreshConversations` drops a response that a newer edit has superseded.
- **Switching agents starts a new conversation** rather than stashing transcripts
  in a ref, which is what the old per-profile `historyRef` did. Restoring a
  conversation adopts the agent it was held with, and sets `prevProfileIdRef`
  alongside `selectedProfileId` so the agent-switch effect doesn't see a switch and
  immediately wipe what was just restored. If you touch that effect, check this.
- **Uploads are polled, not awaited.** `POST /api/agent/uploads` returns
  immediately with `status: "parsing"` and the chip fills in from
  `GET /api/agent/uploads/{id}`; parsing a large workbook takes seconds.
  `sentAttachmentsRef` tracks which files already appeared on a message so a file
  chips onto one turn rather than every later one — the agent can still query every
  file on the conversation, so this is presentation only.
- `components/ConversationHistory.tsx` is the header dropdown (list, rename,
  delete). It reads the list on open rather than subscribing, since it only changes
  when a turn completes or the user acts there. Postgres timestamps arrive without
  a zone and are UTC, so `relativeTime` appends `Z` before parsing — drop that and
  every conversation looks hours old.

### Agents pinned to a view

A view can name the agent the drawer opens with (`Tab.pinned_agent_id`, stored on
the view row). The pin button beside the picker writes whatever is selected to the
active view, through the same full-view PUT as renaming or locking it, so
`canEditView` — not the layout lock — decides who may set one. `DEFAULT_AGENT_PIN`
(`'default'`) is how a view pins the *built-in* agent; without it, "pinned to the
default agent" and "not pinned" would be the same empty string.

The pin is a default, not a lock, and the effect that applies it is fussier than
it looks:

- **It fires once per view activation** (`appliedPinRef`), so choosing a different
  agent while you are on the view sticks. Leaving and coming back re-applies it.
- **It defers to a reopened conversation on the first view it sees**
  (`reopenedRef`). Applying the pin means starting a new conversation, so without
  this every reload of a pinned view would file the chat you were reading into
  history and greet you with an empty one.
- **It skips while a turn is streaming** and lands on the next render instead.
- **It ignores a pin naming an agent that isn't in `availableProfiles`** once that
  list has loaded, because the runtime silently answers as the default agent when
  it cannot resolve a `profile_ref` — the picker would claim an agent nobody could
  open. The panel says so instead. The list is lazy, so an empty list means "not
  known yet", not "no access".

Setting `selectedProfileId` from that effect deliberately cascades into the
agent-switch effect above: the pin does exactly what a click on the picker does.

## Layout of `src/`

```
api.ts                  Typed fetch helpers against /api
widgetRegistry.ts       Runtime widget loading + shared type contracts
App.tsx main.tsx        Router/providers and entry point
pages/                  Screens: WidgetStudio, AgentStudio, ActionLogs, Settings,
                        Help/About/UserGuide, AdminPage
pages/admin/            WidgetManager, ViewManager, RoleMappings, TaxonomyManager,
                        SettingsManager
components/             BaseWidget, WidgetPreview, WidgetTray, Layout, modals,
                        AgentPanel/AgentConversation, ConversationHistory,
                        ThumbnailCapture
hooks/                  useAgentChat, useActionLogger, useDashboardContext, useScript
contexts/ store/        ActionContext, dashboardStore
```

Run `npm run lint` before finishing; `npm run build` type-checks via `tsc -b`
and is the real gate, since dev mode won't surface every type error.
