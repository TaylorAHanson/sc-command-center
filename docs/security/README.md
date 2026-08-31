# Security Response — ISRP-REQ-24803

Index and shared framing for our response to the ISRP application security
review. One document per finding:

| Finding | Topic | Document |
| --- | --- | --- |
| ISRP-REQ-24803-30 | AI-generated widget code and dynamic execution | [`isrp-30-generated-widget-code.md`](isrp-30-generated-widget-code.md) |
| ISRP-REQ-24803-31 | File upload and write-back to Unity Catalog | [`isrp-31-write-back-and-uploads.md`](isrp-31-write-back-and-uploads.md) |
| ISRP-REQ-24803-32 | GenAI, MCP tools, and Red CCI | [`isrp-32-genai-and-ai-gateway.md`](isrp-32-genai-and-ai-gateway.md) |

## The framing we use in every response

On-Behalf-Of plus Unity Catalog is the **primary control** — the app never
widens what a signed-in user may read or change. The findings are about the
*additional surface* that generated code, write-capable widgets, and LLM prompts
introduce on top of that.

Everything in these documents is a **compensating control**: an app- or
platform-level guardrail that reduces that additional surface. We do not claim
any of them replaces Unity Catalog, and we do not claim the app is a sandbox.
Where the honest answer is "that belongs to the platform", we say so rather than
inventing an application control that a reviewer would later find to be
cosmetic.

Status values used in every table: **In place** (shipped, has a code path),
**Committed** (agreed, not yet built), **Proposed** (offered, awaiting a
decision), **Platform** (belongs to Databricks or Qualcomm IT, not this repo).

## Primary controls already in the product

Cite these first in any response. Reviewers routinely miss them because they are
architectural rather than a feature with a settings page.

| Control | Evidence |
| --- | --- |
| Every data operation runs as the signed-in user via their forwarded OBO token; Unity Catalog governs per user | `server/middleware/auth.py` (`get_db_client`) |
| LLM *inference* is the one deliberate service-principal exception; it touches no user data, and every tool call is still OBO | `server/services/agent_runtime.py` (`AGENT_RUNTIME_LLM_AUTH`) |
| Publishing a widget requires domain-editor rights; promotion Dev → Test → Prod and certification are separate rights | `server/routes/custom_widgets.py`, `server/routes/promotion.py` |
| Mutating widget controls route through `executeAction`, which forces a confirmation with a mandatory written explanation, now recorded with the acting user | `src/contexts/ActionContext.tsx`, `server/routes/actions.py` |
| Chat uploads are extension/MIME allowlisted, size-capped (25 MB, 5 per conversation), and parsed by library — never executed | `server/services/file_extract.py`, `server/routes/chat_uploads.py` |
| Attached file *contents* never enter the prompt; the agent gets a constant-size profile and must pull data through structured tools | `server/services/upload_tools.py` |
| `query_file` takes a structured spec, not a pandas or SQL string — no model-authored code is evaluated in the web process, which holds the caller's credentials | `server/services/upload_tools.py` |
| Author-written Python tools execute in a subprocess with credentials stripped from the environment | `server/routes/agent_studio_profiles.py` |
| Admin-settable model parameters are restricted to a closed key list, so a stored setting cannot redirect `base_url` and mail prompts plus the app credential to another host | `server/services/llm_params.py`, `server/services/settings_store.py` |
| Third-party widget scripts load only over HTTPS from an allowlisted CDN | `src/hooks/useScript.ts` |
| SQL failures return a sanitized reason; tracebacks stay in the log rather than rendering on a dashboard | `server/routes/sql_query.py` |
| The frontend holds no secret; all credentialed integration is a backend route | `src/AGENTS.md` |

**Gaps these do not cover**, stated plainly so the response stays credible:
widget TSX is still compiled and executed in the browser (`new Function` +
Babel) — the CSP constrains where that code may send data but does not stop it
running, and that is inherent to the product rather than an oversight; the
Python tool sandbox has no network isolation; there is no application-level data
classification; and the fallback `users` → Global/admin role mapping still
grants everyone global admin on any deployment where an admin has not replaced
it, which is now the main thing standing between a deployment and real
role enforcement.

## Decisions taken

These were open questions in the first draft. Recording the answers because they
change the wording we commit to.

1. **Write-back means Unity Catalog DML under OBO**, not a file-to-table ingest
   path. We answer it with the Databricks-native write controls that already
   exist, plus our own confirmation and audit trail. No new ingest feature is
   implied or promised. See finding 31.
2. **Red CCI will be tagged in Unity Catalog.** The control is therefore
   tag-driven and enforced in the engine, not in application code. Unity Catalog
   ABAC can mask or filter tagged data specifically when an OAuth application
   acts on behalf of a user, which covers the SQL paths including `dbsql`
   — but explicitly **not** Genie. See finding 32.
3. **Attribution is solved by correlation, not by changing the auth model.** The
   app can mint a `client_request_id` per turn; it is logged in the gateway
   inference table and in our own records, which hold the real username. The
   service-principal inference exception stands. See finding 32.
4. **We do not depend on Beta features for the core answer.** The
   previous-generation AI Gateway (per-serving-endpoint) is GA and delivers
   usage tracking, payload logging, rate limits, and safety/PII filters. Unity
   AI Gateway and ABAC context attributes are Beta and are offered as the
   stronger posture where the customer will accept a preview. Finding 32
   presents both.

## Priority

| Wave | Items | Status |
| --- | --- | --- |
| 1 — low risk | Acting user on action logs (31.1); `useScript` HTTPS + CDN allowlist (30.2); this documentation set | **Done** |
| 2 — application controls | Permission checks on by default (30.6); publish-time static checks (30.3); write-shaped SQL implies executable (30.4); read-only `execute-raw` (30.5); certified-only for global views (30.1); CSP (30.7); admin kill-switches (32.3); `client_request_id` correlation (32.7); tool-result caps and metadata-only logging (32.5); retention and delete-my-chats (32.6); context minimization (32.2); GenAI notice (32.4); env and request id on action logs (31.2, 31.3); API docs closed (30.8) | **Done** |
| 3 — configuration | Route all model traffic through a governed gateway endpoint; enable payload logging, rate limits, guardrails; ABAC policies on CCI tags | Awaiting platform-team decision |
| 4 — deferred | Widget iframe/worker isolation; hardened Python tool sandbox with network isolation; replacing the fallback `users` admin mapping per deployment | Awaiting decision — see backlog |

## What shipped in wave 2, and what it cost

Recorded because several of these were previously listed as risky, and the way
the risk was handled is part of the answer.

| Item | How the risk was handled |
| --- | --- |
| Permission checks on by default (30.6) | Bundle default flipped to `false`. The lockout-prevention seed that maps `users` → Global/admin is unchanged — removing it would leave a fresh deployment with no administrator and no way in — but it now logs a warning naming exactly what it granted. **Flipping the flag accomplishes nothing until that mapping is replaced**, which is a per-deployment action, not a code change. |
| Publish-time static checks (30.3) | Rejects rather than warns, per the decision to prefer a visible failure in a dev-stage product. Comment stripping is a state scanner rather than a regex, so `https://` in a string is not mistaken for a comment; 22 unit tests in `tests/test_widget_safety.py`. An existing widget that violates the rules fails on its next save, not while running. |
| Write-shaped SQL implies executable (30.4) | Same classifier as the endpoint below, so publishing and execution cannot disagree about what a statement is. Only applies on save. |
| Read-only `execute-raw` (30.5) | Reads are an allowlist (`SELECT`/`WITH`/`SHOW`/`DESCRIBE`/`EXPLAIN`/`VALUES`/`TABLE`), anything unrecognised classifies as a write, and writes moved to `POST /api/sql/execute-write`. Refusals return the empty-result body older widgets read without checking status, so a refusal renders "no data" rather than crashing a panel. |
| Certified-only for global views (30.1) | Shipped as a setting defaulting **off**, not as a default. Certification is applied during promotion to production, so defaulting it on would make global views impossible to create in dev and test. Enforced on update as well as create. |
| CSP (30.7) | Enforced by default with a report-only escape hatch in Settings. `'unsafe-eval'` is present and load-bearing: Babel compiles widget TSX in the page. The directive doing the work is `connect-src`, which limits where widget code may send what it read. Verified against the built `dist/index.html` — no inline scripts, no workers. |
| Admin kill-switches (32.3) | Default **on** (permissive), matching current behaviour, so nothing changes for an existing deployment until an admin chooses. Applied where the tool list is built, so a disabled tool is never advertised — and a saved agent naming it cannot reintroduce it. |
| `client_request_id` (32.7) | Sent via `extra_body`, best-effort: an endpoint that rejects the field is remembered per model and the call retried without it, so traceability degrades and the answer does not. The app logs the id with the resolved username, which is its half of the join. |
| Prompt context minimization (32.2) | A setting defaulting to current behaviour, enforced server-side in `_system_prompt` rather than client-side, so a stale browser cannot defeat it. |
| Retention (32.6) | No scheduler exists, so the sweep runs off the conversation-list request, throttled hourly per env and non-fatal. Default 0 (keep indefinitely) because the retention period is a policy decision. |

## Backlog awaiting a decision

| Item | Finding | Risk / reason deferred |
| --- | --- | --- |
| Replace the fallback `users` → Global/admin mapping | 30.6 | Per-deployment operational step, not a code change. Until it is done, role checks are enforced against a mapping that grants everyone admin. **This is the highest-value remaining item.** |
| Widget iframe/worker isolation | 30.7 | Re-architecture of `src/widgetRegistry.ts`. The CSP now covers the exfiltration half of the risk, which was the part worth having first. |
| Network isolation for the Python tool sandbox | 32.8 | The subprocess strips credentials and caps time and memory, but can still reach the network. Fixing it properly means a network namespace or an external execution service. Mitigated by the documented training and review requirement. |
| Application-level data classification | 32 | Deliberately not built: Red CCI is handled by Unity Catalog tags and engine-side policy, which is where classification belongs. |

## Change log

| Date | Change |
| --- | --- |
| 2026-08-24 | Created. Findings triaged; primary vs compensating framing established; finding 32 anchored on AI Gateway. |
| 2026-08-24 | Split into per-finding documents. Open questions resolved (write-back scope, CCI tagging, attribution, Beta dependency). Wave 1 implemented. |
| 2026-08-24 | Wave 2 implemented: 15 application-level compensating controls across all three findings. Backlog reduced to platform configuration, widget isolation, sandbox network isolation, and the per-deployment admin mapping. |
