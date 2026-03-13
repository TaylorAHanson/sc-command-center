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
- **Styling**: Tailwind CSS utilizing the Qualcomm brand color scheme.
- **Ecosystem**: A flexible widget-based architecture where individual widgets are isolated React components rendered within a responsive grid layout.

### Backend
- **Framework**: FastAPI (Python) located in `server/main.py`.
- **API Features**: Serving as a robust API Gateway connecting the frontend application to various enterprise tools. Support for local proxy headers and automated authentication middleware.
- **Databases**: Hosted Lakebase (Postgres) databases divided by environment (dev, test, prod) storing core application state including roles, configured views, custom widget states, and the action logs required for the AI Maturity Model.

### Integrations
The backend natively integrates with various enterprise tools:
- **Databricks**: Executing Databricks Jobs and querying SQL Warehouses.
- **n8n**: Triggering automations and workflows.
- **Tableau**: Fetching and interacting with enterprise reporting.
- **Genie & Custom Agents**: Invoking localized intelligent assistants for data analysis and proactive actions.
- **Anything else**: If you need to integrate with another tool, you can add it. This may require adding a new API endpoint in the backend.

#### Integration Security & Governance
When building new widgets and integrating with external tools, you must adhere to strict security and governance standards. The integration paradigm depends on whether the integration requires sensitive credentials:

**Frontend-Only Integrations (e.g., Tableau Embeds)**
If an external tool supports secure, client-side embedding (such as an iframe for a Tableau dashboard) where the authentication is natively handled by the tool in the browser, you can build the widget entirely in the frontend.
* **Governance Rule**: This approach is ONLY permitted if the external tool handles its own session securely and does not expose sensitive tokens, API keys, or data to the client's local storage or network traffic. Never hardcode credentials in the frontend.

**Backend-Mediated Integrations (e.g., Databricks, Custom APIs)**
If an integration requires static secrets, service principal credentials, complex orchestration, or database access, it **MUST** be routed through the FastAPI backend. You must create a new API endpoint in `server/routes/`.
* **Governance Rule**: The frontend must never hold raw API keys, machine-to-machine secrets, or database credentials. The backend acts as a secure, authenticated proxy to these enterprise services, enforcing RBAC access control and preventing secret leakage.

#### On-Behalf-Of (OBO) Integrations
All integrations must use On-Behalf-Of (OBO) authentication to do anything on the Databricks platform, like SQL Queries. This means that the frontend will make a request to the backend, and the backend will make a request to Databricks on behalf of the user, using their credentials and entitlements.

## Operations Manual: 

### Roles System

The Command Center employs a dynamic Role-Based Access Control (RBAC) system to govern who can view, edit, or administer different dashboard "Domains". This includes the ability to create and manage views and widgets and promote them to other environments.

#### Concepts
- **Domains**: Logical groupings of views and widgets (e.g., "Enterprise", "Finance", "Supply Chain", "Sales", "Marketing", "Product", "Engineering", "HR", "Finance", "Legal", etc.).
- **External Roles**: There exists an admin screen on which an admin can map and external role (qgroup) to a domain and permission level combination.
  - Example: "Supply Chain" domain + "viewer" permission level = "supply-chain-viewers" qgroup.
- **Domain Permission Levels**: Granular control levels within a domain:
  - `viewer`: Can only see the dashboards.
  - `editor`: Can modify dashboard layouts and create views.
- **Application Permission Levels**: Granular control levels within the application:
  - `admin`: Full control including managing user access mappings for the domain.

#### Managing Access
Access control mappings are administered entirely through the Command Center UI. Users with `admin` privileges can navigate to the **Access Management** screen to easily configure roles. 
From this interface, administrators can add new rules to link an external role (qgroup) to a specific domain and designate the appropriate permission level (`viewer`, `editor`, or `admin`). The UI provides a clear, at-a-glance view of all existing role bindings, allowing seamless updates or removals of access without needing to interact with the backend code or database directly.

### Promoting Work (Widgets & Views)
The Command Center manages separate database environments (`dev`, `test`, `prod`). As you develop widgets and configure views, you will need to promote them through the environments. This ensures that experimental work doesn't impact production users.

*   **Domain Access Limitations:** A user's ability to promote a widget or a view is strictly governed by the domains they have `admin` access to. You can only promote widgets and views that belong to your assigned domains. For example, a user who is an admin in the "Supply Chain" domain cannot promote widgets belonging to the "Finance" domain.

#### Promoting Widgets
Users with promotion access can manage widget lifecycles via the **Widget Promotion** screen in the admin UI. 
The interface displays a table of all widgets alongside their current versions in Dev, Test, and Prod. 
*   **How to Promote/Rollback**: Under the target environment column, select the desired version number from the dropdown. 
    *   Selecting a version *higher* than the current environment's version will prompt a **Promote Widget** confirmation. 
    *   Selecting a version *lower* than the current version will prompt a **Roll Back** confirmation.
*   **Certification**: In the Prod environment column, you can click the **Certify** button to formally flag a widget as enterprise-ready (`is_certified`).
*   **Preview & History**: You can click **Preview** to render a live version of the widget at a specific version, or **Version History** to see an audit trail of authors and timestamps.

#### Promoting Views
Global view layouts are managed similarly via the **View Promotion** screen. 
*   **How to Promote/Rollback**: Use the version dropdowns beneath the Dev, Test, or Prod columns to change the active version of a view in that environment.
*   **What to Check**: Before promoting a view, ensure that **all widgets** included in that view have already been successfully promoted to the target environment. If a view references a widget ID that doesn't exist in the target environment, the view may fail to render correctly.

#### Temporary Note
RBAC is under development and will be fully implemented in a future release. Additional development and careful testing is required before production use. 

## Contributing to the Codebase

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
   - **Domain:** Assign the widget to a specific domain (e.g., `Supply Chain`, `Finance`) to enforce Role-Based Access Control (RBAC). Only users with access to that domain can view or use the widget.
   - **Default Dimensions:** Specify the widget's default layout grid width (cols) and height (rows).
   - **Data Source:** Select the data external provider type (`None`, `API`, or `SQL`). Provide the desired URL or SQL Query, and click the **Test & Extract Schema** button to securely send a test request and preview the structured data available for your widget code.
   - **Is Executable Action:** Check this box if the widget is designed to trigger external pipelines, submit forms, or execute actions rather than strictly displaying data. This is the toggle that labels a widget an "effect" in our cause and effect data collection system, explained at the top.
   - **Configuration Mode:** Control if end-users can customize dynamic inputs for the widget (`None`, `Allowed`, or `Required`). If enabled, build a Configuration Schema to specify which properties (like target URLs, chart colors, or thresholds) users can define.

2. **Implementing the Widget (`TSX Editor` Mode):**
   - Use the built-in code editor to write the React component for your widget. 
   - **Styling:** The environment uses Tailwind CSS. Ensure you use dark text colors (e.g., `text-slate-800`, `text-gray-900`) for accessibility, as widgets render on a white background. Never use arbitrary Tailwind values (`w-[150px]`); stick to standard classes or inline styles.
   - **Responsiveness:** Ensure your widget adapts gracefully to different heights and widths (use `w-full`, `h-full`).
   - **Telemetry:** When implementing buttons or interactions, utilize the exposed `logAction` function to record user telemetry for the AI Maturity Model.

3. **Preview & Publish:**
   - Use the **Preview** toggle to test your widget's appearance and functionality in real-time.
   - Once satisfied, click **Publish** (or **Update** if editing an existing widget) to save it to the database. It will immediately become available in the Widget Library for authorized users to add to their dashboard views.

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
