# ISRP-REQ-24803-31 — File upload and write-back to Unity Catalog

Read [`README.md`](README.md) first for the primary-vs-compensating framing, the
status legend, and the list of primary controls already in the product.

## The finding

The app supports file uploads through the agent workflow and allows users to
perform write operations against schemas they are already authorized to modify
through Databricks. OBO prevents privilege escalation, but file upload and
write-back introduce data integrity, malicious content, and unintended
modification risks that do not exist in dashboard-only applications.

ISRP asks for: a documented secure file upload and write-back pattern before
production, malware scanning, file type restrictions, upload auditing,
validation controls, change tracking, and monitoring of high-risk data
modification events. All write-capable widgets should undergo enhanced review
and testing prior to publication.

## Scope correction we lead with

The finding treats two different things as one. Separate them first, because
the answer to each is different.

**Chat uploads are not ingest.** A file attached in the assistant drawer is
stored in the app's own Lakebase Postgres, scoped to one conversation, parsed by
allowlisted libraries, and never executed or written into Unity Catalog. There
is no file-to-table path in the product, and we are not proposing one.

**Write-back means Unity Catalog DML under OBO** — a widget or agent tool
running `INSERT`/`UPDATE`/`DELETE`/`MERGE` against a table the signed-in user
already holds `MODIFY` on. This is ordinary Databricks data modification
performed through a different client. It is governed by the same platform
controls as a notebook, a SQL editor query, or a job, and those controls are the
substance of our answer.

## Write-back: the Databricks controls that already apply

These are the compensating controls for data modification, and they are all
platform-native. Nothing in this section is something Command Center has to
build, which is precisely the point worth making to ISRP: writes through the app
are not a new, unaudited channel.

### Authorization

| Control | What it gives the reviewer |
| --- | --- |
| **`MODIFY` privilege on the table**, plus `USE CATALOG` and `USE SCHEMA` on its parents | A user who cannot write a table from a notebook cannot write it from a widget. The app never grants, escalates, or proxies this — the statement runs under the user's own OBO token. |
| **Object ownership and grant hierarchy** | Who may change the data, and who may change who may change it, stays a Unity Catalog decision administered outside the app. |
| **ABAC row filter and column mask policies** | Tag-driven restrictions apply at query time to writes as well as reads. See finding 32 for the tag-based design; the same policies bound what a write can target. |

### Change tracking and recovery

| Control | What it gives the reviewer |
| --- | --- |
| **Delta transaction log** | Every write is an atomic, versioned commit. There is no partial-write state to reconcile. |
| **`DESCRIBE HISTORY <table>`** | Per-version record of the operation (`WRITE`, `MERGE`, `DELETE`), its parameters, the user, and the timestamp. This is the change-tracking control ISRP asks for, at table granularity. |
| **Time travel and `RESTORE`** | Unintended modification is recoverable to a prior version rather than being a data-loss event. Note the recovery window is bounded by the table's retention and `VACUUM` settings — state the configured window rather than implying it is unlimited. |
| **Unity Catalog lineage** (`system.access.table_lineage`, `column_lineage`) | Downstream impact of a modification is traceable, which is what turns "a widget changed a table" into an assessable blast radius. |

### Monitoring and audit

| Control | What it gives the reviewer |
| --- | --- |
| **`system.access.audit`** | Account-level audit of Unity Catalog operations. For on-behalf-of calls the `identity_metadata` field records the acting resource alongside the run-as user, so writes that arrived *through an OAuth application* are distinguishable from the same user's direct queries. That is how a reviewer answers "which of these changes came from Command Center?" without trusting the app to self-report. |
| **`system.query.history`** | The statements actually executed, with user, warehouse, duration, and outcome. Model-generated SQL is as visible here as hand-written SQL. |
| **Serving and warehouse monitoring** | High-volume or anomalous modification patterns surface in the same place as the rest of the workspace's activity. |

The honest framing: **the app is a client, and Databricks audits its clients.**
Our own logging below is additive context — the *intent* behind a change — not a
substitute for the platform record.

## Compensating controls in the application

| # | Control | Status | Notes and evidence |
| --- | --- | --- | --- |
| 31.1 | **Every action records the acting user.** `action_logs` now stores the username resolved from the caller's OBO identity alongside the widget, action name, written explanation, and dashboard context, and the Action Logs screen shows and searches it. | **In place** | `server/database.py`, `server/routes/actions.py`, `src/pages/ActionLogs.tsx`. Unresolved identities store `NULL` rather than a placeholder, following the `widget_runs` precedent — a plausible-looking stand-in is worse than an honest blank, because after the fact it is indistinguishable from real attribution. |
| 31.2 | **The confirmation *is* the audit trail.** Every executable control routes through `executeAction`, which blocks on a modal requiring a written explanation before the callback runs. Databricks records *what* changed; this records *why*, and who said so. | **In place** | `src/contexts/ActionContext.tsx`, `src/components/BaseWidget.tsx`. |
| 31.3 | **Fail closed when a write-capable widget bypasses `executeAction`.** A widget whose SQL data source changes data cannot be saved unless it is marked executable, which is what forces the confirmation path. | **In place** | `server/services/widget_safety.py`; same classifier as 30.5, so the publish check and the endpoint agree about what a statement is. |
| 31.4 | **Approvals are joinable to the statements they authorised.** Each confirmation mints a request id, stores it on the `action_logs` row, and hands it to the widget's callback; `POST /api/sql/execute-write` stamps it into the statement as a leading comment, so the same id appears in `system.query.history`. | **In place** | `src/hooks/useActionLogger.ts`, `server/routes/actions.py`, `server/routes/sql_query.py`. This is the missing join: the app records intent, Databricks records effect, and until now the two records shared no field. Visible in the expanded row on the Action Logs screen. |
| 31.5 | **Action logs are environment-scoped.** The logging endpoints accept and pass through `env` like every other stored-state route. | **In place** | `server/routes/actions.py`. A consistency fix rather than a security one: the runtime app addresses the `dev` dataset throughout, so these rows were never landing in the wrong place relative to the widgets that produced them. |
| 31.6 | **Enhanced review before publication for write-capable widgets** — certification required before a writing widget may be shared. | **In place**, default off | Uses the existing certification right; see 30.1. Applies to global views. |
| 31.7 | **Warehouse or statement policy defaulting widget traffic to read-only**, with writers on a named, separately reviewed path. | Proposed (platform) | The strongest version of this control, and enforced outside the app so it cannot be bypassed by a different client. Note the app now distinguishes read from write at its own boundary (30.5), which makes this policy easier to apply without breaking dashboards. |

## Uploads: the controls that apply

| # | Control | Status | Notes and evidence |
| --- | --- | --- | --- |
| 31.8 | **File type restrictions.** Uploads are allowlisted by extension and MIME type; anything unrecognized is refused with a message naming the supported types. | **In place** | `server/services/file_extract.py` (`sniff_kind`). |
| 31.9 | **Size and count limits**, enforced while streaming so an oversized body is rejected without ever being held in memory. 25 MB per file, 5 attachments per conversation, 50 conversations retained per user. | **In place** | `server/routes/chat_uploads.py`, `server/services/upload_store.py`. |
| 31.10 | **Content is parsed, never executed**, by allowlisted libraries (pandas, openpyxl, pypdf, python-docx). Parsing failures are recorded on the row and never raised into the request path. Archive expansion is bounded to limit decompression abuse. | **In place** | `server/services/file_extract.py`. |
| 31.11 | **Upload auditing.** Each upload is a row with its owner, conversation, filename, size, and parse status. | **In place** | `chat_uploads` table, `server/services/upload_store.py`. |
| 31.12 | **Uploads stay read-only.** No path writes an uploaded file to a Volume, a table, or any Unity Catalog object. If one is ever added it gets its own review. | **In place** (as a design constraint) | Worth stating explicitly in the ISRP response, because the finding assumes otherwise. |
| 31.13 | **Uploaded files are deleted with the conversation that owns them**, individually, in bulk via **Delete all my conversations**, or automatically once the administrator's retention period elapses. | **In place** | `server/services/conversation_store.py`. Bounds how long attached business data sits in the app's own store — previously only the 50-conversation cap did. |
| 31.14 | **Malware scanning of uploaded bytes.** | Platform | Files are parsed by allowlisted libraries and are never executed, re-served to other users, or written to shared storage, so the traditional AV rationale is weak here. If ISRP requires scanning regardless, it belongs at the endpoint or Apps ingress layer rather than in this repo. |

## Platform-level

- **Malware scanning at ingest**, if required, is a Databricks Apps or Qualcomm
  IT control.
- **Grants, Delta history, time travel retention, lineage, and the system audit
  and query-history tables** are all Databricks. The app's job is to not
  circumvent them, which OBO guarantees structurally.
- **Retention and recovery windows** are a platform configuration. Quote the
  configured value in the response rather than implying an unlimited window.
