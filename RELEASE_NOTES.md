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

## 1.4.0 — 2026-07-29

### Added

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
