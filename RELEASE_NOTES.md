<!--
  User-facing release notes, rendered verbatim in the app under
  Resources → Release Notes (src/pages/ReleaseNotesPage.tsx imports this file).

  Conventions:
    * Newest release first. Add a new `## <version> — <YYYY-MM-DD>` block on top.
    * Write for the people using the app, not for reviewers. "Widget Studio has a
      Reload button" — not "added previewNonce state".
    * Group bullets under Added / Changed / Fixed. Omit groups you don't need.
    * Ship the notes in the same commit as the change. Nobody backfills these.
  This comment is an HTML comment, so it never renders in the app.
-->

# Release Notes

## 1.5.0 — 2026-07-30

### Added

- **Attach files to the assistant.** Use the paperclip in the assistant panel, or
  drag a file onto it, and ask questions about it. Spreadsheets and CSVs (up to
  25 MB), PDFs, Word documents, JSON, text and images are all supported, five
  files per conversation.
  Large files stay fast because the assistant is not given the whole file: it sees
  a summary — sheets, columns, row counts, a few sample rows — and queries the rest
  on demand, so a 5,000-row export answers as quickly as a small one and the
  numbers come from every row rather than a sample. For per-row maths like revenue
  from units and unit price, it computes the column first and then totals it.
  Documents are searched rather than skimmed, and answers cite the page. Images
  and short PDFs are read directly by the model, so charts, screenshots and
  scanned pages work too.
- **Conversations are saved.** The assistant panel keeps your conversations, so
  reloading the browser or coming back later picks up where you left off. The
  clock icon in the panel header lists your recent conversations — click one to
  reopen it, rename it with the pencil, or delete it with the trash. The
  speech-bubble icon starts a new conversation; the previous one is kept, not
  discarded. Your 50 most recent are retained, and they are private to you.
  While the last conversation is being reopened the panel says so, and if you
  start typing before it lands, what you started wins.

### Fixed

- **The assistant remembers its own answers.** Follow-up questions like "and what
  about last month?" now work: previous replies were being dropped from the
  conversation before the assistant saw them, so it only had your side of the
  discussion to work from. Asked about a figure it gave earlier, it no longer
  second-guesses whether it really looked it up.
- **Admin Panel → Settings keeps what you type.** Editing a field just as the page
  finished loading could silently snap it back to the stored value. The Reload
  button still discards edits, since that is what it is for.
- **"Thinking" is thinking again.** The assistant's answer used to arrive greyed
  out under "Thinking…" and then repeat itself as the answer, so you read it twice.
  Answers now stream where they belong, and the collapsible box keeps only genuine
  thinking: reasoning, and the notes it abandons mid-sentence when it decides to go
  look something up. Turns that never pause to think no longer show the box at all.
- **Attaching a file the moment the assistant panel opens now works.** While your
  last conversation was still being reopened, a file attached in that first second
  went to the conversation being left behind — and the chip that appeared belonged
  to the conversation being opened, so it looked as though the wrong file had been
  read. Starting a new chat in that same moment could also be undone. Whatever you
  do in that window now wins, and reloading returns you to the conversation you were
  actually working in.

### Changed

- **Pages load several times faster.** The app was reconnecting to its database,
  re-checking who you are, and rebuilding its Databricks connection on every single
  request, which cost far more than the work being done. All three are now reused,
  and requests that used to wait their turn run at the same time. Measured locally,
  a screen that fires nine of these calls went from 8.4 seconds to 0.3; opening a
  saved conversation, loading a dashboard's views, and the Admin Panel's tabs all
  benefit, and nothing about how the app behaves has changed. Permission and group
  changes can take up to five minutes to take effect, which is the one trade-off.
- **Switching agents starts a new conversation** instead of swapping transcripts
  in place. The one you were in is saved, and one click away in the history list.

## 1.4.0 — 2026-07-29

### Added

- **Model settings in the Admin Panel.** A new **Settings** tab lets global admins
  choose which model powers the assistant, which one writes widget code in Widget
  Studio, and which one drafts agents in Agent Studio — picked from a searchable
  list of the models your workspace actually offers, rather than typed by hand or
  set at deployment time. The chat agent's tool-call and response-length limits
  live there too. Changes take effect on new conversations, no redeploy needed.
- **Reload button in Widget Studio.** Re-runs the widget you're editing —
  recompiles and remounts it — so anything that only happens when a widget first
  loads (data fetches, initial render) can be repeated without changing the code.
- **Release notes in the app.** This page, under Resources in the sidebar.
  Newest release at the top.
- **Syntax highlighting and line numbers in the code editors.** The Widget Studio
  TSX editor, the SQL query box on the Configuration tab, and the Python tool
  editor in Agent Studio now colour code and number every line. Tab indents
  instead of jumping out of the box, and pressing Enter keeps your indentation.
- **The assistant can answer questions about the Command Center itself.** Ask it
  what a widget is, why you cannot see a domain's global views, how to get a
  widget into production, or how to share a view, and it answers from the app's
  own documentation instead of guessing. This applies to every agent, including
  ones authored in Agent Studio.
- **The Widget Studio agent now fills in the Configuration tab for you.** After
  it generates a widget it proposes a name, description, category, domain, and
  default size. Anything you have already typed or picked is left alone.

### Changed

- **The browser tab now says "Command Center".** It used to say "client".
  Non-production deployments are labelled with their environment — "Command
  Center - Dev" — so you can tell several open windows apart.
- **The assistant can give longer answers.** The response ceiling went from 4,000
  to 16,000 tokens, so detailed answers no longer stop mid-sentence. It is only a
  ceiling — short answers stay short — and models that allow less are adjusted to
  their own limit automatically. Admins can change it in Admin → Settings.
- **Picking a model for a saved agent is now a searchable list.** Agent Studio's
  Model field used to be free text where a typo surfaced later as a failed chat.
  It now suggests the models available in your workspace, and leaving it blank
  follows the deployment default set in Admin → Settings. Type to filter, then
  click a suggestion or press Enter to take the highlighted one; an endpoint the
  list doesn't know is still accepted as typed, with a warning under the field.
- **The Widget Studio agent now edits code in place instead of rewriting it.**
  When you ask for a change to an existing widget, it sends just the lines it
  wants to replace rather than re-emitting the whole component. Complicated
  widgets no longer fail part-way through with truncated code. Long widgets
  generated from scratch are continued automatically if they don't fit in one
  response.

### Fixed

- **Categories and domains no longer come up empty.** The pickers in Widget
  Studio and the taxonomy admin screens used to show nothing at all when the
  database read failed, which was indistinguishable from someone having deleted
  them. Failures now say so and offer a retry.
- **Faster, more reliable page loads.** Database credentials are reused for a
  short window instead of being re-minted on every single API call, which
  removes several Databricks control-plane round trips per request.

---

Releases before this page existed are in the git history.
