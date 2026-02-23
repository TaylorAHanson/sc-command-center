# TODO

## Widget Studio
The widget studio is a new feature that will allow users to create, preview, and publish their own custom widgets dynamically through natural language interaction.

### 1. User Experience & UI Layout
- **Full-Screen Workspace:** The widget studio will be a dedicated full-screen view, similar to the admin page.
- **Split-Pane Design:** 
  - **Left Pane (Chat & Controls):** A chat interface for communicating with the AI agent, along with configuration panels (data sources, parameters).
  - **Right Pane (Workspace):**
    - *Live Preview Mode:* A real-time rendering of the generated widget, updating automatically.
    - *Code Editor Mode:* A manual code editor (e.g., Monaco Editor) showing the underlying React/TSX code. Users can toggle between Preview and Code, allowing them to make manual tweaks if the AI doesn't get it perfectly right.
- **Actions:** A clear set of actions such as 'Revert', 'Accept', and 'Save/Publish' to commit the widget to the global widget registry.
- **Editing & Cloning:** Users can start from scratch or leverage existing widgets:
  - *Clone Global Widgets:* Users can select a pre-existing, globally registered widget, duplicate it, and modify it in the studio.
  - *Edit Custom Widgets:* Users can re-open any of their previously created custom widgets. This should restore the current state and allow them to continue making iterative adjustments or code improvements.

### 2. Agent & Code Generation Flow
- **Natural Language to Code:** An AI agent will take the user's natural language description and generate React/TSX code adhering to our existing widget design guidelines.
- **Model Hosting:** We will utilize Databricks-hosted models (e.g., Llama 3 or similar), accessed via the standard OpenAI-compatible API spec. This allows us to use standard tooling without custom API integrations.
- **Context Injection:** The system prompt will include the project's styling system, available internal UI components, and the `registerWidget` API contract.
- **Iterative Refinement:** The user can converse with the agent to request layout tweaks, color changes, or logic updates directly in the chat window.

### 3. Data & Configuration Handling
- **Data Sources:** Users can specify whether the widget is purely UI-driven or tied to a data source (e.g., a parameterized SQL query or API fetch). 
- **Configuration Modes:** Support for defining widget configuration parameters matching our registry schema:
  - `config_required` (requires setup before rendering on a dashboard).
  - `config_optional` (has defaults but can be overridden).
  - `isExecutable` integrations (like n8n triggers).
- **Metadata:** Auto-generation of standard widget metadata (`name`, `description`, `category`, `domain`, `defaultW`, `defaultH`).

### 4. Dynamic Frontend Architecture (Refactoring Required)
- **Dynamic Module Loading:** Widgets and the registry are currently hardcoded TSX files. We must transition to a system capable of fetching, transpiling (e.g., via Babel standalone or similar), and evaluating raw TSX code dynamically at runtime.
- **Component Sandboxing:** Ensure that dynamically injected components don't clash or cause global application crashes. React Error Boundaries are essential to isolate bad code.
- **Dynamic Registry:** The `registerWidget` function needs to support runtime additions without requiring a full application rebuild.

### 5. Backend Services & APIs
- **Agent Runner:** Build a backend service to orchestrate the LLM calls. This requires:
  - Managing prompts and system instructions specifically optimized for our widget TSX format.
  - Handling multi-turn conversation state.
- **Widget Storage API:** Endpoints to Save, Update, and Fetch custom widgets from the database (storing the raw TSX code, dependencies, and configuration metadata).
- **Data Source Schema Extraction:** The agent should be able to extract the schema of the data source from SQL or the API endpoint by testing it on the backend.

### 6. Testing & Self-Correction Loop
- **In-Browser Execution:** Leverage the browser environment to execute the generated code in a safe preview sandbox.
- **Automated Feedback Loop:** If the dynamically rendered TSX throws runtime errors or syntax errors, intercept the console output and React error boundary messages.
- **Auto-Retry:** Feed the isolated error logs automatically back to the backend Agent Runner so it can attempt self-correction and output fixed code without user intervention.

### 7. Test Prompts
- **Prompt 1:** I want a widget that shows 4 boxes in a grid, green, yellow, red, and black. These grids will have the current date in them using timezones in PST, hyderabad india, singapore, and nyc.
- **Prompt 2:** Let' make a widget that uses the API to show title, quote, poster, and plays the quote on click. 
  - Add the url: https://owen-wilson-wow-api.onrender.com/wows/random
- **Prompt 3:** create a table that uses this sql query to show in a table 
  - Add the sql query: select * from system.access.audit where event_time >= NOW() - INTERVAL 1 HOUR
- **Prompt 4:** Make a compact "Part Lookup" widget. It needs a search input field taking up 100% width, a blue 'Search' button below it, and a mock 'Recent Searches' list with 3 dummy part numbers. Include hover effects on the list items.
- **Prompt 5:** Create a "Live Inventory" KPI widget. It should just be a single massive number '24,592' in the center with a smaller green '+450' indicating a positive trend below it. Make it look sleek with a dark slate background and white text.
