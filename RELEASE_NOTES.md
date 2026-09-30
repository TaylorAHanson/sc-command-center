<!--
  User-facing release notes, rendered verbatim in the app under
  Resources → Release Notes (src/pages/ReleaseNotesPage.tsx imports this file).

  Conventions:
    * Newest release first. Add a new `## <version> — <YYYY-MM-DD>` block on top.
    * Group bullets under Added / Changed / Fixed. Omit groups you don't need.
    * Ship the notes in the same commit as the change. Nobody backfills these.
    * Write for the people using the app, not for reviewers. "Widget Studio has a
      Reload button" — not "added previewNonce state".
    * One bullet per user-visible change. Merge bullets about the same thing.
    * Each bullet is a bold lead naming the change, then at most one short
      sentence (~25 words in total). Say what someone can now do and where
      (menu path, button name) — not why it changed or how it was built.
    * No root causes, internal names, file or function names, or before/after
      narratives. Add a second sentence only when the reader must act.
    * Aim for a release that fits on one screen.
    * Example: - **Stop the agent.** A Stop button replaces Send while the
      assistant is working.
  This comment is an HTML comment, so it never renders in the app.
-->

# Release Notes

## 1.13.0 — 2026-09-30

### Added

- **Widget Studio watches the widget run.** Failed queries and errors in agent-written code are fixed automatically, and the review sees a screenshot of the preview.
- **Problems panel in Widget Studio.** Under the preview and code, it lists rule checks and what the widget did when it ran; **Fix with agent** sends them.
- **The agent sees real rows.** **Test & Extract Schema** now shows a few sample rows and real column types, and the agent is given both.

### Changed

- **Data source tests run as you.** SQL and Databricks API tests use your own permissions; a statement that changes data is not run.
- **External APIs are tested from your browser,** the same way the widget will call them.
- **Faster quick checks in Widget Studio.** The helper model now defaults to `system.ai.gpt-6-luna`; change it under Admin Panel → Settings.
- **Widget Studio acts on your request as you wrote it.** It's no longer reworded by a smaller model first, which could change what you asked for, and each turn starts a couple of seconds sooner.
- **Planned widget steps can look at your data.** Each step of a large request can check tables and run its own SQL before writing code.

### Fixed

- **Stop and progress in Widget Studio are reliable.** Stopping a generation always takes effect, and progress no longer stalls between updates.
- **Agent Studio keeps working when you change its model.** A draft no longer fails because the new model refuses a setting; the setting is dropped and the draft carries on.

## 1.12.1 — 2026-09-29

### Changed

- **No more confirmation popup on widget actions.** Submit, Run and Sync buttons act immediately; each action is still recorded in **Action Logs**.
- **Simpler About page.** Company details and the copyright line were removed.

## 1.12.0 — 2026-09-29

### Added

- **Promote from Widget Studio.** **Promote** in the studio header moves the widget Dev → Test → Prod, rolls back, and certifies, without visiting the Admin Panel.
- **Stop the agent.** A red Stop button replaces Send while the assistant, Widget Studio or Agent Studio is working; pressing Enter never stops it.
- **Charts in the assistant.** The assistant and Agent Studio agents can draw charts in the chat from the data they retrieved, and export them as PNG or SVG.

### Changed

- **Studio buttons are grouped by what they act on.** Only chat controls sit above the chat; Save, Import, Export, Promote and close are on the right with the widget or agent.
- **Agent Studio shows unsaved changes.** New agent and Open ask before discarding them; **Save** confirms inline; **Delete agent** moved to the Settings tab.
- **Agent Studio's New is two buttons.** **New conversation** above the chat keeps your draft; **New agent** on the right starts over.
- **Chat only shows this app's own images.** An image from another site appears as a placeholder, so an answer can't send your data elsewhere by displaying one.
- **Shorter release notes.** Earlier entries on this page were condensed.

### Fixed

- **Widget Promotion shows each environment's current version,** not its oldest, and Preview shows the code again.
- **Promoting after a rollback no longer fails,** and a Test version with the same number as Dev's is no longer mistaken for the same widget.
- **View Promotion no longer skips a view as "Already up to date"** just because the target has a version with the same number; it now copies whenever the layout differs.
- **Widget version history respects domain access.** Reading a widget's past versions or code now needs access to its domain in that environment.

## 1.11.1 — 2026-09-24

### Fixed

- **Genie answers no longer go missing in the studios.** Widget Studio and Agent Studio pick up slow Genie answers instead of reporting "did not finish", with a link to open them in Databricks.

## 1.11.0 — 2026-09-24

### Added

- **Move everything to another app.** Admin Panel → **Data Migration** (global admins) exports widgets, views, agents and settings, and imports another app's snapshot. **Preview** first; **Merge** adds what's missing, **Replace** makes an exact copy.
- **Widget Studio can look at your data.** Before writing a widget it can run read-only SQL and ask Genie, as you; lookups show under **Thinking**.
- **Agent Studio researches while it drafts.** It can run read-only SQL and ask Genie, so drafted prompts describe your real data.

### Changed

- **Role mappings pick real groups and domains.** Admin Panel → Role Mappings searches Databricks groups as you type, rejects names nobody holds (including wrong capitals), and flags deleted domains.
- **Create Global View lists your real domains** — the ones you can edit.
- **Categories & Domains catch near-duplicates.** Adding `logistics` when `Logistics` exists is refused.
- **Settings flags broken JSON as you type** in the model-parameter overrides box.
- **The Genie and SQL switches cover the studios.** In Admin Panel → Settings they also turn off Widget Studio and Agent Studio research.

## 1.10.1 — 2026-08-24

### Added

- **Action Logs show who acted.** A searchable **User** column; actions from before this release show a dash.
- **Every approved action gets a request ID.** It shows in the expanded Action Logs row, is searchable, and matches the statement in Databricks query history.
- **Delete all my conversations.** At the bottom of the clock-icon history list; removes every conversation and attachment you own, permanently.
- **Admins can limit what the assistant reaches.** Admin Panel → Settings can switch off Genie, SQL, sending images and PDFs to the model, and sharing what's on screen.
- **Conversation retention.** *Delete conversations after (days)* in Admin Panel → Settings removes untouched chats; the default, 0, keeps them.
- **The assistant says what it is.** A line under the message box notes that answers can be wrong and conversations are saved.

### Changed

- **Widgets load scripts only from approved CDNs** (jsDelivr, code.highcharts.com, unpkg, cdnjs). A widget loading from anywhere else now shows an error; repoint it at jsDelivr.
- **Saving a widget checks its code.** Unsafe calls such as `eval` or `innerHTML`, and addresses other than the app's `/api/` paths and approved CDNs, are refused with the reason.
- **Widgets whose SQL changes data must be marked Executable.** Saving is refused until the toggle is on, so every change goes through the confirmation prompt.
- **The read-only query endpoint is read-only.** `/api/sql/execute-raw` refuses statements that change data; writes go to `/api/sql/execute-write`, which Widget Studio now uses.
- **The browser limits where widgets can send data** — only this app and the approved CDNs. If a widget stops rendering, admins can turn on report-only mode in Admin Panel → Settings.
- **Role and permission checks are on by default.** The demo switch that made every signed-in user a global admin now defaults to off; see the notes below.
- **The API documentation is no longer public.** `/api/docs`, `/api/redoc` and `/api/openapi.json` are served only in local and dev.

### Notes for administrators

- **Check your role mappings before deploying.** A deployment that never created a mapping still grants the `users` group global admin; replace it with your admin group in Admin Panel → Access Management.
- **Agent Studio Python tools run on the server.** Grant authoring rights only to people with secure-development training, and review a tool before giving its agent domain or global visibility.

### Fixed

- **Approved actions never run without an audit record.** If the log can't be saved, the confirmation stays open and nothing executes.
- **Certified-only global views check the latest widget version.** Widgets certified only on an older version, and unregistered custom widgets, are blocked.

## 1.10.0 — 2026-08-24

### Added

- **See Widget Studio's thinking.** Expand **Thinking** for how the agent read your request, its plan, the files it opened and anything it skipped.
- **Send a screenshot of your widget.** **Send screenshot to agent**, under the preview, attaches the widget as it looks to your next message.
- **Attach files in Widget Studio.** The paperclip beside the message box takes spreadsheets, documents and images.
- **Agent settings, on the sliders icon above the chat.** *Conduct review after change* (off) has the agent check and fix new code; *Ask before large builds* (on) lets it ask first.
- **Reviews suggest improvements, briefly.** A review lists only what it would change, then up to three **Worth considering** ideas the agent won't build unless asked.
- **Review suggestions are buttons.** Each chip in the **Do next** row writes its suggestion into the message box without sending.
- **The agent asks before large, vague builds.** It may ask up to three questions; answer them or press **Build it anyway**.
- **A helper model for small jobs.** Global admins can set a **Widget helper model** in Admin Panel → Settings; blank uses the widget generation model.

### Changed

- **Update is now Save, and keeps you in the studio.** Press **Done** when you've finished.
- **Widgets are built for the size of their data.** Testing a SQL source counts its rows; large tables are paged and totalled in SQL, not the browser.
- **Long Widget Studio conversations stay usable.** Older turns are summarised.

### Fixed

- **Bad edits no longer fill widgets with `=======` lines.** A widget already damaged this way repairs itself on your next request.
- **Edits land where they were meant to**, not on the first of several matching lines.
- **The message box resizes to fit its text**, including clicked suggestions and restored drafts, and scrolls at full height.
- **A fixed widget shows as fixed.** The "Render Failed" panel clears once repaired code is ready, and **Try Again** works.
- **Highcharts Maps and other modules load**, including exporting, treemap and heatmap.
- **Repeating render crashes stop after three auto-fix attempts.**
- **No stray widget-clarify marker** after the agent's clarifying questions.
- **Render errors are no longer called compilation errors** in auto-fix messages.

## 1.9.0 — 2026-08-11

### Added

- **Pin an agent to a view.** Press the pin beside an agent in the assistant panel and the view opens with it; shared views too, if you can edit them.
- **Claim a widget you built.** Widgets with no recorded creator offer "Did you build this? Claim it", crediting you on the card and Top creators board.

### Changed

- **Edit any widget in a domain you edit.** The Edit button now shows on colleagues' widgets; deleting is still the creator's.

### Fixed

- **Widget Studio explains itself again** on the newest models, and each plan step says what it did.
- **Big requests finish sooner**, planned in fewer, larger steps around what you asked for.
- **Edits no longer fail with a message about a "list".**
- **Failed queries give a one-line reason** instead of a developer error report.
- **Agent Studio works on Claude Opus 5** — no more "INVALID_PARAMETER_VALUE ... Content in ChatMessage".
- **The app starts much faster and no longer freezes.** A 30-widget test library went from 17 seconds to 1.5.
- **A slow network no longer empties the Widget Library.** The page waits, and says so if widgets can't load.
- **Older widgets can be edited again.** Widgets from before authorship worked belong to nobody, so anyone can edit or delete them.

## 1.8.0 — 2026-08-11

### Added

- **See who built each widget.** Widget Library cards credit their creator; click a name to see everything they've built.
- **A Top creators board.** A Widget Library header button ranks creators by published widgets, usage and placement; using your own doesn't count.

### Fixed

- **Your name is recorded on what you create**, instead of "dev" or "unknown". Widgets published earlier keep their old stamp.
- **Widgets with placeholder owners can be deleted again**, by anyone; your own stay yours whatever your email's capitalisation.
- **Long Widget Studio requests keep to their time limit**, and planning can no longer use up the whole allowance.
- **A failed SQL query says why in the widget**, so you and Widget Studio's auto-fix can act on it.
- **Model parameter overrides accept tuning parameters only**, and name any they refuse.

## 1.7.0 — 2026-08-10

### Added

- **Widget Studio builds big requests in steps.** Each step lands in the editor and History as it finishes; **Stop after this step** ends early.
- **Timeouts and limits are settings.** Admin Panel → Settings controls chat and studio limits, including Widget Studio's timeout; work already applied is kept if time runs out.

### Fixed

- **Changing the model no longer breaks Widget Studio.** Name any extra parameters a model needs under **Model parameter overrides** in Settings.
- **Queries on columns with spaces work.** The agents now quote names like `Ship Date` in backticks.
- **A failed query says so** instead of showing an empty widget, and Widget Studio fixes it on retry.

## 1.6.0 — 2026-08-04

### Added

- **History in Widget Studio.** **History**, next to Reload, lists every agent turn, import, Reset, your edits and published versions; **Restore** loads one without publishing.

### Fixed

- **Asking for a change no longer erases the rest of your widget.** You no longer need to ask the agent to "merge" changes.

## 1.5.0 — 2026-07-30

### Added

- **Attach files to the assistant.** Use the paperclip or drag a file in: spreadsheets up to 25 MB, PDFs, Word, JSON, text and images, five per conversation.
- **Conversations are saved.** The clock icon lists your 50 most recent to reopen, rename or delete; the speech-bubble icon starts a new one.

### Fixed

- **The assistant remembers its own answers**, so follow-up questions work.
- **Admin Panel → Settings keeps what you type** while the page finishes loading.
- **"Thinking" holds only thinking.** Answers no longer appear twice.
- **Attaching a file or starting a chat as the panel opens** lands in the right conversation.

### Changed

- **Pages load several times faster.** Permission and group changes can take up to five minutes to apply.
- **Switching agents starts a new conversation.** The previous one stays in the history list.

## 1.4.0 — 2026-07-29

### Added

- **Model settings in the Admin Panel.** Global admins pick the assistant, Widget Studio and Agent Studio models, and chat limits, under **Settings** — no redeploy.
- **Reload button in Widget Studio.** Re-runs the widget without changing its code.
- **Release notes in the app**, under Resources in the sidebar.
- **Syntax highlighting and line numbers** in the Widget Studio, SQL and Agent Studio Python editors; Tab indents.
- **Ask the assistant about the Command Center.** Every agent answers questions about the app from its documentation.
- **Widget Studio fills in the Configuration tab**, proposing name, description, category, domain and size without overwriting yours.

### Changed

- **The browser tab says "Command Center"**, plus the environment outside prod, e.g. "Command Center - Dev".
- **Longer assistant answers.** The ceiling rose from 4,000 to 16,000 tokens; admins can change it in Admin → Settings.
- **Agent Studio's Model field is a searchable list** of your workspace's models; blank uses the deployment default.
- **Widget Studio edits code in place**, so complex widgets no longer fail with truncated code.

### Fixed

- **Categories and domains no longer come up empty** when loading fails; you get an error and a retry.
- **Faster, more reliable page loads.**

---

Releases before this page existed are in the git history.
