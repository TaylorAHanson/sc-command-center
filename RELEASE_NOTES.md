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

## 1.10.0 — 2026-08-21

### Added

- **Widget Studio shows you what it's thinking.** Expand **Thinking** while the
  agent works and you can see how it read your request, the steps it planned, the
  files it opened, and anything it gave up on because it ran short of time. It
  stays with the answer afterwards, so a widget that came out wrong can be traced
  back to the assumption that caused it instead of guessed at.
- **Send the agent a screenshot of your widget.** Under the preview there's a
  **Send screenshot to agent** button that attaches a picture of the widget
  exactly as it looks — at the size you dragged it to — to your next message. It
  doesn't send on its own, so "this column is too narrow and the total is in the
  wrong place" arrives alongside the thing it's describing. Describing a layout
  problem in words was the slowest part of getting one fixed.
- **Attach files in Widget Studio.** The paperclip beside the message box takes
  spreadsheets, documents and images — a sample export, a design someone sent
  you, a screenshot of the report you're replacing — and the agent reads them the
  same way the assistant does.
- **Agent settings, on the sliders icon above the chat.** Two options, remembered
  in your browser rather than set for everyone. *Conduct review after change* is
  off unless you ask for it: once new code compiles, the agent reads it back —
  does it do everything you asked, does it handle loading, empty and error states,
  does it hold up squashed narrow and stretched wide, is every text colour dark
  enough to read — and fixes what it finds. It costs an extra turn, which is why
  it isn't on by default. *Ask before large builds* is the questions behaviour
  below, and is on; turn it off if you would rather it always guessed.
- **The review says what would make the widget better, not just what's broken.**
  It now finishes with **Worth considering**: up to three changes judged the way
  the person living with the widget would judge it rather than against the words
  of your request — the sort order a table of unranked rows is missing, the
  comparison a number without a reference point can't support, the click that
  should follow what it just drew your attention to. A widget can pass every
  correctness check and still stop one step short of being useful, and that gap
  is invisible to a review that only asks "did it do what was asked". These are
  suggestions and nothing else: the agent is not allowed to build them, so the
  setting can stay on without your widget quietly growing features you didn't ask
  for. The other half of the review got shorter at the same time — it lists what
  it would change and stops, instead of walking you through each thing it checked
  and found to be fine, which read as work done rather than anything you could
  act on.
- **Everything the review suggests is a button.** Under the findings there's a
  **Do next** row: one chip per suggestion, plus an amber one for anything it
  spotted but didn't fix. Clicking a chip writes the instruction into the message
  box — it doesn't send, so you can add "…and default to spend descending" before
  you commit a minute of generation to it. A review that ends in three good ideas
  you then have to retype is a review that mostly gets skimmed.
- **The agent asks before it spends ten minutes building the wrong thing.** On a
  large or vague request it can come back with up to three questions instead of
  code — which measure, which grouping, what a click should do — and you answer
  the ones that matter or press **Build it anyway** to have it choose sensible
  defaults. Small requests are never interrupted: a one-line change is quicker to
  make and correct than to ask about.
- **A helper model for the studio's small jobs.** Global admins can set a **Widget
  helper model** in Admin Panel → Settings, and a small fast model is the right
  choice. It tightens up a vague request before the expensive call sees it,
  summarises a long conversation so it stays affordable, and decides whether a
  question is worth asking. Leave it blank and the widget generation model does
  those too, as before.

### Changed

- **Save keeps you in the studio.** The **Update** button is now **Save**, and it
  no longer closes the studio and drops you back on your dashboard — people save
  every few minutes while they work, and every save meant navigating back and
  finding your place again. A line at the top of the chat confirms the save and
  clears itself. Use **Done** when you've actually finished with the widget.
- **The agent knows how much data it's dealing with.** Testing a SQL data source
  now counts the rows it returns, and that number changes what gets built. A few
  thousand rows are fetched once and sorted, filtered and paged in the browser. A
  large table gets all of that pushed into SQL, so the widget holds one page at a
  time and asks the warehouse for totals rather than adding up what it happens to
  have. Widgets that fetched a 40,000-row table a page at a time and then worked
  on it in the browser were slow to load, slow to use, and wrong whenever they
  summed a page and called it a total. An untested source is treated as large.
- **Long Widget Studio conversations stay usable.** A conversation that went on
  for a while was replaying its recent turns in full on every request, which is a
  lot of text once the agent has been explaining itself for twenty minutes. Older
  turns are now summarised down to what still constrains the widget, so the
  request that matters gets the room.

### Fixed

- **A bad edit can no longer wreck your widget with `=======` lines.** If the
  agent slipped while writing an edit — it would say so, something like "I
  accidentally left a duplicate marker" — the stray marker was written into your
  code, which then couldn't compile. Each automatic fix-up attempt was editing a
  file that was itself part marker, so a small change could spiral into a widget
  full of `=======` and duplicated lines. Those edits are now refused before
  anything is written, your code is left as it was, and the agent is told exactly
  what to send instead. A widget already damaged this way repairs itself the next
  time you ask the agent for anything: it recognises the leftover markers and
  rewrites the file cleanly.
- **Edits land where they were meant to.** When the text the agent searched for
  appeared in several places — a lone `);`, a repeated `}, []);` — the change was
  applied to the first one, which was usually not the one it had in mind, so you
  got a widget that was subtly wrong rather than an error you could see. An
  ambiguous edit is now refused and re-requested with enough context to place it.
- **The message box is the right size for what's in it.** It grew as you typed
  but nowhere else, so text that arrived any other way — clicking a suggestion,
  reopening a studio session you'd left mid-sentence — sat in a one-line box with
  the rest of it clipped out of sight, and sending a long prompt with the Send
  button left an empty box still several lines tall. It now sizes itself whenever
  its contents change, and scrolls once it reaches full height rather than hiding
  the overflow.
- **A fixed widget actually shows up as fixed.** When a widget crashed while
  rendering, the red "Build Succeeded, Render Failed" panel stayed on screen even
  after the agent repaired the code and the repair compiled — so a fix that worked
  was indistinguishable from a request the agent had ignored, and the only way out
  was Reload. The panel now clears itself the moment new code is ready, and its
  **Try Again** button re-runs the widget properly instead of leaving the preview
  stuck on "Evaluating Component…" forever.
- **Maps and other Highcharts modules work.** Anything that plugs into a library
  rather than being one — Highcharts Maps, exporting, treemap, heatmap — silently
  failed to load, and the widget died on `Highcharts.mapChart is not a function`
  however clearly you asked for a map. The library loader decided whether to fetch
  a file by looking for the library's name on the page rather than at the file
  itself, and since Highcharts is always present, a module was reported as loaded
  without ever being downloaded. It now goes by the file, and files load in the
  order a widget asks for them, so a module always runs after the library it
  extends.
- **A crash that repeats no longer re-generates forever.** Auto-fixing a render
  error had no attempt limit — each fix compiled, which reset the counter meant to
  stop it — so a widget that threw on every render could keep calling the model.
  It now gets the same three attempts a compile error gets.
- **Widget Studio stops showing you a stray `<!-- widget-clarify -->`.** An
  internal marker on the agent's clarifying questions was being printed at the end
  of the message instead of staying invisible.
- **A render error is described as one.** Auto-fix messages called every failure a
  "compilation error", including crashes in code that compiled perfectly well —
  misleading to read, and it sent the agent looking at syntax rather than at what
  runs on mount.

## 1.9.0 — 2026-08-11

### Added

- **A view can open with the agent that suits it.** Pick an agent in the assistant
  panel and press the pin beside it, and that view will open with that agent from
  then on — your own views, and the shared ones if you can edit them, so a team
  board can ship with the agent that knows it. It's a starting point rather than a
  restriction: you can still switch agents while you're there, and the pin comes
  back the next time you open the view. Press the pin again to remove it.
  Reloading the page keeps you in the conversation you were reading rather than
  replacing it. If a view is pinned to an agent you can't open, the panel says so
  instead of leaving you wondering which agent is answering.
- **You can claim a widget you built.** Widgets made before the app could tell who
  was signed in have nobody's name on them, and there's no record anywhere of who
  wrote them. Where the creator's name would be, those cards now ask "Did you build
  this? Claim it" — say yes and the credit is yours, on the card and on the Top
  creators board. Only widgets with no creator can be claimed, and only by someone
  who could publish to that domain, so nobody can take your work off you.

### Changed

- **You can edit any widget in a domain you're an editor of.** Saving a widget has
  always only asked whether you can edit its domain, but the library was hiding the
  Edit button on anything you hadn't written yourself, which sent you the long way
  round for a colleague's typo. The button now matches what the save allows.
  Deleting still belongs to whoever built it.

### Fixed

- **Widget Studio explains itself again.** On the newest models it had gone quiet:
  a request came back as code with nothing said about it, and a large request that
  was broken into steps ticked every step off under the heading "Worked through 6
  of 6 steps" without saying what any of them did. These models do their thinking
  privately, and the app never sees it, so the running commentary that used to
  come with an answer simply stopped arriving. The studio now asks for it as part
  of the answer, and a step that still says nothing is listed with what it was
  asked to do rather than a blank line. The checklist ticking along is how you can
  tell it's working rather than stuck.
- **Big requests are broken into fewer, larger steps, so they finish sooner.** The
  plan was counting the work it had to do rather than the things you'd asked for:
  "add a search box and a row count" became four steps, and one dashboard turned
  into six with "polish and responsiveness" tacked on the end. Each step is its own
  round trip, and on the current models that's another half a minute of waiting for
  something you never asked for. A request is now planned around what you actually
  asked for: the same dashboard builds in three or four steps and finishes in under
  a minute rather than the two to three it was taking, and small requests that used
  to be split up are simply done.
- **A widget the agent was editing could fail with a message about a "list".**
  Only when its first attempt at an edit didn't fit the file, which is why it came
  and went: the retry that would have fixed it crashed instead, and the turn was
  lost. The same cause could put stray punctuation into a widget mid-generation.
- **Widgets show why a query failed instead of a page of Python.** A query that
  the warehouse never got to run — a warehouse still starting up, an expired
  login, a table you don't have access to — filled the panel with an error report
  meant for developers, under a message implying the app itself had fallen over.
  You now get the reason in a sentence, and a widget can tell the difference
  between "try again in a moment" and "this query is wrong".
- **Agent Studio works on Claude Opus 5.** Every prompt came back as "Generation
  Error: INVALID_PARAMETER_VALUE ... Content in ChatMessage", whatever you asked
  for. Opus 5 replies in a different shape to the models before it, and the app
  was handing part of that reply back to the model in a form it wouldn't accept —
  it failed the moment the assistant used one of its tools, which is nearly
  always. Both studios now tidy up any model's reply before continuing the
  conversation, so this won't come back the next time a new model lands.
- **The app doesn't freeze while it starts, and it starts a lot faster.** Every
  page load used to download every version of every widget ever published —
  including all their code and preview images, tens of megabytes on a mature
  library — and then compile the lot before it would show you anything. That got
  slower every time anyone saved a widget, and had reached the point where the
  browser offered to close the tab for you. Now your dashboard downloads what it
  needs to draw itself, and a widget is prepared when it appears rather than all
  of them up front: on a test library of 30 widgets the page went from unusable
  for 17 seconds to ready in 1.5. Preview images arrive when you open the Widget
  Library, and screens like the Studios and the Admin panel are fetched quietly
  in the background instead of holding up the dashboard. Pinning a widget to an
  older version still works exactly as before; it fetches that version when it
  draws it.
- **A slow network no longer empties the Widget Library.** If the widget compiler
  hadn't finished downloading by the time the page was ready, every widget was
  quietly dropped and you were left with an empty library and no explanation. The
  page now waits for it, and says so if it never arrives.
- **Widgets built before authorship worked can be edited again.** Correcting who gets
  credited for a widget had a side effect: widgets created earlier were recorded
  against a placeholder rather than a person, and the library treated them as
  somebody else's — hiding them behind the Certified filter and taking away their
  Edit and Delete buttons for everyone. A widget with no real author now belongs to
  nobody, so anyone can pick it up, which is how deleting one already worked.

## 1.8.0 — 2026-08-11

### Added

- **The Widget Library says who built each widget.** Every card and list row credits
  its creator, and clicking a name shows you everything else that person has built.
- **A Top creators board.** The button in the Widget Library header opens a short
  ranking of the people whose widgets get used, scored on what they've published,
  how many people use it, and where it's placed. Using your own widget doesn't count
  towards your own score.

### Fixed

- **Your name is recorded properly on what you create.** Widgets were being filed
  under "dev" or "unknown" instead of the person who made them, which is also what
  showed up when a widget wrote your name into a table. The app now resolves your
  real identity — and where it genuinely can't, it says "unknown" rather than
  inventing something that looks like a person. Widgets published before this keep
  whatever they were stamped with; the Top creators board lists how many those are.
- **Widgets stamped with a placeholder name can be deleted again.** A widget filed
  under "dev" by the bug above had an owner nobody could match, so nobody could
  remove it. Anything without a real author is now anyone's to tidy up, and your own
  widgets stay yours whichever way your address happens to be capitalised.
- **A long Widget Studio request keeps to the time you gave it.** The limit was being
  applied per attempt rather than to the request, so a slow build could quietly run
  about three times over. Planning the work is also capped separately now — a slow
  plan used to be able to spend the entire allowance and leave nothing to build with,
  which is how a big request could take the full timeout and come back empty.
- **A SQL query that fails says why, in the widget.** A rejected query — a renamed
  table, a column that needs backticks, a permission you don't have — reported itself
  as "no data", so a fixable mistake looked like an empty result. The error now
  reaches the widget and Widget Studio's auto-fix, which can act on it. Widgets built
  before this change show the same empty state they always did rather than breaking.
- **A model setting can't be pointed somewhere it shouldn't go.** The per-model
  parameter overrides in Admin Panel → Settings now accept tuning parameters only,
  and say which name they refused.

## 1.7.0 — 2026-08-10

### Added

- **Widget Studio builds big requests in steps.** Ask for several things at once —
  a table, a filter bar, and a CSV export — and the agent plans the work, then does
  one step at a time. You see the plan tick over as it goes, each step lands in the
  editor the moment it's ready, and History gets an entry per step so you can go
  back to any point. If a step fails, the earlier ones stay; there's a **Stop after
  this step** link when you've seen enough. This is the fix for a large request
  spending minutes and then returning nothing.
- **Timeouts and limits are settings now.** Admin Panel → Settings has cards for the
  chat agent's limits and the studios', including how long a Widget Studio request may
  take before it gives up. Widget Studio waits as long as that allows — it used to
  stop at five minutes whatever the setting said — and the spinner counts the seconds
  so a long build reads as work rather than as a hang. If a request does run out of
  time, whatever the agent already applied is kept and the reply tells you which knob
  to turn.

### Fixed

- **Changing the model no longer breaks Widget Studio.** Some models refuse settings
  others require — a temperature that newer Claude models won't accept, a reasoning
  flag some models insist on — and Widget Studio always sent the same ones, so
  choosing certain models failed every generation while chat carried on working. The
  app now sends each model only what it accepts, learns from anything an endpoint
  refuses, and if a model needs something unusual you can name it under **Model
  parameter overrides** in Settings without a redeploy.
- **Queries against columns with spaces in their names work.** Databricks needs names
  like `Ship Date` wrapped in backticks, and the agents were writing them bare —
  which failed. Both the chat agent and Widget Studio now quote them properly, and are
  reminded of the rule if a query still fails on a name.
- **A failed query says so instead of showing an empty widget.** A query the warehouse
  rejected — a typo, a missing table, no permission — came back as a widget with no
  data and no explanation. The error is now reported, which also lets Widget Studio
  fix its own query on the retry.

## 1.6.0 — 2026-08-04

### Added

- **History in Widget Studio.** A **History** button next to Reload lists versions
  of your widget you can go back to, and **Restore** puts one back in the editor.
  Every change the studio makes for you is saved there first — each agent turn, each
  import, each Reset — along with a snapshot of your own editing as you go, so a turn
  that goes wrong is one click from undone. For a widget you've already published,
  the panel also lists its published versions with who saved each one and how large
  it was, so you can pull an older one back without leaving the studio. Restoring
  only loads code: your Configuration settings are untouched, nothing is published
  until you press Publish, and the version you restored over is itself kept in
  History in case you want it back.

### Fixed

- **The agent no longer erases your widget when you ask it to change one.** Asked
  for a small change, it would sometimes reply with just the part it had rewritten —
  or with a placeholder like "the rest of the component is unchanged" — and that
  reply replaced the whole file, taking everything else with it. Those replies are
  now recognised and refused: your code is left exactly as it was while the agent is
  asked to make the change in place instead, which is what it does on the retry. If a
  turn does legitimately replace most of your widget, the reply says so and points at
  History. You no longer need to ask it to "merge" the changes.

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
