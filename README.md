# Enterprise Command Center 

## Overview

### At first glance
On the surface, this app looks just like a highly configurable dashboarding tool where users select and add widgets to a grid.
They have the ability to create multiple views, and share with others.

### The deeper truth
This app is not just analytical/dashboards. It's a data collection platform.
The reason we want to pair "View Data" with "Take action" on one screen is to collect user telemetry. 
If we log the data, we have rows in a DB that are more or less cause and effect - user saw 'abc' so took action 'xyz'. 
This is ML training food! This is an actual strategic plan to implement the 4 stage AI maturity model.

### The 4 Stage AI Maturity Model
**Stage 1 (6 months):**
Manual control, log all user actions. What did they see, and what action they took based on that.

**Stage 2 (1 year):**
Train and serve ML model(s) to proactively nudge and suggest user actions. Continue collecting cause/effect data and refining models.

**Stage 3 (2 years):**
Proactive, agentic, tool based action taking with human-in-the-loop approval. Continue collecting cause/effect data and refining models.

**Stage 4 (3 years):**
Full automation with the option for human review, but mostly just model and agent tuning.

## Architecture

The Enterprise Command Center is an enterprise application composed of a modern frontend client paired with a FastAPI backend that acts as an API gateway.

### Frontend
- **Framework**: React Single Page Application (SPA) using TypeScript and Vite.
- **Styling**: Tailwind CSS utilizing the app's brand color scheme (`brand-navy`, `brand-blue`).
- **Ecosystem**: A flexible widget-based architecture where individual widgets are isolated React components rendered within a responsive grid layout.

### Backend
- **Framework**: FastAPI (Python) located in `server/main.py`.
- **API Features**: Serving as a robust API Gateway connecting the frontend application to various enterprise tools. Support for local proxy headers and automated authentication middleware.
- **Databases**: A hosted Lakebase (Postgres) database per deployment, storing core application state including access lists, configured views, custom widget states, and the action logs required for the AI Maturity Model.

### Integrations
The backend natively integrates with various enterprise tools:
- **Databricks**: Executing Databricks Jobs and querying SQL Warehouses.
- **n8n**: Triggering automations and workflows.
- **Tableau**: Fetching and interacting with enterprise reporting.
- **Genie & Custom Agents**: Invoking localized intelligent assistants for data analysis and proactive actions.
- **Anything else**: If you need to integrate with another tool, you can add it. This may require adding a new API endpoint in the backend.

#### AI Assistant Panel
The right-hand **Assistant** panel is a native chat experience backed by an
external agent service (e.g. the Supply Chain Agent), kept in its own codebase
so it stays reusable as a template. The Command Center never talks to the agent
from the browser directly — requests are proxied through the FastAPI backend
(`server/routes/agent_proxy.py`) so the agent's URL and credentials stay
server-side, per the governance rules above. Configure the target with the
`AGENT_BASE_URL` environment variable (defaults to `http://localhost:8001`).
Locally, run the agent backend on a port other than `8000` to avoid colliding
with this app's backend.

On every message, the panel transparently emits the active view's context
(widget titles, descriptions, and configurations, plus the user's email and
roles — see *Emitters and Receivers*) as a hidden preamble, so the assistant is
always grounded in what the user is currently looking at.

#### Integration Security & Governance
When building new widgets and integrating with external tools, you must adhere to strict security and governance standards. The integration paradigm depends on whether the integration requires sensitive credentials:

**Frontend-Only Integrations (e.g., Tableau Embeds)**
If an external tool supports secure, client-side embedding (such as an iframe for a Tableau dashboard) where the authentication is natively handled by the tool in the browser, you can build the widget entirely in the frontend.
* **Governance Rule**: This approach is ONLY permitted if the external tool handles its own session securely and does not expose sensitive tokens, API keys, or data to the client's local storage or network traffic. Never hardcode credentials in the frontend.

**Backend-Mediated Integrations (e.g., Databricks, Custom APIs)**
If an integration requires static secrets, service principal credentials, complex orchestration, or database access, it **MUST** be routed through the FastAPI backend. You must create a new API endpoint in `server/routes/`.
* **Governance Rule**: The frontend must never hold raw API keys, machine-to-machine secrets, or database credentials. The backend acts as a secure, authenticated proxy to these enterprise services, enforcing access control and preventing secret leakage.

#### On-Behalf-Of (OBO) Integrations
All integrations must use On-Behalf-Of (OBO) authentication to do anything on the Databricks platform, like SQL Queries. This means that the frontend will make a request to the backend, and the backend will make a request to Databricks on behalf of the user, using their credentials and entitlements.

## Operations Manual: 

### Sharing and Permissions

The Command Center shares content the way a Databricks dashboard does. Views, widgets and agents each carry their own access list; there are no domain roles.

#### Concepts
- **Access levels**: Each entry on an access list grants one of two levels:
  - **Can use** (`USE`): see and open the latest published version, place a published widget on your own views, chat with a published agent.
  - **Can manage** (`MANAGE`): everything Can use allows, plus edit the draft, publish, discard, revert, certify widget versions, change the access list, and archive or delete.
- **Principals**: An entry names a Databricks user (matched ignoring case), a Databricks group (its exact display name), or **Everyone in this app**. The highest level a person gets through any entry wins.
- **Owner**: Whoever creates a view, widget or agent gets Can manage automatically. An access list must keep at least one manager.
- **Administrators**: A short list of users and groups who can manage everything and are the only people who see the Admin Panel.
- **Domains**: Labels such as "Finance" or "Supply Chain" for filtering the Widget Library. They grant nothing.
- **Anyone can build**: Widget Studio and Agent Studio are open to every signed-in user; what they build is private until shared.

A published view carries its widgets: anyone who can use the view sees each widget on it at its published version, without the widget being shared separately. It does not carry its pinned agent, which must be shared on its own. Links open only for people something is shared with; anyone else gets the same "not found" as for something that doesn't exist.

#### Managing Access
Sharing is done from the **Share** button on a view, in Widget Studio or in Agent Studio, by anyone with Can manage. Changes save immediately. Administrators are managed under **Admin Panel → Administrators**, and **Admin Panel → Content** lists every view, widget and agent with its owner and sharing, so an Administrator can reassign something whose owner has left. No database work is needed for either.

The upgrade to sharing migrated the old domain role mappings once: on widgets, global views and domain agents whose domain is exactly the mapping's (General when none was set), `viewer` became Can use and `editor` and `admin` became Can manage. Owners got Can manage, people subscribed to a view got Can use, only global agents became shared with everyone, and an `admin` mapping on Global, All or App made that principal an Administrator; a viewer or editor mapping on those names covered only items literally under them. If nobody ended up an Administrator, the workspace `users` group was added, so review **Admin Panel → Administrators** afterwards.

The move ran once per deployment and records each step (done, skipped or failed) in the `cutover_log` table of the settings schema. A failed step is not retried on restart; the Admin Panel shows a notice whose **View details** lists what happened and offers **Retry**.

### Drafts and Publishing (Widgets, Views & Agents)
Every view, widget and agent has one **draft** and any number of **published versions**. Managers edit the draft, which is saved in place and adds no version; **Publish** turns it into the next version, which is what people with Can use see. **History** lists published versions, **Revert** copies one back into the draft, and **Discard draft** drops unpublished changes.

*   **Publishing a view** runs a preflight that lists widgets and the pinned agent that are unpublished or have unpublished changes, and offers to publish them together with the view. With **Shared views may only contain certified widgets** on (Admin Panel → Settings), a view shared with anyone besides its owner can't be published while any widget on it is uncertified; private views are never affected.
*   **Publishing a widget** re-runs the same safety check as saving it.
*   **Certification** belongs to one published widget version and is set by its managers, by default on the latest published version. A new version starts uncertified.
*   **Discard draft** is refused for something never published; delete it instead.
*   **Archiving** a view hides it from everyone's sidebar and stops its link opening; managers restore it, or delete it permanently, from **Archived**. A shared view must be archived before it can be deleted; a private one can be deleted directly.
*   People with Can use always see the published version. A widget on a view that has no published version shows a "Not published yet" card to them.

Data Migration snapshots are format 2: they carry drafts, access lists and Administrators. Format-1 snapshots from before sharing still import, and their role mappings are converted the same way as above.

There is no longer an in-app Dev / Test / Prod workspace or promotion. A one-time consolidation made Prod the published version and newer Dev (or Test) work the draft. Separate deployments (a dev app, stage, prod) remain, each with its own database, and content moves between them with **Admin Panel → Data Migration** snapshots.

### Optional features: off until set up
Three features need something set up outside the app. Until it is, each stays off and says why, and the rest of the app works. **Admin Panel → Settings → Setup** shows what is ready and the next step; the full steps are in the in-app User Guide under **Admin settings**.

*   **Email** (a widget's **Send** button, scheduled reports): verify a sender in Amazon SES, give the app an IAM user's keys as secret resources plus `AWS_REGION`, then set the From address in **Settings → Email**. A local run writes emails to the log instead of sending them.
*   **Scheduling** (reports and actions on a timer, run as the person who scheduled them, never as the app): an account admin adds an OAuth app connection (public client, SQL scope, 30-day refresh tokens, this app's `/api/oauth/callback` as the redirect URL) and pastes its client id in **Settings → Scheduling**. A `TOKEN_VAULT_KEY` secret is recommended. Each person then connects once.
*   **Hybrid view search** (Discover finds views by meaning, not just words): enable Lakebase Search on the Lakebase project. The app installs the extensions, builds the indexes and embeds views itself; without it, search uses keyword or word matching.

## Contributing to the Codebase

> **Working with an AI coding agent?** Start with [`AGENTS.md`](AGENTS.md), plus
> [`server/AGENTS.md`](server/AGENTS.md) and [`src/AGENTS.md`](src/AGENTS.md) for
> the backend and frontend. Those files carry the verified commands, the
> environment/schema model, and the platform gotchas; where they disagree with
> the sections below, they are the more current source.

### Repository Structure
```
client/
├── src/
│   ├── widgets/          # Individual widget React components
│   ├── pages/            # High-level views (e.g., ViewManager, WidgetStudio)
│   ├── widgetRegistry.ts # Registry where all widgets are exported
│   └── api.ts            # Client-side API functions
server/
├── main.py               # FastAPI application entry point
├── database.py           # Lakebase/Postgres connection and migrations
└── routes/               # API Router modules (e.g., roles.py, actions.py)
```

### Local Development
To run the project locally:

1. **Start the Development Servers**
   Use the provided bash script to start both the Python backend and the React dev server simultaneously:
   ```bash
   ./dev.sh
   # Note: The backend runs natively on port 8000 and the vite server runs on its default port.
   ```

2. Commit and push using standard Gitflow (feature/my-feature is pushed, PR to merge that to develop, etc.)

3. External teams may contribute using the open source software development model. Create an issue, create a fork, make changes, and submit for PR.

## Widget Guidance

The Enterprise Command Center no longer requires manually writing widget files into the source code. Instead, all widgets are created and managed dynamically via the built-in **Widget Studio** UI.

### Creating and Editing Simple Widgets
To create a new widget or modify an existing one, navigate to the **Widget Studio** within the application. 

1. **Configuration (`Settings` Mode):**
   - **Name & Description:** Define a descriptive name and brief explanation for your widget.
   - **Category:** Organize the widget within the library (e.g., `Analytics`, `Monitoring`, `Actions`).
   - **Domain:** Label the widget with a business area (e.g., `Supply Chain`, `Finance`) so people can filter for it in the Widget Library. It does not control access; **Share** does.
   - **Default Dimensions:** Specify the widget's default layout grid width (cols) and height (rows).
   - **Data Source:** Select the data external provider type (`None`, `API`, or `Databricks API`). Provide the desired URL or path, and click the **Test & Extract Schema** button to securely send a test request and preview the structured data available for your widget code. There is no SQL option: for tables, leave it on `None` and name the table to the agent, which writes the SQL into the widget and runs it to check it. Widgets saved earlier with a SQL data source keep it, read-only.
   - **Is Executable Action:** Check this box if the widget is designed to trigger external pipelines, submit forms, or execute actions rather than strictly displaying data. This is the toggle that labels a widget an "effect" in our cause and effect data collection system, explained at the top.
   - **Configuration Mode:** Control if end-users can customize dynamic inputs for the widget (`None`, `Allowed`, or `Required`). If enabled, build a Configuration Schema to specify which properties (like target URLs, chart colors, or thresholds) users can define.

2. **Implementing the Widget (`TSX Editor` Mode):**
   - Use the built-in code editor to write the React component for your widget. 
   - **Styling:** The environment uses Tailwind CSS. Ensure you use dark text colors (e.g., `text-slate-800`, `text-gray-900`) for accessibility, as widgets render on a white background. Never use arbitrary Tailwind values (`w-[150px]`); stick to standard classes or inline styles.
   - **Responsiveness:** Ensure your widget adapts gracefully to different heights and widths (use `w-full`, `h-full`).
   - **Telemetry:** When implementing buttons or interactions, utilize the exposed `logAction` function to record user telemetry for the AI Maturity Model.

3. **Preview & Publish:**
   - Use the **Preview** toggle to test your widget's appearance and functionality in real-time.
   - Once satisfied, click **Save** to write your draft, **Share** to choose who can use it, and **Publish** to make the draft the version those people see in the Widget Library and on views.

### Creating and Editing Complex Widgets

For widgets that require a custom API or complex backend logic beyond the standard data sources, we use a highly opinionated hybrid contribution model. You will still build the UI component in the Widget Studio, but you must contribute your custom API directly to the codebase via a **fork and Pull Request (PR)**.

To have your PR accepted, you **must** adhere to the following strict guidelines:

1. **Single File Requirement**: Your entire custom API logic must be contained within a **single Python file** placed in the `server/routes/custom_widgets/` directory.
2. **Zero Modifications to Existing Files**: You must not change `main.py` or any other existing files. The backend is configured to **dynamically load** any `APIRouter` found in the `custom_widgets` directory.
3. **OBO Authentication Only**: You must use the On-Behalf-Of (OBO) authentication dependency for any Databricks interactions. Service Principal authentication is strictly prohibited for custom widget APIs.

#### The Required Template

Your single file must define an `APIRouter` named `router` so the dynamic loader can mount it. Here is the base template you **must** use:

```python
from fastapi import APIRouter, Depends
from server.auth import get_current_user, get_obo_token

# 1. The router MUST be named 'router' for the dynamic loader to find it
# 2. The prefix MUST start with /api/custom/ to avoid routing conflicts
router = APIRouter(
    prefix="/api/custom/my_unique_widget_name",
    tags=["Custom Widget: My Unique Widget"]
)

@router.get("/data")
async def get_widget_data(
    user: dict = Depends(get_current_user),
    obo_token: str = Depends(get_obo_token)
):
    """
    Fetch data for the custom widget using the user's OBO token.
    """
    # Use the obo_token to interact with Databricks securely on behalf of the user.
    # DO NOT use service principal credentials here.
    
    return {
        "status": "success", 
        "user": user.get("username"),
        "data": "Your custom data here"
    }
```


Happy configuring! 🚀
