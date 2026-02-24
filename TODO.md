# Widget Architecture Migration Plan

## Phase 1: Database Migration
- [ ] Design database schema for all widgets (currently in `widgetRegistry.ts`)
- [ ] Create API endpoints for CRUD operations on core widgets
- [ ] Migrate existing hardcoded widgets to the database
- [ ] Remove hardcoded `widgetRegistry` definitions

## Phase 2: Dynamic Loading
- [ ] Update `widgetRegistry` loader to fetch all widgets (core + custom) from the database on startup
- [ ] Implement lazy loading/dynamic imports for widget components to reduce bundle size
- [ ] Ensure `useScript` and Babel evaluation works seamlessly for all dynamically loaded widgets

## Phase 3: Environment Promotion
- [ ] Implement an API to transfer widget records from one environment to another
- [ ] Update Admin Dashboard UI with a "Widget Promotion" tab
- [ ] Add promotion workflow in Admin UI to securely push a widget definition from the Dev database to the Test/Prod databases
- [ ] Include conflict resolution for updating existing widgets in target environments based on Widget IDs/Versions