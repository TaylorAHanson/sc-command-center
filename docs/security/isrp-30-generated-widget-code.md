# ISRP-REQ-24803-30 — AI-generated widget code and dynamic execution

Read [`README.md`](README.md) first for the primary-vs-compensating framing, the
status legend, and the list of primary controls already in the product.

## The finding

The app lets users generate and publish widget code from natural-language
prompts and execute those widgets against Databricks data sources, APIs, and
actions. Widgets run under OBO and do not elevate permissions, but the platform
introduces an attack surface where AI-generated code, user-supplied
configuration, or insufficient validation could result in insecure data access
patterns, malicious code generation, unauthorized API usage, client-side
injection, or abuse of executable actions.

ISRP asks for: secure development standards for AI-generated widgets, mandatory
human review of executable widgets, validation of generated code against
approved patterns, input sanitization, restrictions on supported APIs and
actions, and application security testing focused on code generation, dynamic
execution, and user-supplied widget configuration.

## Our position

We accept the finding as stated. OBO bounds the blast radius to the user's own
Unity Catalog entitlements — a generated widget cannot read or write anything
its operator could not read or write directly — but it does not stop badly
generated or deliberately abusive code from running *as* that user in their
browser. That residual risk is what the compensating controls below address.

We do not claim the widget runtime is a sandbox. Widget TSX is compiled with
Babel and evaluated through `new Function` in the page
(`src/widgetRegistry.ts`), which is inherent to a dynamic-widget architecture.
Our controls therefore concentrate on **what may be published**, **what a
published widget may reach**, and **who may share one**, rather than on
containing arbitrary JavaScript after it is already running.

The useful question, given that arbitrary code will run, is not "can it run" but
"where can it send what it read". Three controls answer that at different
layers, and they are deliberately redundant: the generator is instructed to use
only allowlisted hosts, the publish path refuses to store code that names any
other, and the browser refuses to connect to one regardless. Each is independent
of the others, so bypassing one does not reach the data.

## Compensating controls

| # | Control | Status | Notes and evidence |
| --- | --- | --- | --- |
| 30.1 | **Certified-only for global views.** A view shared with everyone may contain only widgets an admin has certified — the mandatory-human-review control ISRP asks for, built on the review path that already exists. Enforced on create and on update, against the resulting widget list. | **In place**, default off | `server/routes/views.py::_require_certified_widgets`, setting `require_certified_for_global_views`. **Default off deliberately**: certification is applied during promotion to production, so nothing in dev or test is certified and defaulting it on would make global views impossible to create there. Turn it on for the production deployment. |
| 30.2 | **`useScript` requires HTTPS and an allowlisted CDN host.** Third-party libraries load only from a named list; `javascript:`, `data:`, plain HTTP, and arbitrary hosts are refused before a `<script>` tag is ever created, and the widget surfaces a load error instead. | **In place** | `src/hooks/useScript.ts`. Default hosts: `cdn.jsdelivr.net`, `code.highcharts.com`, `unpkg.com`, `cdnjs.cloudflare.com`. Closes the cheapest client-side supply-chain and script-injection path. The generation contract already mandated jsDelivr (`server/routes/agent_instructions.md`); this makes it enforcement rather than advice. |
| 30.3 | **Publish-time static checks.** Saving a widget is refused if the code contains `eval`, `new Function`, `document.write`, `innerHTML`, `dangerouslySetInnerHTML` or `importScripts`, or references any absolute URL whose host is not on the CDN allowlist. Applied to every write path, so an author cannot update their way to what they could not create. | **In place** | `server/services/widget_safety.py`, called from both handlers in `server/routes/custom_widgets.py`. 22 tests in `tests/test_widget_safety.py`. Comments and string literals are separated by a state scanner rather than a regex — naive comment stripping deletes the rest of the line from inside `'https://…'`, which is how a checker like this produces nonsense. Rejects rather than warns, per the decision to prefer a visible failure at this stage of the product. |
| 30.4 | **Write-shaped SQL implies an executable widget.** A SQL data source that changes data cannot be saved unless the widget is marked executable, which is what routes its controls through the confirmation-and-explanation path. | **In place** | `server/services/widget_safety.py::review_widget`, using the same classifier as 30.5 so publishing and execution cannot disagree about what a statement is. Closes the case where a widget presents as a read-only panel and is not one. |
| 30.5 | **`execute-raw` is read-only; writes moved to `execute-write`.** Reads are an allowlist (`SELECT`, `WITH`, `SHOW`, `DESCRIBE`, `EXPLAIN`, `VALUES`, `TABLE`) with no write verb anywhere in the statement; anything unrecognised classifies as a write and is refused. | **In place** | `server/services/sql_safety.py`, `server/routes/sql_query.py`. Catches a write behind a leading CTE and a second statement after a semicolon; ignores verbs inside comments, string literals and quoted identifiers. Refusals return the empty-result body that widgets predating the error contract read without checking status, so a refusal renders "no data" rather than crashing a live panel. |
| 30.6 | **Role and permission checks on by default.** `disable_permission_checks` now defaults to `false`. | **In place**, with a caveat | `databricks.yml`. **The flag alone changes nothing**: the lockout-prevention seed in `server/database.py` maps `users` → Global/admin when a deployment has no admin mapping, and `users` is everyone. It is kept — removing it leaves a fresh deployment with no administrator and no way in — but now logs a warning naming what it granted. Replacing that row with a real admin group is a per-deployment step and is the highest-value remaining item in the backlog. |
| 30.7 | **Content Security Policy.** `connect-src` and `script-src` limit widget code to this app's own origin and the four allowlisted CDNs, with `object-src 'none'`, `base-uri 'self'`, `form-action 'self'` and `frame-ancestors 'self'`. Enforced by default; an admin can downgrade to report-only to diagnose a widget. | **In place** | `server/main.py`. `'unsafe-eval'` is present and load-bearing — Babel compiles widget TSX in the page — so this does not contain a malicious widget. What it does is bound where such a widget could *send* what it read, which was the more valuable half. Verified against the built `dist/index.html`: no inline scripts, no workers. |
| 30.8 | **Interactive API documentation closed outside local and dev.** `/api/docs`, `/api/redoc` and `/api/openapi.json` publish the whole route surface. | **In place** | `server/main.py`. An unset `APP_ENVIRONMENT` is treated as "do not expose", so a deployment that forgot to set it stays closed; `DEV_MODE=true` re-opens them on a developer machine, where `APP_ENVIRONMENT` is normally unset. |
| 30.9 | **Iframe or worker isolation for widget execution.** | Deferred | The only thing that genuinely contains a malicious widget, but a re-architecture of `src/widgetRegistry.ts`. 30.7 now covers the exfiltration half of the risk, which was the part worth having first. |

### Already true, and worth citing under this finding

- Publishing to a domain requires **domain-editor** rights; promotion across
  Dev → Test → Prod and certification in production are **separate** rights held
  by domain admins (`server/routes/promotion.py`, `server/routes/roles.py`).
- Widgets cannot import arbitrary modules. The runtime's `require` shim resolves
  only React, ReactDOM, and a matching `window` global, and throws a clear
  per-widget error otherwise, which also stops one bad widget from failing the
  registry (`src/widgetRegistry.ts`).
- Every mutating control must route through `executeAction`, which forces a
  confirmation dialog with a mandatory written explanation before the callback
  runs, now recorded with the acting user (`src/contexts/ActionContext.tsx`,
  `server/routes/actions.py`).
- Widget SQL errors return a sanitized reason. Tracebacks stay in the log rather
  than rendering into a dashboard panel (`server/routes/sql_query.py`).
- A stored admin setting cannot redirect model traffic: `model_params` is
  restricted to a closed key list, checked on save and again on read, so a
  setting cannot introduce a `base_url` that would mail prompts and the app
  credential to another host (`server/services/llm_params.py`).

## Platform-level

State these; do not promise them as application controls.

- **Unity Catalog remains the ACL.** No app-side check substitutes for a grant,
  and we do not maintain a second permission model over data.
- **Browser-side execution of widget code is inherent** to the dynamic-widget
  architecture. Databricks Apps does not offer a server-side JavaScript sandbox.
- **CDN reachability is a network decision.** We already prefer jsDelivr because
  some corporate environments return 403 for other CDNs. If Qualcomm requires an
  internal mirror, 30.2's allowlist is one constant to change
  (`ALLOWED_SCRIPT_HOSTS` in `src/hooks/useScript.ts`), plus the corresponding
  line in `server/routes/agent_instructions.md`.
- **Application security testing** of the generation and execution paths is a
  program commitment, not a code change. Scope it to: prompt injection into
  widget generation, publish-path validation bypass, and the executable-action
  confirmation flow.
