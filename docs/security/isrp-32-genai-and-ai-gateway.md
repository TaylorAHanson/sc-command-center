# ISRP-REQ-24803-32 — GenAI, MCP tools, and Red CCI

Read [`README.md`](README.md) first for the primary-vs-compensating framing, the
status legend, and the list of primary controls already in the product.

## The finding

The app uses Databricks-hosted foundation models and MCP tools such as `dbsql`
and `genie_ask`, and may operate against Red CCI datasets accessible to the
user. Although the app states that Qualcomm data does not leave Databricks and
relies on Databricks compliance commitments, no application-specific controls
were identified governing what data may be submitted to AI services, how prompts
and responses are monitored, or how sensitive information disclosure through
AI-assisted workflows is prevented.

ISRP asks for: an approved GenAI usage pattern, data classification
restrictions, approved AI use cases, prompt and response logging, monitoring for
sensitive data exposure, and alignment with Qualcomm-approved GenAI controls.

## Our position

The finding is correct that "it stays in Databricks" is a tenancy statement
rather than a control, and correct that the application does not implement its
own DLP.

**We are not going to build one.** A bespoke classification and filtering layer
inside the app would be weaker than the platform's, unauditable from outside the
app, administered by app admins rather than the governance team, and trivially
bypassed by any other client reaching the same data. Instead:

> Every model call and every MCP tool call is routed through Databricks AI
> Gateway, and sensitive-data restrictions are enforced by Unity Catalog tags
> and policies at query time. The controls ISRP is asking for exist at the
> platform layer, are administered by the governance team, and log to Unity
> Catalog where the customer already audits everything else.

This is a stronger answer than an app feature, and most of it is configuration
rather than code.

## Why this is mostly configuration

The app already derives its OpenAI-compatible base path from the configured
model name, and already accepts an explicit override that pins *every* model to
one path:

```
server/services/settings_store.py::base_path_for_model
  system.ai.<name>   -> /ai-gateway/mlflow/v1     (gateway route)
  <endpoint name>    -> /serving-endpoints        (direct route)
  AGENT_RUNTIME_LLM_BASE_PATH / AGENT_STUDIO_LLM_BASE_PATH override both
```

MCP servers are likewise a configured list (`AGENT_STUDIO_MCP_SERVERS`, default
`/api/2.0/mcp/sql,/api/2.0/mcp/genie`), and the model each caller uses is an
admin-editable row in `app_settings`.

So "all AI traffic is governed" becomes a deployment posture that a reviewer can
verify from configuration, rather than a behaviour they have to trust us about.

## Two deployment postures

Unity AI Gateway is Beta and needs account-admin enablement. We therefore
present a **GA-only posture that fully answers the finding**, and a stronger
posture for customers who will accept previews. Do not let a review stall on the
Beta question — lead with the GA column.

| ISRP ask | GA today (per-endpoint AI Gateway) | Stronger, currently Beta |
| --- | --- | --- |
| Prompt and response logging | **Payload logging to Unity Catalog inference tables**, enabled per serving endpoint | Unity AI Gateway inference tables, covering model calls **and MCP interactions** |
| Monitoring for exposure / usage | **Usage tracking** to `system.serving.endpoint_usage` | `system.ai_gateway.usage`, plus token-level cost attribution and per-user budget alerts |
| Restrictions on what may be submitted | **Guardrails: PII detection (Presidio) and safety filtering (Llama Guard)** on inputs and outputs | LLM-judge service policies: PII redaction or blocking, unsafe content, jailbreak/prompt-injection, hallucination |
| Qualcomm-specific rules (CCI markers, codenames) | Not available as a gateway policy — use the ABAC design below | **Custom service policies**: SQL UDFs evaluated `ON CALL` and `ON RESULT`, versioned in Unity Catalog |
| Limiting which tools an agent may invoke | App-side per-agent tool lists, and the `AGENT_STUDIO_MCP_SERVERS` list | **Service policies for MCP**, keyed on identity and request context, not editable by an app admin |
| Runaway or anomalous usage | **Rate limits** (QPM/TPM per user, group, or service principal) and fallbacks | Same, plus enforced budget thresholds |

Sources, confirmed August 2026:
[Unity AI Gateway overview](https://developers.databricks.com/docs/agents/ai-gateway),
[Configure guardrails](https://learn.microsoft.com/en-us/azure/databricks/ai-gateway/guardrails),
[Service policy function reference](https://docs.databricks.com/aws/en/data-governance/unity-catalog/service-policies/policy-function-reference),
[Inference tables](https://docs.databricks.com/aws/en/ai-gateway/inference-tables-serving-endpoints).

## Red CCI: tag-driven refusal

Given that Red CCI will be tagged in Unity Catalog, the question was whether the
app can simply decline to read it even when a user asks.

**The better answer is that Unity Catalog can decline on our behalf, at query
time, for the SQL paths — including `dbsql`.** Unity Catalog ABAC combines
governed tags with row filter and column mask policies, and policy conditions
can test the *context of the request*:

| Attribute | Meaning |
| --- | --- |
| `request.is_on_behalf_of` | `'true'` when an OAuth application is acting on behalf of a user |
| `request.client_id` | The OAuth client ID of the calling application — for us, the Databricks App's client ID from its authorization details page |

A column mask policy conditioned on `has_context_attribute_value('request.client_id', '<Command Center client id>')`
masks CCI-tagged columns **when Command Center asks**, while the same user
querying directly in the workspace is unaffected. That is exactly the shape the
finding is reaching for, and it requires no application code, applies to every
SQL path uniformly, and cannot be bypassed by a widget, an agent tool, or a
prompt-injection attack — because it is enforced in the engine rather than in
our request handler.

### Four caveats that must be in the design review

1. **Genie is not covered.** Databricks states these context attributes identify
   external agents, **not Genie agents**. For a CCI workspace the control is
   therefore to disable the Genie MCP server (32.3) or to ensure Genie spaces
   are scoped to tables carrying no CCI tags. This is the one place the
   engine-side answer does not reach, and we should say so first rather than be
   asked.
2. **Target the client ID, not the OBO flag alone.** Any OAuth-authenticated
   access sets `request.is_on_behalf_of`, including the CLI, the SDKs, and the
   Statement Execution API, so a policy written on that attribute alone also
   catches humans. Condition on our specific `request.client_id`.
3. **Values are case-sensitive.** A policy testing `'True'` rather than `'true'`
   matches nothing and fails open, masking no data while appearing configured.
4. **Absence resolves to `false`, and a misspelled key raises.** Phrase
   conditions so a missing attribute *restricts* rather than grants. Note also
   that personal access tokens do not set these attributes.

Feature status: ABAC row filter and column mask policies, governed tags, and
data classification are **GA**; the request-context attributes are **Beta**. The
GA fallback, if previews are unacceptable, is either a blanket mask on
CCI-tagged columns in scope — blunt, because it affects direct user queries too
— or app-side tool disablement per 32.3. Sources:
[ABAC core concepts](https://docs.databricks.com/aws/en/data-governance/unity-catalog/abac/core-concepts),
[CREATE POLICY](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-ddl-create-policy),
[policy evaluation](https://learn.microsoft.com/en-us/azure/databricks/data-governance/unity-catalog/abac/policy-evaluation).

### App-side tag pre-flight — offered, not recommended as primary

A pre-flight lookup of table and column tags before running a query, refusing
when a CCI tag is present, is implementable for our own SQL routes and REST
calls. We can offer it as defence in depth, but it should not be presented as
the control, for three reasons: it requires parsing model-generated SQL to know
which objects are referenced (fragile, and wrong in the unsafe direction); it is
bypassed by any other client; and it duplicates a decision Unity Catalog already
makes correctly. If ISRP wants an application-layer assertion, the honest one is
32.3 — the ability to switch the data tools off entirely.

## Attribution: correlation, not a change to the auth model

Inference is signed by the app's service principal
(`AGENT_RUNTIME_LLM_AUTH=sp`) because per-user foundation-model entitlements
produced 403 "Unauthorized access to Org" for some users. Gateway usage
attribution and per-user rate limits therefore see the service principal, not
the end user.

The fix is correlation rather than re-litigating the SP exception. Model serving
accepts a **`client_request_id`** as a top-level key in the request body and
records it in the inference table alongside the Databricks-generated request id
and the full request and response payloads. The app can mint one id per turn,
send it with the call, and store it on the conversation turn and in
`action_logs`, which now hold the real username. Joining the inference table to
our records then yields per-user attribution over gateway-logged prompts without
any user needing a foundation-model entitlement.

Two implementation notes: the raw request JSON is logged either way, so an id
embedded in the body is recoverable even where `client_request_id` is not a
first-class column (Unity AI Gateway inference tables expose `request_id` and
`invocation_id`); and an unrecognized body key can be rejected by some
endpoints.

**This is now built** (32.7). The rejection concern was handled by adaptation
rather than by a setting: the id is sent by default, and a model that refuses it
is recorded and retried without it, matching how `llm_params` already learns
which optional parameters an endpoint will not take. A deployment therefore gets
attribution wherever the endpoint supports it and a working assistant
everywhere else, with no configuration to get wrong. The app-side half — the id
logged next to the resolved username — happens regardless, so even an endpoint
that discards the field leaves a timestamped record of who was talking to which
model.

## Compensating controls in the application

| # | Control | Status | Notes and evidence |
| --- | --- | --- | --- |
| 32.1 | **In-app notice and agent primer.** A line under the message box states that answers are generated, can be wrong, and that conversations are saved; the agent's own primer says the same, so it answers consistently when asked. | **In place** | `src/components/AgentConversation.tsx`, `server/services/app_help.py` (`APP_PRIMER`), with the fuller version in `server/services/app_guide.md` and `src/pages/UserGuidePage.tsx`. |
| 32.2 | **Minimize what the prompt carries.** *Tell the assistant what is on screen* controls whether the dashboard summary — widget names, titles, configuration — reaches the model at all. | **In place**, default on | Setting `send_dashboard_context`, enforced in `server/services/agent_runtime.py::_system_prompt` rather than in the browser, so a stale client cannot defeat it. Default preserves current answer quality; a deployment where widget configuration is itself sensitive turns it off. |
| 32.3 | **Admin kill-switches** for the Genie MCP server, the SQL tool, and native image/PDF-to-model, so a high-sensitivity workspace can run "chat about the app and attached files only". | **In place**, default on | `enable_genie_tool`, `enable_sql_tool`, `enable_native_file_passthrough` in `server/services/settings_store.py`. **This is the control that covers the Genie gap above.** Applied where the tool list is built, so a disabled tool is never advertised to the model and a saved agent that names it cannot bring it back. Defaults match today's behaviour so nothing changes until an admin decides. |
| 32.4 | **Log metadata, not payloads, in the app**: tool name, argument *names*, duration, result size. Full payload capture is the gateway's job — duplicating it in Lakebase *increases* the amount of CCI we store. | **In place** | `server/services/agent_runtime.py::_run_tool`. Argument values are excluded deliberately: that is where the filters and identifiers live, and logs outlive the conversation and are read by more people than the chat is. |
| 32.5 | **A single enforced cap on tool results** (8,000 characters), applied at the one funnel every tool path passes through, and stated in-band when it truncates so the model does not summarise a clipped table as the whole thing. | **In place** | `server/services/agent_runtime.py::_truncate_result`. Individual paths capped their own output before; this covers paths added later too. |
| 32.6 | **Retention and deletion.** *Delete conversations after (days)* removes untouched chats and their attachments for everyone; **Delete all my conversations** lets a user remove their own history at once. | **In place**, default 0 | `server/services/conversation_store.py`, `server/routes/conversations.py`, `src/components/ConversationHistory.tsx`. Default 0 keeps them indefinitely, because the retention period is a policy decision rather than an engineering default. No scheduler exists, so the sweep runs off the conversation-list request, throttled hourly per environment and non-fatal. |
| 32.7 | **`client_request_id` correlation** per the attribution section above. The app mints one id per chat turn, logs it with the resolved username, and sends it with the model call. | **In place** | `server/services/agent_runtime.py`. Sent via `extra_body` and best-effort: an endpoint that rejects the field is remembered per model and the call retried without it, so a refusal costs traceability rather than the user's answer. This is what makes an SP-signed gateway row attributable to a person. |
| 32.8 | **Network isolation for author-written Python tools.** | Deferred | The subprocess strips the app's credentials and caps time and memory, but can still reach the network. A proper fix needs a network namespace or an external execution service. Mitigated meanwhile by the documented requirement that Python tool authoring is restricted to people who have completed secure-development training, and that new tools are read before their agent gains domain or global visibility (`server/services/app_guide.md`, `src/pages/UserGuidePage.tsx`). |

### Already true, and worth citing under this finding

- **Inference is the only service-principal path.** Every tool call — SQL,
  Genie, Unity Catalog, author-written Python — executes under the caller's OBO
  token, so no tool can read data the user cannot
  (`server/services/agent_runtime.py`).
- **A file's contents never enter the prompt.** Attachments contribute a
  constant-size profile; the agent must pull what it needs through structured
  tools (`server/services/upload_tools.py`).
- **No model-authored code is evaluated in the web process**, which holds the
  caller's credentials. `query_file` takes a structured spec rather than a
  pandas or SQL string, and author-written Python tools run in a subprocess with
  credentials stripped from the environment.
- **A stored setting cannot redirect model traffic.** `model_params` is
  restricted to a closed key list, enforced on save and again on read, so no
  configuration value can introduce a `base_url` that would send prompts and the
  app credential to another host (`server/services/llm_params.py`).

## Platform-level

- **Whether Red CCI may reach Databricks foundation models, the AI Gateway, or
  Genie at all is Qualcomm GenAI policy**, not something Command Center can
  certify. Our commitment is that the app can be configured to comply either
  way.
- **Unity Catalog governed tags, ABAC policies, classification, column masking,
  and row filters** are the real control on the data itself. Guardrails see the
  prompt; they do not see a table a widget renders directly.
- **AI Gateway payload logging and usage tracking** are the monitoring ISRP
  wants, and they live in Unity Catalog rather than in the app.
