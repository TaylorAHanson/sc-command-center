# Enterprise Command Center - AI Context & Discoveries

*Note: This file is intended for AI development context. As an AI assistant, you should continually update or edit this file as new discoveries or quirks are noticed in the codebase.*

## Architecture Overview
- **Frontend**: React SPA using TypeScript and Vite. Widgets are rendered in a grid layout (likely `react-grid-layout`).
- **Backend**: FastAPI (Python) functioning as an API gateway. Handles RBAC, widget states, and proxying to enterprise services.
- **Database**: Lakebase (Postgres).

## Key Patterns & Rules
- **Integration Security**: 
  - Frontend-only is fine for iframe-style embeds that manage their own secure session.
  - Backend-mediated integrations are REQUIRED for secrets, service principals, or DB access. The frontend must NEVER hold API keys.
- **Authentication (OBO)**: On-Behalf-Of (OBO) authentication is strictly enforced for Databricks interactions (like SQL Queries).
- **Widgets**:
  - All widgets are built via the **Widget Studio** UI dynamically, stored in the DB, rather than as static files in the repository.
  - Complex widgets use a hybrid model: built in Widget Studio, but their API is contributed as a single file in `server/routes/custom_widgets/`.
  - Custom widget APIs MUST use `@router.get("/data")` (or similar) and use `obo_token: str = Depends(get_obo_token)` for auth. DO NOT use service principals.
  - Widgets use `logAction` to send telemetry back for the 4-stage AI Maturity Model if marked as "Executable"
- **RBAC**: Implemented with "Domains" (e.g., Supply Chain, Finance) mapped to external roles (qgroups) with permissions like `viewer`, `editor`, `admin`. This is only for this app itself, not the content of widgets.

## Known Quirks & Bugs to Track
- **Screen Jumping/Scrolling**: [Fixed/Pending] Submitting buttons or typing text into widgets causes the screen to jump or scroll unexpectedly. Might be related to layout re-calculation or component re-renders.
- **Drag & Drop Flickering**: [Fixed/Pending] On moving/dropping a widget, its original position reappears briefly. Likely an optimistic UI failure during the delay of saving to the database.

*Update this file as new architectural decisions, bug fixes, or patterns are established.*
